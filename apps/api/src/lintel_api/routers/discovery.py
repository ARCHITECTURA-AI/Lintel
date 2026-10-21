from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db.models import Application, Job, WatchlistCompany
from ..deps import UserCtx
from ..errors import bad_request, not_found
from ..serialize import row
from ..services import discovery, feeds, registry
from ..services.core import audit

router = APIRouter(tags=["discovery"])


class DetectIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)


@router.post("/watchlist/detect")
def detect(body: DetectIn, ctx: UserCtx) -> dict:
    try:
        ref = feeds.detect(body.url)
    except feeds.FeedError as exc:
        raise bad_request("detect_failed", str(exc)) from exc
    return {"platform": ref.platform, "board": ref.board, "name": ref.name_guess, "posting_id": ref.posting_id,
            "region": ref.region}


class CompanyIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    name: str | None = Field(default=None, max_length=120)
    company_size: str | None = None


@router.get("/watchlist")
def list_watchlist(ctx: UserCtx) -> list[dict]:
    companies = list(ctx.db.scalars(select(WatchlistCompany).where(WatchlistCompany.active.is_(True)).order_by(WatchlistCompany.name)))
    counts = dict(ctx.db.execute(
        select(Job.watchlist_company_id, func.count()).where(Job.closed_at.is_(None), Job.target_match.is_(True))
        .group_by(Job.watchlist_company_id)).all())
    return [row(c, matched=counts.get(c.id, 0)) for c in companies]


@router.post("/watchlist")
def add_company(body: CompanyIn, ctx: UserCtx) -> dict:
    if body.company_size and body.company_size not in ("1-50", "51-200", "201-1000", "1000+"):
        raise bad_request("bad_size", "Pick a company size from the list.")
    c = discovery.add_company(ctx.db, ctx.user, body.url, company_size=body.company_size, name=body.name)
    return row(c)


class CompanyPatch(BaseModel):
    name: str | None = None
    company_size: str | None = None


@router.patch("/watchlist/{company_id}")
def patch_company(company_id: uuid.UUID, body: CompanyPatch, ctx: UserCtx) -> dict:
    c = ctx.db.get(WatchlistCompany, company_id)
    if c is None:
        raise not_found("Company not found.")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    return row(c)


@router.delete("/watchlist/{company_id}")
def remove_company(company_id: uuid.UUID, ctx: UserCtx) -> dict:
    c = ctx.db.get(WatchlistCompany, company_id)
    if c is None:
        raise not_found("Company not found.")
    c.active = False
    audit(ctx.db, ctx.uid, "user", "watchlist.removed", "watchlist_company", c.id)
    return {"ok": True}


@router.post("/watchlist/{company_id}/sync")
def sync_company(company_id: uuid.UUID, ctx: UserCtx) -> dict:
    c = ctx.db.get(WatchlistCompany, company_id)
    if c is None:
        raise not_found("Company not found.")
    result = discovery.sync_company(ctx.db, ctx.user, c, force=True)
    return {"company": row(c), "result": result}


@router.get("/jobs")
def list_jobs(ctx: UserCtx, company_id: uuid.UUID | None = None, matched: bool | None = None,
              include_closed: bool = False, q: str | None = None, limit: int = 200) -> list[dict]:
    stmt = select(Job).order_by(Job.target_match.desc(), Job.first_seen_at.desc()).limit(min(limit, 500))
    if company_id:
        stmt = stmt.where(Job.watchlist_company_id == company_id)
    if matched is not None:
        stmt = stmt.where(Job.target_match.is_(matched))
    if not include_closed:
        stmt = stmt.where(Job.closed_at.is_(None))
    if q:
        stmt = stmt.where(Job.title.ilike(f"%{q}%") | Job.company_name.ilike(f"%{q}%") | Job.location.ilike(f"%{q}%"))
    jobs = list(ctx.db.scalars(stmt))
    apps = {a.job_id: a for a in ctx.db.scalars(select(Application).where(Application.job_id.in_([j.id for j in jobs])))} if jobs else {}
    out = []
    for j in jobs:
        a = apps.get(j.id)
        dest = registry.for_host(ctx.db, j.host)
        out.append(row(j, exclude={"description", "questions"}, application_id=a.id if a else None,
                       application_state=a.state if a else None, fit_label=a.fit_label if a else None,
                       support_mode=registry.max_mode(dest).value))
    return out


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, ctx: UserCtx) -> dict:
    j = ctx.db.get(Job, job_id)
    if j is None:
        raise not_found("Job not found.")
    return row(j)


@router.post("/jobs/{job_id}/consider")
def consider(job_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = discovery.consider_job(ctx.db, ctx.user, job_id)
    return {"application_id": str(app.id), "state": app.state}


class ImportIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)


@router.post("/jobs/import")
def import_posting(body: ImportIn, ctx: UserCtx) -> dict:
    app = discovery.import_posting(ctx.db, ctx.user, body.url)
    return {"application_id": str(app.id), "state": app.state}
