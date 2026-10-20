from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from lintel_schemas import STATE_LABELS, ApplicationState, FitBrief
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db.models import (
    AnswerDraft,
    Application,
    ApplicationEvent,
    ApplicationRun,
    ApprovalRecord,
    Contact,
    Destination,
    Document,
    Evidence,
    FollowUp,
    Job,
    ProfileFact,
    ResumeVariant,
    RunStep,
    SubmitIntent,
    UserTask,
)
from ..deps import UserCtx
from ..errors import bad_request, conflict, not_found
from ..serialize import plain, row, rows
from ..services import drafting, execution, grounding, outcomes, registry, variants
from ..services import facts as ledger
from ..services.core import audit, now, transition

router = APIRouter(prefix="/applications", tags=["applications"])

ORDER = {s: i for i, s in enumerate([
    "in_review", "approved", "grounding", "fit_review", "drafted", "filling", "submitting", "imported",
    "submission_uncertain", "confirmed", "user_reported_submitted", "draft_only", "skipped", "expired", "cancelled",
])}


def _app(ctx: UserCtx, app_id: uuid.UUID) -> Application:
    app = ctx.db.get(Application, app_id)
    if app is None:
        raise not_found("Application not found.")
    return app


def summary(ctx: UserCtx, app: Application, job: Job) -> dict[str, Any]:
    brief = app.fit_brief or {}
    return row(app, exclude={"fit_brief", "form_model", "mapping", "payload"},
               state_label=STATE_LABELS[ApplicationState(app.state)],
               job={"id": job.id, "title": job.title, "company_name": job.company_name, "location": job.location,
                    "workplace": job.workplace, "platform": job.platform, "apply_url": job.apply_url, "closed_at": job.closed_at,
                    "comp": brief.get("compensation")},
               recommendation=brief.get("recommendation"), fit_summary=brief.get("summary"))


@router.get("")
def list_applications(ctx: UserCtx, state: str | None = None) -> list[dict]:
    stmt = select(Application, Job).join(Job, Job.id == Application.job_id)
    if state:
        stmt = stmt.where(Application.state.in_(state.split(",")))
    pairs = ctx.db.execute(stmt).all()
    out = [summary(ctx, a, j) for a, j in pairs]
    out.sort(key=lambda r: (ORDER.get(r["state"], 99), -(r["fit_score"] or 0), r["state_changed_at"]))
    return out


@router.get("/queue")
def queue(ctx: UserCtx) -> dict:
    """Roles waiting for a fit decision, ranked by fit. The surplus waits for next week."""

    pairs = ctx.db.execute(select(Application, Job).join(Job, Job.id == Application.job_id)
                           .where(Application.state.in_(["imported", "fit_review"]))).all()
    items = [summary(ctx, a, j) for a, j in pairs]
    items.sort(key=lambda r: (r["state"] != "fit_review", -(r["fit_score"] or 0)))
    return {"budget": grounding.budget_status(ctx.db, ctx.user), "items": items}


def _fact_map(ctx: UserCtx, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    facts = ctx.db.scalars(select(ProfileFact).where(ProfileFact.id.in_([uuid.UUID(i) for i in ids])))
    return {str(f.id): row(f) for f in facts}


@router.get("/{app_id}")
def detail(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    db = ctx.db
    app = _app(ctx, app_id)
    job = db.get(Job, app.job_id)
    dest = db.get(Destination, app.destination_id) if app.destination_id else None
    drafts = list(db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id).order_by(AnswerDraft.position)))
    tasks = list(db.scalars(select(UserTask).where(UserTask.application_id == app.id).order_by(UserTask.created_at)))
    runs = execution.runs_for(db, app.id)
    steps = list(db.scalars(select(RunStep).where(RunStep.run_id.in_([r.id for r in runs])).order_by(RunStep.run_id, RunStep.seq))) if runs else []
    approvals = list(db.scalars(select(ApprovalRecord).where(ApprovalRecord.application_id == app.id).order_by(ApprovalRecord.approved_at)))
    intents = list(db.scalars(select(SubmitIntent).where(SubmitIntent.application_id == app.id).order_by(SubmitIntent.fence)))
    events = list(db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.id)))
    evidence = list(db.scalars(select(Evidence).where(Evidence.application_id == app.id)))
    variants_ = list(db.scalars(select(ResumeVariant).where(ResumeVariant.application_id == app.id).order_by(ResumeVariant.created_at.desc())))
    follow_ups = list(db.scalars(select(FollowUp).where(FollowUp.application_id == app.id).order_by(FollowUp.created_at)))
    resume = drafting.resume_document(db, app)

    cited: set[str] = set()
    for d in drafts:
        cited |= {str(i) for i in d.fact_ids or []}
        for s in d.sentences or []:
            cited |= set(s.get("fact_ids") or [])
    brief = FitBrief.model_validate(app.fit_brief) if app.fit_brief else None
    if brief:
        for r in brief.requirements:
            cited |= set(r.evidence_fact_ids)
    view = grounding.grounding_view(db, app) if app.state in ("grounding", "drafted") else None
    if view:
        for p in view["plan"]:
            cited |= set(p["fact_ids"])
    last_fill = execution.last_fill(db, app)
    verified = {}
    if last_fill:
        for st in steps:
            if st.run_id == last_fill.id and st.action == "verify" and st.field_key:
                verified[st.field_key] = st.verification
    live_approval = next((a for a in approvals if a.consumed_at is None and a.revoked_at is None), None)
    contacts = outcomes.contacts_at(db, job.company_name)
    return {
        "application": row(app, exclude={"form_model"}, state_label=STATE_LABELS[ApplicationState(app.state)]),
        "job": row(job, exclude={"questions"}),
        "destination": row(dest),
        "max_mode": registry.max_mode(dest).value,
        "drafts": rows(drafts),
        "tasks": rows(tasks),
        "runs": rows(runs),
        "steps": rows(steps),
        "approvals": rows(approvals),
        "live_approval": row(live_approval),
        "intents": rows(intents),
        "events": rows(events),
        "outcomes": rows(outcomes.timeline(db, app.id)),
        "evidence": rows(evidence),
        "variants": rows(variants_),
        "follow_ups": rows(follow_ups),
        "facts": _fact_map(ctx, cited),
        "grounding": view,
        "readiness": drafting.readiness(db, app),
        "resume": row(resume, exclude={"parsed"}),
        "fill": {"run": row(last_fill), "verified": verified,
                 "current": bool(last_fill and last_fill.payload_hash == app.payload_hash)},
        "budget": grounding.budget_status(db, ctx.user),
        "contacts": rows(contacts),
        "form_model": app.form_model,
        "sent": outcomes.is_sent(db, app),
    }


class DecideIn(BaseModel):
    go: bool
    reason: str = Field(default="", max_length=300)
    next_week: bool = False


@router.post("/{app_id}/decide")
def decide(app_id: uuid.UUID, body: DecideIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    grounding.decide(ctx.db, ctx.user, app, go=body.go, reason=body.reason, next_week=body.next_week)
    if body.go and not body.next_week:
        outcomes.referral_nudge(ctx.db, ctx.user, app)
    return {"state": app.state}


@router.post("/{app_id}/refresh-fit")
def refresh_fit(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    from ..services import fit

    app = _app(ctx, app_id)
    if app.state not in ("imported", "fit_review"):
        raise conflict("wrong_state", "The fit brief is fixed once you've decided.")
    fit.generate(ctx.db, ctx.user, app)
    return {"ok": True}


@router.post("/{app_id}/grounding/confirm")
def confirm_grounding(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    grounding.confirm_grounding(ctx.db, ctx.user, app)
    return {"state": app.state, "drafting": True}


class AnswerIn(BaseModel):
    value: Any
    scope: str = "application"


@router.post("/{app_id}/answers/{field_key}")
def answer(app_id: uuid.UUID, field_key: str, body: AnswerIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    if body.scope not in ("application", "all"):
        raise bad_request("bad_scope", "Scope is this application or all applications.")
    d = grounding.answer_field(ctx.db, ctx.user, app, field_key, body.value, scope=body.scope)
    drafting.refresh_payload(ctx.db, app)
    return row(d)


class EditIn(BaseModel):
    text: str = Field(max_length=10000)


@router.put("/{app_id}/drafts/{field_key}")
def edit_draft(app_id: uuid.UUID, field_key: str, body: EditIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(drafting.edit_answer(ctx.db, ctx.user, app, field_key, body.text))


@router.post("/{app_id}/drafts/{field_key}/redraft")
def redraft(app_id: uuid.UUID, field_key: str, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(drafting.redraft(ctx.db, ctx.user, app, field_key))


@router.post("/{app_id}/drafts/{field_key}/accept-partial")
def accept_partial(app_id: uuid.UUID, field_key: str, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(drafting.accept_without_failed(ctx.db, ctx.user, app, field_key))


class CheckIn(BaseModel):
    text: str = Field(max_length=2000)
    fact_ids: list[str] = Field(default_factory=list)


@router.post("/{app_id}/check")
def check_text(app_id: uuid.UUID, body: CheckIn, ctx: UserCtx) -> list[dict]:
    """Preview the claim check on text the user is typing, sentence by sentence."""

    from lintel_trust.claimcheck import split_sentences

    from ..llm.heuristics import relevance

    app = _app(ctx, app_id)
    job = ctx.db.get(Job, app.job_id)
    facts = ledger.current_facts(ctx.db, app.id)
    out = []
    for s in split_sentences(body.text)[:12]:
        ids = body.fact_ids or [str(f.id) for f in sorted(
            [f for f in facts if f.kind in ledger.MODEL_VISIBLE_KINDS],
            key=lambda f: relevance(s, f.statement), reverse=True)[:3] if relevance(s, f.statement) > 0.15]
        res = drafting.check(ctx.db, ctx.user, job, s, ids, facts)
        out.append({"text": s, "fact_ids": ids, "check": res.model_dump(mode="json")})
    return out


class ConsentIn(BaseModel):
    value: bool


@router.post("/{app_id}/consents/{field_key}")
def consent(app_id: uuid.UUID, field_key: str, body: ConsentIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(drafting.set_consent(ctx.db, app, field_key, body.value))


@router.post("/{app_id}/variants/{variant_id}/approve")
def approve_variant(app_id: uuid.UUID, variant_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(variants.approve_variant(ctx.db, ctx.user, app, variant_id))


@router.post("/{app_id}/variants/{variant_id}/reject")
def reject_variant(app_id: uuid.UUID, variant_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(variants.reject_variant(ctx.db, ctx.user, app, variant_id))


@router.post("/{app_id}/variants/propose")
def propose_variant(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    v = variants.propose_variant(ctx.db, ctx.user, app)
    if v is None:
        raise conflict("no_variant", "Nothing to tailor: upload a résumé with bullet points under Experience or Projects.")
    return row(v)


@router.post("/{app_id}/fill")
def fill(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    run = execution.start_fill(ctx.db, ctx.user, app)
    return {"run": row(run), "state": app.state}


class ApproveIn(BaseModel):
    payload_hash: str
    mode: str | None = None


@router.post("/{app_id}/approve")
def approve(app_id: uuid.UUID, body: ApproveIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    rec = execution.approve(ctx.db, ctx.user, app, payload_hash=body.payload_hash, mode=body.mode)
    return {"approval": row(rec, exclude={"payload"}), "state": app.state}


@router.post("/{app_id}/arm")
def arm(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return {"run": row(execution.rearm(ctx.db, ctx.user, app))}


@router.post("/{app_id}/revoke")
def revoke(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    execution.revoke_approval(ctx.db, ctx.user, app)
    return {"state": app.state}


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/{app_id}/report-sent")
def report_sent(app_id: uuid.UUID, body: NoteIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    execution.report_user_submitted(ctx.db, ctx.user, app, body.note)
    return {"state": app.state}


@router.post("/{app_id}/close-packet")
def close_packet(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    if app.state != ApplicationState.drafted.value:
        raise conflict("wrong_state", "Only a drafted packet can be closed.")
    transition(ctx.db, app, ApplicationState.draft_only, actor="user", reason="you closed the packet without sending")
    return {"state": app.state}


@router.post("/{app_id}/cancel")
def cancel(app_id: uuid.UUID, body: NoteIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    execution.cancel_application(ctx.db, ctx.user, app, body.note)
    return {"state": app.state}


class OutcomeIn(BaseModel):
    stage: str
    note: str = Field(default="", max_length=500)
    occurred_at: datetime | None = None


@router.post("/{app_id}/outcomes")
def add_outcome(app_id: uuid.UUID, body: OutcomeIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    return row(outcomes.record_stage(ctx.db, ctx.user, app, body.stage, note=body.note, occurred_at=body.occurred_at))


class EvidenceIn(BaseModel):
    text: str = Field(default="", max_length=4000)
    reference_number: str | None = Field(default=None, max_length=120)


@router.post("/{app_id}/evidence")
def add_evidence(app_id: uuid.UUID, body: EvidenceIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    ev = Evidence(user_id=ctx.uid, application_id=app.id, kind="confirmation_text", text=body.text,
                  reference_number=body.reference_number)
    ctx.db.add(ev)
    for t in ctx.db.scalars(select(UserTask).where(UserTask.application_id == app.id, UserTask.type == "confirm_submission",
                                                   UserTask.status == "open")):
        t.status, t.resolved_at = "done", now()
    ctx.db.flush()
    return row(ev)


class FlagIn(BaseModel):
    field_key: str
    sentence: str
    note: str = ""


@router.post("/{app_id}/flag-claim")
def flag_claim(app_id: uuid.UUID, body: FlagIn, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    audit(ctx.db, ctx.uid, "user", "claim.flagged", "application", app.id, field_key=body.field_key,
          sentence=body.sentence[:300], note=body.note[:300])
    return {"ok": True}


@router.get("/{app_id}/packet")
def packet(app_id: uuid.UUID, ctx: UserCtx) -> dict:
    """A copyable packet: every answer in form order, with its sources."""

    app = _app(ctx, app_id)
    job = ctx.db.get(Job, app.job_id)
    drafts = list(ctx.db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id).order_by(AnswerDraft.position)))
    resume = drafting.resume_document(ctx.db, app)
    items = []
    for d in drafts:
        if d.status == "skipped":
            continue
        value = d.value
        if d.options and value is not None:
            labels = {o["value"]: o["label"] for o in d.options}
            value = [labels.get(v, v) for v in value] if isinstance(value, list) else labels.get(value, value)
        items.append({"field_key": d.field_key, "label": d.label, "value": plain(value), "status": d.status,
                      "category": d.category, "fact_ids": plain(d.fact_ids)})
    return {"job": row(job, exclude={"questions", "description"}), "items": items,
            "resume": row(resume, exclude={"parsed"}), "payload_hash": app.payload_hash}


@router.post("/{app_id}/referral/{contact_id}")
def referral(app_id: uuid.UUID, contact_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    contact = ctx.db.get(Contact, contact_id)
    if contact is None:
        raise not_found("Contact not found.")
    return outcomes.draft_referral(ctx.db, ctx.user, app, contact)


@router.get("/{app_id}/document/{doc_id}")
def app_document(app_id: uuid.UUID, doc_id: uuid.UUID, ctx: UserCtx) -> dict:
    _app(ctx, app_id)
    doc = ctx.db.get(Document, doc_id)
    if doc is None:
        raise not_found("Document not found.")
    return row(doc, exclude={"parsed"})


@router.get("/{app_id}/runs/{run_id}")
def run_detail(app_id: uuid.UUID, run_id: uuid.UUID, ctx: UserCtx) -> dict:
    run = ctx.db.get(ApplicationRun, run_id)
    if run is None or run.application_id != app_id:
        raise not_found("Run not found.")
    steps = ctx.db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq))
    return {"run": row(run), "steps": rows(steps)}


@router.post("/{app_id}/runs/{run_id}/cancel")
def cancel_run(app_id: uuid.UUID, run_id: uuid.UUID, ctx: UserCtx) -> dict:
    app = _app(ctx, app_id)
    run = ctx.db.get(ApplicationRun, run_id)
    if run is None or run.application_id != app.id:
        raise not_found("Run not found.")
    if run.state in ("queued", "running", "waiting_user"):
        run.state = "cancelled"
        run.ended_reason = "cancelled by you"
        if run.kind == "fill" and app.state == "filling":
            transition(ctx.db, app, ApplicationState.drafted, actor="user", reason="you stopped the fill")
    return row(run)
