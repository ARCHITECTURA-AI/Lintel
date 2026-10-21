from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Response, UploadFile
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import storage
from ..db.models import Document, FactCandidate, ProfileFact, ProfileVersion
from ..deps import SESSION_COOKIE, UserCtx
from ..errors import bad_request, not_found
from ..serialize import row, rows
from ..services import facts as ledger
from ..services import ingestion, privacy
from ..services.core import audit
from .auth import me_payload

router = APIRouter(tags=["profile"])


class SettingsIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    weekly_budget: int | None = Field(default=None, ge=0, le=50)
    no_reply_days: int | None = Field(default=None, ge=3, le=90)
    hard_filters: dict[str, Any] | None = None
    targets: dict[str, Any] | None = None
    notification_prefs: dict[str, Any] | None = None
    onboarding: dict[str, Any] | None = None


@router.patch("/me")
def update_me(body: SettingsIn, ctx: UserCtx) -> dict:
    u = ctx.user
    data = body.model_dump(exclude_none=True)
    if "timezone" in data:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(data["timezone"])
        except Exception as exc:  # noqa: BLE001
            raise bad_request("bad_timezone", "Unknown time zone.") from exc
    if "onboarding" in data:
        data["onboarding"] = {**(u.onboarding or {}), **data["onboarding"]}
    for k, v in data.items():
        setattr(u, k, v)
    audit(ctx.db, u.id, "user", "settings.updated", "user", u.id, fields=sorted(data))
    return me_payload(u)


@router.get("/me/export")
def export(ctx: UserCtx) -> RawResponse:
    data = privacy.export_zip(ctx.db, ctx.user)
    audit(ctx.db, ctx.uid, "user", "account.exported", "user", ctx.uid)
    return RawResponse(data, media_type="application/zip",
                       headers={"Content-Disposition": 'attachment; filename="lintel-export.zip"'})


class DeleteIn(BaseModel):
    confirm: str


@router.post("/me/delete")
def delete_account(body: DeleteIn, ctx: UserCtx, response: Response) -> dict:
    if body.confirm.strip().lower() != ctx.user.email.lower():
        raise bad_request("confirm_mismatch", "Type your email address to confirm.")
    privacy.erase(ctx.db, ctx.user)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"deleted": True}


# -- documents and résumé ingestion -----------------------------------------


@router.post("/documents/resume")
async def upload_resume(ctx: UserCtx, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    doc, n = ingestion.upload_resume(ctx.db, ctx.user, data, file.filename or "resume", file.content_type or "")
    return {"document": row(doc, exclude={"parsed"}), "candidates": n}


@router.get("/documents")
def list_documents(ctx: UserCtx) -> list[dict]:
    docs = ctx.db.scalars(select(Document).where(Document.deleted_at.is_(None)).order_by(Document.created_at.desc()))
    return rows(docs, exclude={"parsed"})


@router.get("/documents/{doc_id}")
def get_document(doc_id: uuid.UUID, ctx: UserCtx) -> dict:
    doc = ctx.db.get(Document, doc_id)
    if doc is None:
        raise not_found("Document not found.")
    return row(doc)


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: uuid.UUID, ctx: UserCtx) -> RawResponse:
    doc = ctx.db.get(Document, doc_id)
    if doc is None or doc.deleted_at:
        raise not_found("Document not found.")
    return RawResponse(storage.get(ctx.uid, doc.storage_key), media_type=doc.content_type,
                       headers={"Content-Disposition": f'inline; filename="{doc.filename}"', "X-Content-SHA256": doc.sha256})


@router.get("/fact-candidates")
def candidates(ctx: UserCtx) -> list[dict]:
    q = select(FactCandidate).where(FactCandidate.status == "pending").order_by(FactCandidate.created_at, FactCandidate.id)
    return rows(ctx.db.scalars(q))


class ConfirmIn(BaseModel):
    statement: str | None = None
    claim_scope: str | None = None
    kind: str | None = None
    attributes: dict[str, Any] | None = None


@router.post("/fact-candidates/{cand_id}/confirm")
def confirm(cand_id: uuid.UUID, body: ConfirmIn, ctx: UserCtx) -> dict:
    fact = ingestion.confirm_candidate(ctx.db, ctx.user, cand_id, **body.model_dump(exclude_none=True))
    return row(fact)


@router.post("/fact-candidates/{cand_id}/reject")
def reject(cand_id: uuid.UUID, ctx: UserCtx) -> dict:
    ingestion.reject_candidate(ctx.db, cand_id)
    return {"ok": True}


class BulkIn(BaseModel):
    ids: list[uuid.UUID]


@router.post("/fact-candidates/confirm-many")
def confirm_many(body: BulkIn, ctx: UserCtx) -> dict:
    n = 0
    for cid in body.ids:
        c = ctx.db.get(FactCandidate, cid)
        if c and c.status == "pending":
            ingestion.confirm_candidate(ctx.db, ctx.user, cid)
            n += 1
    return {"confirmed": n}


# -- the fact ledger --------------------------------------------------------


@router.get("/facts")
def list_facts(ctx: UserCtx, include_history: bool = False) -> list[dict]:
    if include_history:
        facts = ctx.db.scalars(select(ProfileFact).order_by(ProfileFact.created_at))
        current = {f.id for f in ledger.current_facts(ctx.db)}
        return [row(f, current=f.id in current) for f in facts]
    return [row(f, current=True) for f in ledger.current_facts(ctx.db) if f.application_scope_id is None]


class FactIn(BaseModel):
    kind: str
    claim_scope: str
    statement: str = Field(min_length=1, max_length=2000)
    attributes: dict[str, Any] = Field(default_factory=dict)


@router.post("/facts")
def add_fact(body: FactIn, ctx: UserCtx) -> dict:
    fact = ledger.add_fact(ctx.db, ctx.uid, kind=body.kind, claim_scope=body.claim_scope, statement=body.statement,
                           attributes=body.attributes, source_type="user_entry", source_ref="added by you")
    return row(fact, current=True)


class SupersedeIn(BaseModel):
    statement: str | None = None
    claim_scope: str | None = None
    kind: str | None = None
    attributes: dict[str, Any] | None = None


@router.post("/facts/{fact_id}/supersede")
def supersede(fact_id: uuid.UUID, body: SupersedeIn, ctx: UserCtx) -> dict:
    fact = ledger.supersede(ctx.db, ctx.uid, fact_id, **body.model_dump(exclude_none=True))
    return row(fact, current=True)


@router.post("/facts/{fact_id}/retract")
def retract(fact_id: uuid.UUID, ctx: UserCtx) -> dict:
    ledger.retract(ctx.db, ctx.uid, fact_id)
    return {"ok": True}


@router.get("/facts/{fact_id}/history")
def fact_history(fact_id: uuid.UUID, ctx: UserCtx) -> list[dict]:
    return rows(ledger.history(ctx.db, fact_id))


@router.get("/profile-versions")
def profile_versions(ctx: UserCtx) -> list[dict]:
    return rows(ctx.db.scalars(select(ProfileVersion).order_by(ProfileVersion.created_at.desc()).limit(50)))
