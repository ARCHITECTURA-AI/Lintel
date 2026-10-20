"""Devices (web side) and the Local Runner's API (device side).

The runner makes outbound calls only. It sends step records and redacted evidence, never
cookies, passwords or browser state.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import Response as RawResponse
from lintel_schemas import FormModel, RunStepRecord
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from .. import storage
from ..config import get_settings
from ..db.models import ApplicationRun, RunnerDevice
from ..deps import AnonDb, DeviceCtx, UserCtx
from ..errors import ApiError, not_found
from ..security import new_token, new_user_code, signing_public_pem, token_hash
from ..serialize import row, rows
from ..services import execution
from ..services.core import audit, now

router = APIRouter(tags=["runner"])
RUNNER_VERSION_MIN = "0.1.0"


# -- web: devices ------------------------------------------------------------


@router.get("/devices")
def list_devices(ctx: UserCtx) -> list[dict]:
    devs = ctx.db.scalars(select(RunnerDevice).order_by(RunnerDevice.paired_at.desc()))
    out = []
    for d in devs:
        online = bool(d.last_seen_at and now() - d.last_seen_at < timedelta(seconds=45) and d.revoked_at is None)
        out.append(row(d, online=online))
    return out


class PairIn(BaseModel):
    user_code: str = Field(min_length=4, max_length=12)


@router.post("/devices/pair")
def approve_pairing(body: PairIn, ctx: UserCtx) -> dict:
    name = ctx.db.scalar(text("SELECT pairing_approve(:c)"), {"c": body.user_code.strip().upper()})
    return {"device_name": name}


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: uuid.UUID, ctx: UserCtx) -> dict:
    d = ctx.db.get(RunnerDevice, device_id)
    if d is None:
        raise not_found("Device not found.")
    d.revoked_at = now()
    for run in ctx.db.scalars(select(ApplicationRun).where(ApplicationRun.runner_device_id == d.id,
                                                           ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
        run.state = "cancelled"
        run.ended_reason = "device revoked"
    audit(ctx.db, ctx.uid, "user", "device.revoked", "runner_device", d.id)
    return row(d)


@router.post("/runs/{run_id}/resume")
def web_resume(run_id: uuid.UUID, ctx: UserCtx) -> dict:
    new = execution.resume_run(ctx.db, ctx.user, run_id)
    return row(new)


# -- device: pairing ----------------------------------------------------------


class PairStartIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(default="", max_length=80)


@router.post("/runner/pair/start")
def pair_start(body: PairStartIn, db: AnonDb) -> dict:
    device_code = secrets.token_urlsafe(32)
    user_code = new_user_code()
    db.execute(text("SELECT pairing_start(:d, :u, :n, :p, :t)"),
               {"d": token_hash(device_code), "u": user_code, "n": body.name, "p": body.platform, "t": timedelta(minutes=10)})
    s = get_settings()
    return {"device_code": device_code, "user_code": user_code, "verification_url": f"{s.web_origin}/devices?code={user_code}",
            "interval": 2, "expires_in": 600}


class PairPollIn(BaseModel):
    device_code: str
    runner_version: str = "0.1.0"


@router.post("/runner/pair/poll")
def pair_poll(body: PairPollIn, db: AnonDb) -> dict:
    token = new_token("lr")
    r = db.execute(text("SELECT status, device_id, user_id FROM pairing_complete(:d, :t, :v)"),
                   {"d": token_hash(body.device_code), "t": token_hash(token), "v": body.runner_version}).first()
    if r.status != "approved":
        return {"status": r.status}
    return {"status": "approved", "token": token, "device_id": str(r.device_id), "public_key_pem": signing_public_pem()}


# -- device: work --------------------------------------------------------------


@router.get("/runner/config")
def runner_config(ctx: DeviceCtx) -> dict:
    s = get_settings()
    return {"device_id": str(ctx.device.id), "device_name": ctx.device.name, "public_key_pem": signing_public_pem(),
            "user": {"email": ctx.user.email, "name": ctx.user.full_name},
            "limits": {"max_actions": s.run_max_actions, "max_recoveries": s.run_max_recoveries_per_step,
                       "max_active_minutes": s.run_max_active_minutes, "lease_seconds": s.run_lease_seconds}}


@router.post("/runner/claim")
def claim(ctx: DeviceCtx, response: Response) -> Any:
    a = execution.claim_next(ctx.db, ctx.user, ctx.device)
    if a is None:
        response.status_code = 204
        return None
    return a.model_dump(mode="json")


@router.post("/runner/runs/{run_id}/heartbeat")
def heartbeat(run_id: uuid.UUID, ctx: DeviceCtx) -> dict:
    return execution.heartbeat(ctx.db, ctx.device, run_id)


@router.post("/runner/runs/{run_id}/steps")
def steps(run_id: uuid.UUID, body: list[RunStepRecord], ctx: DeviceCtx) -> dict:
    return {"accepted": execution.record_steps(ctx.db, ctx.device, run_id, body)}


@router.post("/runner/runs/{run_id}/form")
def form(run_id: uuid.UUID, body: FormModel, ctx: DeviceCtx) -> dict:
    result = execution.report_form(ctx.db, ctx.user, ctx.device, run_id, body)
    from ..db.models import Application

    run = ctx.db.get(ApplicationRun, run_id)
    app = ctx.db.get(Application, run.application_id)
    a = execution.build_assignment(ctx.db, ctx.user, app, run, ctx.device) if run.kind in ("fill", "submit") else None
    return {**result, "assignment": a.model_dump(mode="json") if a else None}


class WaitIn(BaseModel):
    reason: str
    detail: str = ""


@router.post("/runner/runs/{run_id}/waiting")
def waiting(run_id: uuid.UUID, body: WaitIn, ctx: DeviceCtx) -> dict:
    execution.set_waiting(ctx.db, ctx.user, ctx.device, run_id, body.reason, body.detail[:300])
    return {"ok": True}


@router.post("/runner/runs/{run_id}/resume")
def resume(run_id: uuid.UUID, ctx: DeviceCtx) -> dict:
    new = execution.resume_run(ctx.db, ctx.user, run_id, device=ctx.device)
    from ..db.models import Application

    app = ctx.db.get(Application, new.application_id)
    return execution.build_assignment(ctx.db, ctx.user, app, new, ctx.device).model_dump(mode="json")


class CompleteIn(BaseModel):
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


@router.post("/runner/runs/{run_id}/complete")
def complete(run_id: uuid.UUID, body: CompleteIn, ctx: DeviceCtx) -> dict:
    execution.complete_run(ctx.db, ctx.user, ctx.device, run_id, {"summary": body.summary, **body.result})
    return {"ok": True}


class FailIn(BaseModel):
    reason: str


@router.post("/runner/runs/{run_id}/fail")
def fail(run_id: uuid.UUID, body: FailIn, ctx: DeviceCtx) -> dict:
    execution.fail_run(ctx.db, ctx.user, ctx.device, run_id, body.reason)
    return {"ok": True}


@router.get("/runner/runs/{run_id}/status")
def run_status(run_id: uuid.UUID, ctx: DeviceCtx) -> dict:
    run = ctx.db.get(ApplicationRun, run_id)
    if run is None:
        raise not_found("Run not found.")
    from ..db.models import Application

    app = ctx.db.get(Application, run.application_id)
    return {"state": run.state, "application_state": app.state, "cancel_requested": app.cancel_requested_at is not None}


class GuardIn(BaseModel):
    approval_id: uuid.UUID
    payload_hash: str


@router.post("/runner/applications/{app_id}/guard-check")
def guard_check(app_id: uuid.UUID, body: GuardIn, ctx: DeviceCtx) -> dict:
    return execution.guard_check(ctx.db, ctx.device, app_id, body.approval_id, body.payload_hash)


class IntentIn(BaseModel):
    approval_id: uuid.UUID
    payload_hash: str
    mode: str = "assisted_fill"


@router.post("/runner/applications/{app_id}/submit-intent")
def submit_intent(app_id: uuid.UUID, body: IntentIn, ctx: DeviceCtx) -> dict:
    fence = execution.begin_submit(ctx.db, ctx.user, ctx.device, app_id, body.approval_id, body.payload_hash, body.mode)
    return {"fence": fence}


class OutcomeIn(BaseModel):
    fence: int
    confirmation_text: str = Field(default="", max_length=4000)
    reference_number: str | None = Field(default=None, max_length=120)
    page_hash: str | None = None


@router.post("/runner/applications/{app_id}/outcome")
def outcome(app_id: uuid.UUID, body: OutcomeIn, ctx: DeviceCtx) -> dict:
    result = execution.record_outcome(ctx.db, ctx.user, ctx.device, app_id, body.fence, body.confirmation_text,
                                      body.reference_number, body.page_hash)
    return {"result": result}


class MismatchIn(BaseModel):
    diffs: list[dict[str, Any]]
    live_values: dict[str, Any] | None = None
    adopt: bool = False


@router.post("/runner/applications/{app_id}/guard-mismatch")
def mismatch(app_id: uuid.UUID, body: MismatchIn, ctx: DeviceCtx) -> dict:
    execution.guard_mismatch(ctx.db, ctx.user, ctx.device, app_id, body.diffs, body.live_values, adopt=body.adopt)
    return {"ok": True}


@router.post("/runner/applications/{app_id}/user-submitted")
def user_submitted(app_id: uuid.UUID, ctx: DeviceCtx) -> dict:
    from ..db.models import Application

    app = ctx.db.get(Application, app_id)
    if app is None:
        raise not_found("Application not found.")
    execution.report_user_submitted(ctx.db, ctx.user, app, "sent from the Lintel browser outside the Guard")
    return {"ok": True}


@router.get("/runner/documents/{sha256}")
def document(sha256: str, ctx: DeviceCtx) -> RawResponse:
    doc = execution.document_for_runner(ctx.db, sha256)
    data = storage.get(ctx.uid, doc.storage_key)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ApiError(500, "hash_mismatch", "Stored document does not match its hash.")
    return RawResponse(data, media_type=doc.content_type, headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'})


class PrepareIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)


@router.post("/runner/prepare")
def prepare(body: PrepareIn, ctx: DeviceCtx) -> dict:
    """`lintel prepare <url>` from the terminal: add a posting or a careers page."""

    from ..services import discovery

    try:
        app = discovery.import_posting(ctx.db, ctx.user, body.url)
        return {"application_id": str(app.id), "link": f"{get_settings().web_origin}/applications/{app.id}"}
    except ApiError as exc:
        if exc.code != "not_a_posting":
            raise
        company = discovery.add_company(ctx.db, ctx.user, body.url)
        return {"company_id": str(company.id), "link": f"{get_settings().web_origin}/watchlist"}


@router.get("/runner/runs")
def recent_runs(ctx: DeviceCtx) -> list[dict]:
    return rows(ctx.db.scalars(select(ApplicationRun).order_by(ApplicationRun.created_at.desc()).limit(20)))
