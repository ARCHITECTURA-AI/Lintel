"""The worker: feed sync, fit briefs, drafting, delivery, and the recovery scheduler.

Queue rows are claimed with FOR UPDATE SKIP LOCKED through a narrow SECURITY DEFINER function;
each item is then processed in its own transaction under its user's row-level security.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import traceback
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .db import anon_session, user_session
from .db.models import Application, User, WatchlistCompany, WorkItem
from .services import delivery, discovery, drafting, execution, fit, grounding, outcomes
from .services.core import enqueue, now, transition, week_start

log = logging.getLogger("lintel.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _sync(db: Session, user: User, payload: dict[str, Any]) -> None:
    company = db.get(WatchlistCompany, uuid.UUID(payload["company_id"]))
    if company and company.active:
        discovery.sync_company(db, user, company, force=payload.get("force", True))


def _fit(db: Session, user: User, payload: dict[str, Any]) -> None:
    app = db.get(Application, uuid.UUID(payload["application_id"]))
    if app and app.state in ("imported", "fit_review"):
        fit.generate(db, user, app)


def _draft(db: Session, user: User, payload: dict[str, Any]) -> None:
    app = db.get(Application, uuid.UUID(payload["application_id"]))
    if app:
        drafting.draft_application(db, user, app)


def _deliver(db: Session, user: User, payload: dict[str, Any]) -> None:
    delivery.deliver(db, user)


HANDLERS = {
    "sync_company": _sync,
    "fit_brief": _fit,
    "draft_application": _draft,
    "deliver_notifications": _deliver,
}


def process_one(item_row: Any) -> None:
    uid = item_row.user_id
    try:
        with user_session(uid) as db:
            user = db.get(User, uid)
            if user is None:
                return
            HANDLERS[item_row.kind](db, user, item_row.payload or {})
            db.execute(text("UPDATE work_queue SET done_at = now(), locked_at = NULL WHERE id = :i"), {"i": item_row.id})
    except Exception as exc:  # noqa: BLE001
        log.warning("work item %s (%s) failed: %s", item_row.id, item_row.kind, exc)
        with user_session(uid) as db:
            item = db.get(WorkItem, item_row.id)
            if item is None:
                return
            item.last_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:500]
            item.locked_at = None
            if item.attempts >= item.max_attempts:
                item.failed_at = now()
            else:
                item.run_after = now() + timedelta(seconds=10 * 2 ** item.attempts)


def drain(max_items: int = 50) -> int:
    """Process ready items until none are left (or max_items). Returns how many ran."""

    done = 0
    while done < max_items:
        with anon_session() as db:
            items = db.execute(text("SELECT * FROM claim_work(:w, :k, 5)"), {"w": WORKER_ID, "k": list(HANDLERS)}).all()
        if not items:
            break
        for it in items:
            process_one(it)
            done += 1
    return done


def schedule_user(uid: uuid.UUID, *, hourly: bool) -> None:
    with user_session(uid) as db:
        user = db.get(User, uid)
        if user is None:
            return
        execution.sweep(db, user)
        outcomes.sweep_no_reply(db, user)
        # The surplus waits: roles queued for this week move on when their week arrives.
        this_week = week_start(user).date()
        for app in db.scalars(select(Application).where(Application.state == "fit_review", Application.week_budget_slot == this_week,
                                                        Application.decided_at.isnot(None))):
            # the slot was reserved when the user queued it, so the budget already counts it
            transition(db, app, "grounding", actor="worker", reason="this week's budget opened")
            grounding.prepare_grounding(db, user, app)
        if hourly:
            for company in db.scalars(select(WatchlistCompany).where(WatchlistCompany.active.is_(True))):
                enqueue(db, user.id, "sync_company", {"company_id": str(company.id), "force": False}, dedupe_key=f"sync:{company.id}")
            delivery.daily_digest(db, user)


def scheduler_tick(*, hourly: bool = False) -> None:
    with anon_session() as db:
        uids = list(db.scalars(text("SELECT * FROM scheduler_user_ids()")))
    for uid in uids:
        try:
            schedule_user(uid, hourly=hourly)
        except Exception:  # noqa: BLE001
            log.exception("scheduler failed for a user")
    if hourly:
        from .config import get_settings

        with anon_session() as db:
            db.execute(text("SELECT retention_purge(:d)"), {"d": get_settings().step_log_retention_days})


def run_forever(stop: threading.Event | None = None, poll: float = 1.0, tick: float = 15.0) -> None:
    stop = stop or threading.Event()
    last_tick = 0.0
    last_hour = 0.0
    log.info("worker %s started", WORKER_ID)
    while not stop.is_set():
        try:
            drain()
            t = time.monotonic()
            if t - last_tick >= tick:
                hourly = t - last_hour >= 3600
                scheduler_tick(hourly=hourly)
                last_tick = t
                if hourly:
                    last_hour = t
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
        stop.wait(poll)


def start_background() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(stop,), name="lintel-worker", daemon=True).start()
    return stop
