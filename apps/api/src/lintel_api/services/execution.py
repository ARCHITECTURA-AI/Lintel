"""Runs, approvals, the write-ahead submit intent and recovery.

Exactly-once cannot be guaranteed on a third-party site. Lintel guarantees something narrower
and testable: it never sends twice on its own authority.

  1. compare-and-set the application from approved (awaiting the click) to submitting, which
     returns a fencing token
  2. write a submit_intent row carrying the token and the payload hash, before the click
  3. let the click through
  4. observe the outcome through the adapter
  5. write the outcome keyed by application id and token, so a repeat write is a no-op

A crash after step 2 leaves submitting with no outcome. Recovery marks it submission_uncertain
and never retries. A stale runner holding an old token cannot write an outcome.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from lintel_schemas import (
    TERMINAL_STATES,
    ApplicationState,
    CanonicalPayload,
    FormModel,
    RunAssignment,
    RunKind,
    RunStepRecord,
    SupportMode,
)
from lintel_trust import sign_approval, sign_fill_grant
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import (
    AnswerDraft,
    Application,
    ApplicationRun,
    ApprovalRecord,
    Destination,
    Document,
    Evidence,
    Job,
    OutcomeEvent,
    RunnerDevice,
    RunStep,
    User,
    UserTask,
)
from ..errors import conflict, not_found
from ..security import signing_key
from . import registry
from .core import audit, close_task, close_tasks_for, notify, now, open_task, require_state, transition
from .drafting import readiness, refresh_payload

WAITING_COPY = {
    "captcha": ("A CAPTCHA needs you", "Complete it in the Lintel browser window, then press Resume. Lintel never solves or evades one."),
    "mfa": ("Sign-in verification needs you", "Finish the verification in the Lintel browser window, then press Resume."),
    "login": ("Sign in to continue", "The site asked you to sign in. Do it in the Lintel browser window, then press Resume."),
    "modal": ("An unexpected dialog appeared", "Close it in the Lintel browser window, then press Resume."),
    "missing_fact": ("The form asks something new", "The live form has questions Lintel hasn't seen. Answer them in Lintel."),
    "session_expired": ("The page session expired", "Reload the page in the Lintel browser window, then press Resume."),
    "paused": ("Automation paused", "Lintel pauses after 15 minutes of active automation. Press Resume to continue."),
    "no_progress": ("Lintel stopped making progress", "The page didn't respond as expected. Check the window, then press Resume."),
    "validation": ("The site rejected a value", "Fix the highlighted field in the Lintel browser window, then press Resume."),
}


# ---------------------------------------------------------------------------
# Starting runs (web side)
# ---------------------------------------------------------------------------


def _device(db: Session, device_id: uuid.UUID | None = None) -> RunnerDevice:
    q = select(RunnerDevice).where(RunnerDevice.revoked_at.is_(None))
    if device_id:
        q = q.where(RunnerDevice.id == device_id)
    dev = db.scalar(q.order_by(RunnerDevice.last_seen_at.desc().nullslast()))
    if dev is None:
        raise conflict("no_runner", "Pair the Local Runner first. It opens the form in a browser on your own machine.")
    return dev


def start_fill(db: Session, user: User, app: Application) -> ApplicationRun:
    require_state(app, ApplicationState.drafted, ApplicationState.in_review)
    if app.support_mode == SupportMode.draft_only.value:
        raise conflict("draft_only", "This site is draft-only. Copy the packet and apply on the site yourself.")
    refresh_payload(db, app)
    ready = readiness(db, app)
    if not ready["ready"]:
        raise conflict("not_ready", "Some answers still need you before Lintel can fill the form.", ready)
    _device(db)
    from .grounding import queue_run

    run = queue_run(db, user, app, RunKind.fill.value, payload_hash=app.payload_hash)
    transition(db, app, ApplicationState.filling, actor="user", reason="you asked Lintel to fill the form in your browser")
    return run


def cancel_application(db: Session, user: User, app: Application, reason: str = "") -> None:
    if app.state == ApplicationState.submitting.value:
        raise conflict("submitting", "The click already happened. Lintel is waiting to see the outcome.")
    app.cancel_requested_at = now()
    for run in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app.id,
                                                       ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
        run.state = "cancelled"
        run.ended_reason = "application cancelled"
    _revoke_live(db, app, "application cancelled")
    transition(db, app, ApplicationState.cancelled, actor="user", reason=reason or "you cancelled this application")
    close_tasks_for(db, app.id)


# ---------------------------------------------------------------------------
# Approval (gate 3)
# ---------------------------------------------------------------------------


def _revoke_live(db: Session, app: Application, reason: str) -> ApprovalRecord | None:
    live = db.scalar(
        select(ApprovalRecord).where(ApprovalRecord.application_id == app.id, ApprovalRecord.consumed_at.is_(None),
                                     ApprovalRecord.revoked_at.is_(None))
    )
    if live:
        live.revoked_at = now()
        live.revoked_reason = reason
        db.flush()
    return live


def last_fill(db: Session, app: Application) -> ApplicationRun | None:
    return db.scalar(
        select(ApplicationRun).where(ApplicationRun.application_id == app.id, ApplicationRun.kind == "fill",
                                     ApplicationRun.state == "completed").order_by(ApplicationRun.ended_at.desc())
    )


def approve(db: Session, user: User, app: Application, *, payload_hash: str, mode: str | None = None) -> ApprovalRecord:
    require_state(app, ApplicationState.in_review)
    refresh_payload(db, app)
    if payload_hash != app.payload_hash:
        raise conflict("payload_changed", "The payload changed while you were reviewing. Review the new version.",
                       {"payload_hash": app.payload_hash})
    ready = readiness(db, app)
    if not ready["ready"]:
        raise conflict("not_ready", "Some answers still need you.", ready)
    fill = last_fill(db, app)
    if fill is None or fill.payload_hash != app.payload_hash:
        raise conflict("refill_needed", "The form in your browser doesn't hold this exact payload yet. Fill it again first.")
    device = _device(db, fill.runner_device_id)
    dest = db.get(Destination, app.destination_id) if app.destination_id else None
    if mode:
        capped = registry.cap_mode(mode, dest)
        if capped.value != mode:
            raise conflict("mode_not_allowed", f"{dest.domain if dest else 'This site'} doesn't allow that mode.")
        app.support_mode = capped.value
    _revoke_live(db, app, "replaced by a new approval")
    s = get_settings()
    approval_id = uuid.uuid4()
    expires = now() + timedelta(minutes=s.approval_ttl_minutes)
    signed = sign_approval(
        signing_key(), approval_id=str(approval_id), application_id=str(app.id), payload_hash=app.payload_hash,
        runner_device_id=str(device.id), expires_at=expires,
    )
    rec = ApprovalRecord(
        id=approval_id, user_id=user.id, application_id=app.id, payload_hash=app.payload_hash, payload=app.payload,
        runner_device_id=device.id, approved_at=now(), expires_at=expires, signature=signed.signature, key_id=signed.key_id,
    )
    db.add(rec)
    app_approved_at = now()
    transition(db, app, ApplicationState.approved, actor="user", reason="you approved the exact payload")
    from .grounding import queue_run

    run = queue_run(db, user, app, RunKind.submit.value, payload_hash=app.payload_hash)
    run.runner_device_id = device.id
    audit(db, user.id, "user", "approval.created", "application", app.id, approval_id=str(approval_id),
          payload_hash=app.payload_hash, expires_at=expires.isoformat(), mode=app.support_mode,
          minutes_since_decision=round((app_approved_at - app.decided_at).total_seconds() / 60, 2) if app.decided_at else None)
    return rec


def revoke_approval(db: Session, user: User, app: Application, reason: str = "you revoked the approval") -> None:
    require_state(app, ApplicationState.approved)
    _revoke_live(db, app, reason)
    for run in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app.id, ApplicationRun.kind == "submit",
                                                       ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
        run.state = "cancelled"
        run.ended_reason = reason
    transition(db, app, ApplicationState.in_review, actor="user", reason=reason)


def report_user_submitted(db: Session, user: User, app: Application, note: str = "") -> None:
    """The Guard is a seatbelt, not a lock. Sending outside it is recorded honestly."""

    if app.state not in (ApplicationState.drafted.value, ApplicationState.filling.value, ApplicationState.in_review.value,
                         ApplicationState.approved.value):
        raise conflict("wrong_state", "This application can't be marked as sent from its current state.")
    _revoke_live(db, app, "sent outside the Guard")
    for run in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app.id,
                                                       ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
        run.state = "cancelled"
        run.ended_reason = "you sent it yourself"
    transition(db, app, ApplicationState.user_reported_submitted, actor="user", reason="you reported sending it yourself")
    db.add(OutcomeEvent(user_id=user.id, application_id=app.id, stage="user_reported_submitted", source="user", note=note))
    close_tasks_for(db, app.id, ["unknown_answer", "fact_interview", "claim_review", "waiting_user", "guard_mismatch"])
    open_task(db, user.id, "confirm_submission", title="Add the confirmation", application_id=app.id,
              body="Paste the confirmation message or reference number so your outcome record has evidence.",
              dedupe_key=f"confirm:{app.id}")


# ---------------------------------------------------------------------------
# Runner side
# ---------------------------------------------------------------------------


def claim_next(db: Session, user: User, device: RunnerDevice) -> RunAssignment | None:
    s = get_settings()
    if db.scalar(select(func.count()).select_from(ApplicationRun).where(ApplicationRun.state == "running")):
        return None  # one active run per user
    run = db.execute(
        select(ApplicationRun)
        .where(ApplicationRun.state == "queued",
               (ApplicationRun.runner_device_id.is_(None)) | (ApplicationRun.runner_device_id == device.id))
        .order_by(ApplicationRun.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if run is None:
        return None
    app = db.get(Application, run.application_id)
    if app.cancel_requested_at:
        run.state = "cancelled"
        run.ended_reason = "application cancelled"
        return None
    run.state = "running"
    run.runner_device_id = device.id
    run.started_at = now()
    run.heartbeat_at = now()
    run.lease_expires_at = now() + timedelta(seconds=s.run_lease_seconds)
    db.flush()
    return build_assignment(db, user, app, run, device)


def build_assignment(db: Session, user: User, app: Application, run: ApplicationRun, device: RunnerDevice) -> RunAssignment:
    s = get_settings()
    job = db.get(Job, app.job_id)
    dest = db.get(Destination, app.destination_id) if app.destination_id else None
    host = urlparse(job.apply_url).netloc.lower()
    allowed = sorted({host, *(dest.asset_hosts if dest else [])})
    drafts = list(db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id)))
    assignment = RunAssignment(
        run_id=str(run.id),
        kind=RunKind(run.kind),
        application_id=str(app.id),
        apply_url=job.apply_url,
        support_mode=SupportMode(app.support_mode),
        allowed_hosts=allowed,
        permitted_paths=list(dest.permitted_paths) if dest else ["/"],
        field_labels={d.field_key: d.label for d in drafts},
        handles={d.field_key: (d.handle or d.category) for d in drafts},
        limits={"max_actions": s.run_max_actions, "max_recoveries": s.run_max_recoveries_per_step,
                "max_active_minutes": s.run_max_active_minutes, "lease_seconds": s.run_lease_seconds},
    )
    if run.kind in ("fill", "submit") and app.payload:
        payload = CanonicalPayload.model_validate(app.payload)
        assignment.payload = payload
        assignment.payload_hash = app.payload_hash
        docs = []
        for d in payload.documents:
            doc = db.scalar(select(Document).where(Document.sha256 == d.sha256, Document.deleted_at.is_(None)))
            if doc:
                docs.append({"role": d.role, "sha256": d.sha256, "filename": doc.filename, "field_key": d.field_key,
                             "url": f"/runner/documents/{d.sha256}"})
        assignment.documents = docs
    if run.kind == "fill":
        assignment.fill_grant = sign_fill_grant(
            signing_key(), run_id=str(run.id), application_id=str(app.id), payload_hash=app.payload_hash,
            runner_device_id=str(device.id), expires_at=now() + timedelta(minutes=s.fill_grant_ttl_minutes),
        )
    if run.kind == "submit":
        rec = db.scalar(select(ApprovalRecord).where(ApprovalRecord.application_id == app.id, ApprovalRecord.consumed_at.is_(None),
                                                     ApprovalRecord.revoked_at.is_(None)))
        if rec is None or rec.runner_device_id != device.id:
            run.state = "cancelled"
            run.ended_reason = "no live approval for this device"
            raise conflict("no_approval", "There's no live approval for this device.")
        from lintel_schemas import SignedApproval

        assignment.approval = SignedApproval(
            approval_id=str(rec.id), application_id=str(app.id), payload_hash=rec.payload_hash,
            runner_device_id=str(rec.runner_device_id), expires_at=rec.expires_at, signature=rec.signature, key_id=rec.key_id,
        )
    return assignment


def _own_run(db: Session, device: RunnerDevice, run_id: uuid.UUID) -> ApplicationRun:
    run = db.get(ApplicationRun, run_id)
    if run is None:
        raise not_found("Run not found.")
    if run.runner_device_id != device.id:
        raise conflict("not_your_run", "This run belongs to another device.")
    return run


def heartbeat(db: Session, device: RunnerDevice, run_id: uuid.UUID) -> dict[str, Any]:
    run = _own_run(db, device, run_id)
    app = db.get(Application, run.application_id)
    cancel = run.state not in ("running", "waiting_user") or app.cancel_requested_at is not None
    if run.kind == "submit" and app.state not in ("approved", "submitting"):
        cancel = True
    if not cancel:
        run.heartbeat_at = now()
        run.lease_expires_at = now() + timedelta(seconds=get_settings().run_lease_seconds)
    return {"cancel": cancel, "state": run.state, "application_state": app.state}


def record_steps(db: Session, device: RunnerDevice, run_id: uuid.UUID, steps: list[RunStepRecord]) -> int:
    run = _own_run(db, device, run_id)
    if run.state not in ("running", "waiting_user"):
        raise conflict("run_closed", "This run has ended.")
    existing = set(db.scalars(select(RunStep.seq).where(RunStep.run_id == run.id)))
    added = 0
    for st in steps:
        if st.seq in existing:
            continue  # idempotent: a retried upload never duplicates a step
        db.add(RunStep(user_id=run.user_id, run_id=run.id, seq=st.seq, action=st.action, field_key=st.field_key,
                       value_hash=st.value_hash, value_len=st.value_len, verification=st.verification, detail=st.detail[:500]))
        if st.action in ("fill", "select", "check", "upload", "click", "navigate"):
            added += 1
    limit = get_settings().run_max_actions
    if run.action_count + added > limit:
        run.action_count = limit
        db.flush()
        raise conflict("budget_exhausted", f"This run reached its limit of {limit} tool actions.")
    run.action_count += added
    return added


def report_form(db: Session, user: User, device: RunnerDevice, run_id: uuid.UUID, fm: FormModel) -> dict[str, Any]:
    """The live page is the truth. Reconcile it with what the cloud expected."""

    from .grounding import apply_form_model

    run = _own_run(db, device, run_id)
    app = db.get(Application, run.application_id)
    if fm.bot_challenge:
        mode = db.scalar(text("SELECT report_bot_challenge(:h)"), {"h": fm.host})
        audit(db, user.id, "runner", "registry.bot_challenge", "destination", fm.host, new_mode=mode)
    old_keys = {f["field_key"] for f in (app.form_model or {}).get("fields", [])}
    app.form_model = fm.model_dump(mode="json")
    app.form_source = "runner"
    changes = apply_form_model(db, user, app, fm)
    new_needs = list(db.scalars(select(AnswerDraft).where(
        AnswerDraft.application_id == app.id, AnswerDraft.field_key.in_(changes["added"]),
        AnswerDraft.status.in_(["needs_user", "pending"]), AnswerDraft.required.is_(True))))
    if changes["added"] or changes["removed"]:
        audit(db, user.id, "runner", "form.reconciled", "application", app.id, added=len(changes["added"]),
              removed=len(changes["removed"]), page_version=fm.page_version, had=len(old_keys))
    if app.state in (ApplicationState.drafted.value, ApplicationState.grounding.value, ApplicationState.in_review.value,
                     ApplicationState.filling.value):
        # drafting new free-text questions happens in the normal drafting step
        pending = [d for d in new_needs if d.decision == "draft_needed"]
        if pending and app.state != ApplicationState.grounding.value:
            from .drafting import draft_one

            for d in pending:
                draft_one(db, user, app, d)
        refresh_payload(db, app)
    return {"added": changes["added"], "removed": changes["removed"],
            "blocking": [d.field_key for d in new_needs if d.status != "ready"]}


def set_waiting(db: Session, user: User, device: RunnerDevice, run_id: uuid.UUID, reason: str, detail: str = "") -> None:
    run = _own_run(db, device, run_id)
    if run.state != "running":
        raise conflict("run_closed", "This run isn't running.")
    run.state = "waiting_user"
    run.waiting_reason = reason
    title, body = WAITING_COPY.get(reason, ("Lintel needs you", detail or "Check the Lintel browser window."))
    app = db.get(Application, run.application_id)
    job = db.get(Job, app.job_id)
    open_task(db, user.id, "waiting_user", title=title, body=f"{job.title} at {job.company_name}. {body}",
              application_id=app.id, data={"run_id": str(run.id), "reason": reason, "detail": detail},
              dedupe_key=f"waiting:{run.id}")
    # An immediate message only when a run is blocked.
    notify(db, user.id, "run.blocked", title, f"{job.title} at {job.company_name}. {body}", link=f"/applications/{app.id}",
           urgent=True, dedupe_key=f"blocked:{run.id}")


def resume_run(db: Session, user: User, run_id: uuid.UUID, device: RunnerDevice | None = None) -> ApplicationRun:
    """Resuming creates a new run that starts from a fresh read of the page."""

    old = db.get(ApplicationRun, run_id)
    if old is None:
        raise not_found("Run not found.")
    if device is not None and old.runner_device_id != device.id:
        raise conflict("not_your_run", "This run belongs to another device.")
    if old.state != "waiting_user":
        raise conflict("not_waiting", "That run isn't waiting for you.")
    old.state = "cancelled"
    old.ended_reason = "resumed as a new run"
    db.flush()
    app = db.get(Application, old.application_id)
    if app.state in (ApplicationState.submitting.value,) or ApplicationState(app.state) in TERMINAL_STATES:
        raise conflict("wrong_state", "This application can't resume.")
    s = get_settings()
    new = ApplicationRun(user_id=user.id, application_id=app.id, kind=old.kind, payload_hash=app.payload_hash,
                         resumed_from_run_id=old.id, runner_device_id=old.runner_device_id)
    if device is not None:
        new.state = "running"
        new.started_at = now()
        new.heartbeat_at = now()
        new.lease_expires_at = now() + timedelta(seconds=s.run_lease_seconds)
    db.add(new)
    db.flush()
    task = db.scalar(select(UserTask).where(UserTask.dedupe_key == f"waiting:{old.id}", UserTask.status == "open"))
    if task:
        close_task(task, "done", {"resumed_as": str(new.id)})
    return new


def complete_run(db: Session, user: User, device: RunnerDevice, run_id: uuid.UUID, result: dict[str, Any]) -> None:
    run = _own_run(db, device, run_id)
    if run.state not in ("running", "waiting_user"):
        return  # idempotent
    app = db.get(Application, run.application_id)
    run.state = "completed"
    run.ended_reason = result.get("summary") or "completed"
    if run.kind == "fill":
        if run.payload_hash != app.payload_hash:
            run.ended_reason = "filled an older payload"
        if app.state == ApplicationState.filling.value:
            transition(db, app, ApplicationState.in_review, actor="runner",
                       reason="form filled in your browser and every value read back")
    elif run.kind == "read_form" or run.kind == "submit":
        pass


def fail_run(db: Session, user: User, device: RunnerDevice, run_id: uuid.UUID, reason: str) -> None:
    run = _own_run(db, device, run_id)
    if run.state not in ("running", "waiting_user", "queued"):
        return
    run.state = "failed"
    run.ended_reason = reason[:300]
    app = db.get(Application, run.application_id)
    if run.kind == "fill" and app.state == ApplicationState.filling.value:
        transition(db, app, ApplicationState.drafted, actor="runner", reason=f"fill stopped: {reason[:120]}")
        notify(db, user.id, "run.failed", "Fill stopped", reason[:200], link=f"/applications/{app.id}")
    if app.state == ApplicationState.submitting.value:
        db.scalar(text("SELECT mark_submission_uncertain(:a, :r)"), {"a": app.id, "r": f"runner failed after the click: {reason[:120]}"})
        _uncertain_notice(db, user, app)


# -- the guard's server-side checks, the intent and the outcome -------------


def guard_check(db: Session, device: RunnerDevice, app_id: uuid.UUID, approval_id: uuid.UUID, payload_hash: str) -> dict[str, Any]:
    app = db.get(Application, app_id)
    if app is None:
        raise not_found("Application not found.")
    reasons = []
    rec = db.get(ApprovalRecord, approval_id)
    if rec is None or rec.application_id != app.id:
        reasons.append("No approval matches this click.")
    else:
        if rec.consumed_at:
            reasons.append("This approval was already used.")
        if rec.revoked_at:
            reasons.append(f"This approval was revoked ({rec.revoked_reason}).")
        if rec.expires_at <= now():
            reasons.append("This approval has expired.")
        if rec.runner_device_id != device.id:
            reasons.append("This approval is for another device.")
        if rec.payload_hash != payload_hash:
            reasons.append("The approval covers a different payload.")
    if app.payload_hash != payload_hash:
        reasons.append("The payload changed after approval.")
    if app.state != ApplicationState.approved.value:
        reasons.append(f"The application is {app.state.replace('_', ' ')}, not awaiting your click.")
    if app.cancel_requested_at:
        reasons.append("The application was cancelled.")
    job = db.get(Job, app.job_id)
    if job.closed_at:
        reasons.append("The posting has closed.")
    return {"ok": not reasons, "reasons": reasons}


def begin_submit(db: Session, user: User, device: RunnerDevice, app_id: uuid.UUID, approval_id: uuid.UUID,
                 payload_hash: str, mode: str) -> int:
    fence = db.scalar(
        text("SELECT begin_submit(:a, :ap, :h, :d, :m)"),
        {"a": app_id, "ap": approval_id, "h": payload_hash, "d": device.id, "m": mode},
    )
    audit(db, user.id, "runner", "submit.intent", "application", app_id, fence=fence, payload_hash=payload_hash, mode=mode)
    return int(fence)


def record_outcome(db: Session, user: User, device: RunnerDevice, app_id: uuid.UUID, fence: int,
                   confirmation_text: str, reference_number: str | None, page_hash: str | None) -> str:
    app = db.get(Application, app_id)
    if app is None:
        raise not_found("Application not found.")
    existing = db.scalar(select(OutcomeEvent).where(OutcomeEvent.application_id == app_id, OutcomeEvent.fence == fence))
    if existing:
        return "duplicate"
    ev = Evidence(user_id=user.id, application_id=app_id, kind="confirmation_text", text=(confirmation_text or "")[:2000],
                  reference_number=reference_number, page_hash=page_hash)
    db.add(ev)
    db.flush()
    result = db.scalar(text("SELECT record_submit_outcome(:a, :f, :e, :n)"),
                       {"a": app_id, "f": fence, "e": ev.id, "n": "confirmation page observed"})
    if result == "recorded":
        job = db.get(Job, app.job_id)
        db.refresh(app)
        close_tasks_for(db, app.id, ["waiting_user", "guard_mismatch"], status="done")
        notify(db, user.id, "application.confirmed", "Application sent",
               f"{job.title} at {job.company_name}" + (f" · reference {reference_number}" if reference_number else ""),
               link=f"/applications/{app.id}")
        from .outcomes import schedule_follow_up

        schedule_follow_up(db, user, app)
    return result


def guard_mismatch(db: Session, user: User, device: RunnerDevice, app_id: uuid.UUID, diffs: list[dict[str, Any]],
                   live_values: dict[str, Any] | None = None) -> None:
    app = db.get(Application, app_id)
    if app is None:
        raise not_found("Application not found.")
    job = db.get(Job, app.job_id)
    audit(db, user.id, "runner", "guard.blocked", "application", app_id, fields=[d.get("field_key") for d in diffs])
    if app.state == ApplicationState.approved.value:
        _revoke_live(db, app, "the Submit Guard found differences at the click")
        for run in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app.id, ApplicationRun.kind == "submit",
                                                           ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
            run.state = "completed"
            run.ended_reason = "guard blocked the click"
        transition(db, app, ApplicationState.in_review, actor="runner",
                   reason="the Submit Guard blocked the click: the form differs from the approval")
    open_task(db, user.id, "guard_mismatch", title="The Guard blocked a click",
              body=f"{job.title} at {job.company_name}: {len(diffs)} field(s) in the browser differ from what you approved.",
              application_id=app.id, data={"diffs": diffs, "has_live_values": bool(live_values)},
              dedupe_key=f"guard:{app.id}")
    if live_values:
        _adopt_live_values(db, user, app, live_values)
    notify(db, user.id, "guard.blocked", "The Guard blocked a click",
           f"{len(diffs)} field(s) differ from your approval for {job.title}.", link=f"/applications/{app.id}", urgent=True,
           dedupe_key=f"guard:{app.id}:{int(now().timestamp()) // 30}")


def _adopt_live_values(db: Session, user: User, app: Application, live_values: dict[str, Any]) -> None:
    """The user chose 'update the payload'. Free text goes back through the claim check."""

    from .drafting import edit_answer
    from .grounding import answer_field

    for key, value in live_values.items():
        d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == key))
        if d is None:
            continue
        if d.decision == "draft_needed":
            edit_answer(db, user, app, key, str(value))
        elif d.category == "consent":
            from .drafting import set_consent

            set_consent(db, app, key, bool(value))
        else:
            answer_field(db, user, app, key, value, scope="application")
    refresh_payload(db, app)


# ---------------------------------------------------------------------------
# Recovery and expiry (run by the scheduler under each user's context)
# ---------------------------------------------------------------------------


def _uncertain_notice(db: Session, user: User, app: Application) -> None:
    job = db.get(Job, app.job_id)
    notify(db, user.id, "submission.uncertain", "Submission uncertain",
           f"Lintel can't confirm whether {job.title} at {job.company_name} was sent. It will not retry. "
           "Check your email or the site, then record what happened.", link=f"/applications/{app.id}", urgent=True,
           dedupe_key=f"uncertain:{app.id}")
    open_task(db, user.id, "confirm_submission", title="Did this application go through?", application_id=app.id,
              body="The click happened but no confirmation was observed. Lintel never resends. Record the outcome if you find one.",
              dedupe_key=f"confirm:{app.id}")


def sweep(db: Session, user: User) -> dict[str, int]:
    s = get_settings()
    counts = {"leases": 0, "uncertain": 0, "expired_approvals": 0, "paused": 0}
    # 1. runs whose runner went quiet
    for run in db.scalars(select(ApplicationRun).where(ApplicationRun.state == "running", ApplicationRun.lease_expires_at < now())):
        run.state = "failed"
        run.ended_reason = "the runner stopped sending heartbeats"
        counts["leases"] += 1
        app = db.get(Application, run.application_id)
        if run.kind == "fill" and app.state == ApplicationState.filling.value:
            transition(db, app, ApplicationState.drafted, actor="worker", reason="the runner went quiet during the fill")
    # 2. intents with no outcome
    cutoff = now() - timedelta(seconds=s.submit_uncertain_after_seconds)
    for app in db.scalars(select(Application).where(Application.state == "submitting", Application.submitted_at < cutoff)):
        live_run = db.scalar(select(ApplicationRun).where(ApplicationRun.application_id == app.id, ApplicationRun.state == "running",
                                                          ApplicationRun.lease_expires_at > now()))
        if live_run is None:
            db.scalar(text("SELECT mark_submission_uncertain(:a, :r)"),
                      {"a": app.id, "r": "no outcome was observed after the submit intent"})
            db.refresh(app)
            _uncertain_notice(db, user, app)
            counts["uncertain"] += 1
    # 3. approvals that ran out
    for rec in db.scalars(select(ApprovalRecord).where(ApprovalRecord.consumed_at.is_(None), ApprovalRecord.revoked_at.is_(None),
                                                       ApprovalRecord.expires_at < now())):
        rec.revoked_at = now()
        rec.revoked_reason = "expired"
        app = db.get(Application, rec.application_id)
        if app.state == ApplicationState.approved.value:
            for run in db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app.id, ApplicationRun.kind == "submit",
                                                               ApplicationRun.state.in_(["queued", "running", "waiting_user"]))):
                run.state = "cancelled"
                run.ended_reason = "approval expired"
            transition(db, app, ApplicationState.in_review, actor="worker", reason="the approval expired after 30 minutes")
            notify(db, user.id, "approval.expired", "Approval expired", "Approve again when you're ready to click.",
                   link=f"/applications/{app.id}")
        counts["expired_approvals"] += 1
    # 4. 15 minutes of active automation
    limit = now() - timedelta(minutes=s.run_max_active_minutes)
    for run in db.scalars(select(ApplicationRun).where(ApplicationRun.state == "running", ApplicationRun.kind == "fill",
                                                       ApplicationRun.started_at < limit)):
        run.state = "waiting_user"
        run.waiting_reason = "paused"
        counts["paused"] += 1
    return counts


def runs_for(db: Session, app_id: uuid.UUID) -> list[ApplicationRun]:
    return list(db.scalars(select(ApplicationRun).where(ApplicationRun.application_id == app_id).order_by(ApplicationRun.created_at)))


def document_for_runner(db: Session, sha256: str) -> Document:
    doc = db.scalar(select(Document).where(Document.sha256 == sha256, Document.deleted_at.is_(None)))
    if doc is None:
        raise not_found("Document not found.")
    # Only documents on an application's current payload may leave the cloud.
    on_payload = db.scalar(
        select(func.count()).select_from(Application).where(
            Application.state.in_(["filling", "in_review", "approved", "submitting"]),
            Application.payload["documents"].astext.contains(sha256),
        )
    )
    if not on_payload:
        raise conflict("not_on_payload", "That document isn't on any approved list.")
    return doc
