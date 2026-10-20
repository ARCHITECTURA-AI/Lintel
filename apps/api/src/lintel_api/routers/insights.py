"""Outcomes, follow-ups, contacts, notifications, the registry, metrics, the dashboard and the
public Trust Report."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..config import ROOT, get_settings
from ..db.models import (
    Application,
    ApplicationEvent,
    Contact,
    Destination,
    FollowUp,
    Job,
    Notification,
    PushSubscription,
    RunnerDevice,
    UserTask,
    WatchlistCompany,
)
from ..deps import UserCtx
from ..errors import ApiError, bad_request, not_found
from ..serialize import row, rows
from ..services import facts as ledger
from ..services import grounding, outcomes
from ..services.core import audit, now

router = APIRouter(tags=["insights"])


# -- outcomes and follow-ups ------------------------------------------------------


@router.get("/outcomes/review")
def review(ctx: UserCtx, weeks: int = 12) -> dict:
    return outcomes.weekly_review(ctx.db, ctx.user, weeks=max(1, min(weeks, 52)))


@router.get("/follow-ups")
def follow_ups(ctx: UserCtx) -> list[dict]:
    pairs = ctx.db.execute(
        select(FollowUp, Application, Job, Contact)
        .join(Application, Application.id == FollowUp.application_id)
        .join(Job, Job.id == Application.job_id)
        .outerjoin(Contact, Contact.id == FollowUp.contact_id)
        .order_by(FollowUp.due_at)
    ).all()
    return [row(f, job={"title": j.title, "company_name": j.company_name}, application_state=a.state,
                contact={"name": c.name, "relationship": c.relationship, "email": c.email} if c else None)
            for f, a, j, c in pairs]


class MarkIn(BaseModel):
    status: str


@router.post("/follow-ups/{fu_id}/mark")
def mark(fu_id: uuid.UUID, body: MarkIn, ctx: UserCtx) -> dict:
    return row(outcomes.mark_follow_up(ctx.db, fu_id, body.status))


@router.post("/follow-ups/{fu_id}/draft")
def draft_now(fu_id: uuid.UUID, ctx: UserCtx) -> dict:
    fu = ctx.db.get(FollowUp, fu_id)
    if fu is None:
        raise not_found("Follow-up not found.")
    app = ctx.db.get(Application, fu.application_id)
    fu.draft, fu.draft_sentences = outcomes.draft_follow_up(ctx.db, ctx.user, app)
    fu.status = "ready"
    return row(fu)


# -- contacts (entered by the user, never scraped) ------------------------------------


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=120)
    relationship: str = "acquaintance"
    email: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=1000)


@router.get("/contacts")
def list_contacts(ctx: UserCtx) -> list[dict]:
    return rows(ctx.db.scalars(select(Contact).order_by(Contact.company, Contact.name)))


@router.post("/contacts")
def add_contact(body: ContactIn, ctx: UserCtx) -> dict:
    if body.relationship not in outcomes.RELATIONSHIP_RANK:
        raise bad_request("bad_relationship", "Pick a relationship from the list.")
    c = Contact(user_id=ctx.uid, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    # Contacts at a company you're applying to turn a referral nudge into a suggestion.
    for t in ctx.db.scalars(select(UserTask).where(UserTask.type == "referral", UserTask.status == "open")):
        if (t.data or {}).get("company", "").lower() == c.company.lower() and t.application_id:
            t.status, t.resolved_at = "done", now()
            outcomes.referral_nudge(ctx.db, ctx.user, ctx.db.get(Application, t.application_id))
    return row(c)


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: uuid.UUID, body: ContactIn, ctx: UserCtx) -> dict:
    c = ctx.db.get(Contact, contact_id)
    if c is None:
        raise not_found("Contact not found.")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.updated_at = now()
    return row(c)


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: uuid.UUID, ctx: UserCtx) -> dict:
    c = ctx.db.get(Contact, contact_id)
    if c is None:
        raise not_found("Contact not found.")
    ctx.db.delete(c)
    return {"ok": True}


# -- notifications -----------------------------------------------------------------


@router.get("/notifications")
def notifications(ctx: UserCtx, limit: int = 50) -> dict:
    items = list(ctx.db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(min(limit, 200))))
    unread = ctx.db.scalar(select(func.count()).select_from(Notification).where(Notification.read_at.is_(None))) or 0
    return {"items": rows(items), "unread": unread}


@router.post("/notifications/read-all")
def read_all(ctx: UserCtx) -> dict:
    for n in ctx.db.scalars(select(Notification).where(Notification.read_at.is_(None))):
        n.read_at = now()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: uuid.UUID, ctx: UserCtx) -> dict:
    n = ctx.db.get(Notification, nid)
    if n and n.read_at is None:
        n.read_at = now()
    return {"ok": True}


@router.get("/push/key")
def push_key(ctx: UserCtx) -> dict:
    return {"public_key": get_settings().vapid_public_key}


class PushIn(BaseModel):
    endpoint: str
    keys: dict[str, str]


@router.post("/push/subscribe")
def subscribe(body: PushIn, ctx: UserCtx) -> dict:
    existing = ctx.db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing is None:
        ctx.db.add(PushSubscription(user_id=ctx.uid, endpoint=body.endpoint, p256dh=body.keys.get("p256dh", ""),
                                    auth=body.keys.get("auth", "")))
    prefs = dict(ctx.user.notification_prefs or {})
    prefs["push"] = True
    ctx.user.notification_prefs = prefs
    return {"ok": True}


# -- registry ----------------------------------------------------------------------


@router.get("/registry")
def registry_list(ctx: UserCtx) -> list[dict]:
    return rows(ctx.db.scalars(select(Destination).order_by(Destination.platform, Destination.domain)))


class RegistryPatch(BaseModel):
    support_mode: str | None = None
    policy_review_status: str | None = None
    enabled: bool | None = None
    disabled_reason: str | None = None
    known_limitations: str | None = None
    bot_challenge_seen: bool | None = None


@router.patch("/registry/{dest_id}")
def registry_patch(dest_id: uuid.UUID, body: RegistryPatch, ctx: UserCtx) -> dict:
    if not ctx.user.is_admin:
        raise ApiError(403, "admin_only", "Only an administrator can change the registry.")
    d = ctx.db.get(Destination, dest_id)
    if d is None:
        raise not_found("Destination not found.")
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(d, k, v)
    if "policy_review_status" in data:
        d.policy_review_date = now().date()
    d.updated_at = now()
    ctx.db.flush()
    audit(ctx.db, ctx.uid, "user", "registry.changed", "destination", d.id, **{k: str(v) for k, v in data.items()})
    return row(d)


# -- metrics, dashboard ----------------------------------------------------------------


@router.get("/metrics")
def metrics(ctx: UserCtx) -> dict:
    return outcomes.trust_metrics(ctx.db, ctx.user)


@router.get("/dashboard")
def dashboard(ctx: UserCtx) -> dict[str, Any]:
    db = ctx.db
    counts = dict(db.execute(select(Application.state, func.count()).group_by(Application.state)).all())
    tasks = list(db.scalars(select(UserTask).where(UserTask.status == "open").order_by(UserTask.created_at.desc()).limit(50)))
    app_ids = {t.application_id for t in tasks if t.application_id}
    jobs = {}
    if app_ids:
        for a, j in db.execute(select(Application, Job).join(Job, Job.id == Application.job_id).where(Application.id.in_(app_ids))):
            jobs[a.id] = {"title": j.title, "company_name": j.company_name, "state": a.state}
    active = db.execute(
        select(Application, Job).join(Job, Job.id == Application.job_id)
        .where(Application.state.in_(["fit_review", "grounding", "drafted", "filling", "in_review", "approved", "submitting"]))
        .order_by(Application.state_changed_at.desc())
    ).all()
    devices = list(db.scalars(select(RunnerDevice).where(RunnerDevice.revoked_at.is_(None))))
    runner_online = any(d.last_seen_at and now() - d.last_seen_at < timedelta(seconds=45) for d in devices)
    activity = db.execute(
        select(ApplicationEvent, Job).join(Application, Application.id == ApplicationEvent.application_id)
        .join(Job, Job.id == Application.job_id).order_by(ApplicationEvent.id.desc()).limit(12)
    ).all()
    due = list(db.scalars(select(FollowUp).where(FollowUp.status == "ready")))
    facts_n = len(ledger.current_facts(db))
    companies = db.scalar(select(func.count()).select_from(WatchlistCompany).where(WatchlistCompany.active.is_(True))) or 0
    matched_open = db.scalar(select(func.count()).select_from(Job).where(Job.closed_at.is_(None), Job.target_match.is_(True))) or 0
    review = outcomes.weekly_review(db, ctx.user, weeks=8)
    return {
        "budget": grounding.budget_status(db, ctx.user),
        "counts": counts,
        "tasks": [row(t, job=jobs.get(t.application_id)) for t in tasks],
        "active": [{"id": str(a.id), "state": a.state, "fit_label": a.fit_label, "fit_score": a.fit_score,
                    "title": j.title, "company_name": j.company_name, "state_changed_at": a.state_changed_at.isoformat(),
                    "support_mode": a.support_mode} for a, j in active],
        "runner": {"paired": bool(devices), "online": runner_online, "devices": len(devices)},
        "activity": [{"id": e.id, "application_id": str(e.application_id), "from_state": e.from_state, "to_state": e.to_state,
                      "actor": e.actor, "reason": e.reason, "created_at": e.created_at.isoformat(),
                      "title": j.title, "company_name": j.company_name} for e, j in activity],
        "follow_ups_ready": len(due),
        "facts": facts_n,
        "watchlist": companies,
        "matched_open_jobs": matched_open,
        "outcomes": {"sent": review["sent"], "replies": review["replies"], "interviews": review["interviews"],
                     "ci": review["ci"], "by_week": review["by_week"]},
    }


# -- public: the Trust Report -----------------------------------------------------------


@router.get("/public/trust-report")
def trust_report() -> dict:
    path = ROOT / "evals" / "out" / "report.json"
    fallback = ROOT / "docs" / "trust-report.json"
    for p in (path, fallback):
        if p.exists():
            return json.loads(p.read_text())
    return {"generated_at": None, "sections": [], "note": "Run `uv run lintel-evals` to generate the report."}
