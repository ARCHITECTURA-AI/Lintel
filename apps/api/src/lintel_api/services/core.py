"""Small shared services: audit, notifications, tasks, the work queue and the lifecycle engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from lintel_schemas import TERMINAL_STATES, ApplicationState, can_transition
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import set_actor
from ..db.models import Application, AuditEvent, Notification, User, UserTask, WorkItem
from ..errors import conflict


def now() -> datetime:
    return datetime.now(UTC)


def audit(db: Session, user_id: uuid.UUID, actor: str, action: str, subject_type: str = "", subject_id: Any = "",
          **detail: Any) -> None:
    db.add(AuditEvent(user_id=user_id, actor=actor, action=action, subject_type=subject_type,
                      subject_id=str(subject_id), detail=detail))


# ---------------------------------------------------------------------------
# Notifications. Channel order: in-app inbox first, then email, then web push. Every link points
# into the dashboard, which requires a signed-in session.
# ---------------------------------------------------------------------------


def notify(db: Session, user_id: uuid.UUID, kind: str, title: str, body: str = "", link: str = "/",
           *, urgent: bool = False, dedupe_key: str | None = None) -> None:
    stmt = insert(Notification).values(
        user_id=user_id, kind=kind, title=title, body=body, link=link, urgent=urgent, dedupe_key=dedupe_key
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"],
                                           index_where=Notification.dedupe_key.isnot(None))
    db.execute(stmt)
    if urgent:
        enqueue(db, user_id, "deliver_notifications", {}, dedupe_key=f"deliver:{user_id}")


# ---------------------------------------------------------------------------
# Tasks: questions and requests only the user can answer.
# ---------------------------------------------------------------------------


def open_task(db: Session, user_id: uuid.UUID, type_: str, title: str, *, body: str = "",
              application_id: uuid.UUID | None = None, data: dict[str, Any] | None = None,
              dedupe_key: str | None = None) -> UserTask:
    if dedupe_key:
        existing = db.scalar(
            select(UserTask).where(UserTask.user_id == user_id, UserTask.dedupe_key == dedupe_key,
                                   UserTask.status == "open")
        )
        if existing:
            existing.title, existing.body, existing.data = title, body, data or {}
            return existing
    task = UserTask(user_id=user_id, type=type_, title=title, body=body, application_id=application_id,
                    data=data or {}, dedupe_key=dedupe_key)
    db.add(task)
    db.flush()
    return task


def close_task(task: UserTask, status: str = "done", resolution: dict[str, Any] | None = None) -> None:
    task.status = status
    task.resolved_at = now()
    task.resolution = resolution or {}


def close_tasks_for(db: Session, application_id: uuid.UUID, types: list[str] | None = None, status: str = "dismissed") -> None:
    q = select(UserTask).where(UserTask.application_id == application_id, UserTask.status == "open")
    if types:
        q = q.where(UserTask.type.in_(types))
    for t in db.scalars(q):
        close_task(t, status, {"reason": "application moved on"})


# ---------------------------------------------------------------------------
# Work queue: Postgres rows, claimed with FOR UPDATE SKIP LOCKED by the worker.
# ---------------------------------------------------------------------------


def enqueue(db: Session, user_id: uuid.UUID, kind: str, payload: dict[str, Any], *, delay_seconds: int = 0,
            dedupe_key: str | None = None) -> None:
    stmt = insert(WorkItem).values(
        user_id=user_id, kind=kind, payload=payload, run_after=now() + timedelta(seconds=delay_seconds),
        dedupe_key=dedupe_key,
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            index_where=(WorkItem.done_at.is_(None) & WorkItem.failed_at.is_(None) & WorkItem.dedupe_key.isnot(None)),
        )
    db.execute(stmt)


# ---------------------------------------------------------------------------
# Lifecycle engine. Only this function writes application state; every transition records an
# actor and a reason (the database refuses one that does not).
# ---------------------------------------------------------------------------

GATE_NOTICES = {
    ApplicationState.fit_review: ("Fit brief ready", "Decide go or skip for {title} at {company}."),
    ApplicationState.grounding: ("Confirm the facts", "Check the facts behind {title} at {company}."),
    ApplicationState.in_review: ("Ready for your review", "Review the exact payload for {title} at {company}."),
}


def transition(db: Session, app: Application, to: ApplicationState | str, *, actor: str, reason: str,
               notify_user: bool = True) -> None:
    to = ApplicationState(to)
    src = ApplicationState(app.state)
    if src == to:
        return
    if src in TERMINAL_STATES:
        raise conflict("terminal_state", f"This application is {src.value.replace('_', ' ')} and can't change.")
    if not can_transition(src, to):
        raise conflict("illegal_transition", f"Can't move from {src.value} to {to.value}.")
    set_actor(db, actor, reason)
    app.state = to.value
    db.flush()
    if notify_user and to in GATE_NOTICES:
        from ..db.models import Job

        job = db.get(Job, app.job_id)
        title, body = GATE_NOTICES[to]
        notify(db, app.user_id, f"gate.{to.value}", title,
               body.format(title=job.title if job else "a role", company=job.company_name if job else ""),
               link=f"/applications/{app.id}", dedupe_key=f"gate:{app.id}:{to.value}:{int(now().timestamp()) // 60}")


def require_state(app: Application, *states: ApplicationState | str) -> None:
    allowed = {ApplicationState(s) for s in states}
    if ApplicationState(app.state) not in allowed:
        nice = ", ".join(s.value.replace("_", " ") for s in allowed)
        raise conflict("wrong_state", f"This step needs the application to be {nice}; it is {app.state.replace('_', ' ')}.")


def week_start(user: User, at: datetime | None = None) -> datetime:
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(user.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local = (at or now()).astimezone(tz)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday
