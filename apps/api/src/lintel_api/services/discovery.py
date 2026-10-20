"""Discovery from a company watchlist. Feeds are read-only and polled gently."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from lintel_schemas import TERMINAL_STATES, ApplicationState
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import Application, Job, User, WatchlistCompany
from ..errors import bad_request, conflict
from . import feeds, registry
from .core import audit, enqueue, now, transition

EARLY_STATES = {"imported", "fit_review", "grounding", "drafted", "filling", "in_review", "approved"}


def target_match(user: User, job: Job | feeds.NormalizedJob) -> tuple[bool, str]:
    t = user.targets or {}
    titles = [x.lower() for x in t.get("titles") or [] if x.strip()]
    exclude = [x.lower() for x in t.get("exclude_titles") or [] if x.strip()]
    locations = [x.lower() for x in t.get("locations") or [] if x.strip()]
    title = job.title.lower()
    if exclude and any(re.search(r"\b" + re.escape(x) + r"\b", title) for x in exclude):
        return False, "Title is on your exclude list."
    if titles and not any(x in title for x in titles):
        return False, "Title doesn't match your target roles."
    loc = f"{job.location} {job.workplace}".lower()
    remote = "remote" in loc
    if locations:
        if not (any(x in loc for x in locations) or (remote and t.get("remote_ok", True))):
            return False, "Location doesn't match your targets."
    reason = "Matches your target roles" + (" and is remote" if remote else "")
    return True, reason + "."


def add_company(db: Session, user: User, url: str, *, company_size: str | None = None, name: str | None = None) -> WatchlistCompany:
    try:
        ref = feeds.detect(url)
    except feeds.FeedError as exc:
        raise bad_request("detect_failed", str(exc)) from exc
    existing = db.scalar(
        select(WatchlistCompany).where(WatchlistCompany.platform == ref.platform, WatchlistCompany.board_name == ref.board)
    )
    if existing:
        if not existing.active:
            existing.active = True
        return existing
    company = WatchlistCompany(
        user_id=user.id,
        name=(name or ref.name_guess or ref.board).strip(),
        platform=ref.platform,
        board_name=ref.board,
        careers_url=url,
        api_base=ref.api_base,
        region=ref.region,
        company_size=company_size,
    )
    db.add(company)
    db.flush()
    audit(db, user.id, "user", "watchlist.added", "watchlist_company", company.id, platform=ref.platform, board=ref.board)
    enqueue(db, user.id, "sync_company", {"company_id": str(company.id)}, dedupe_key=f"sync:{company.id}")
    return company


def _ref(company: WatchlistCompany) -> feeds.BoardRef:
    return feeds.BoardRef(
        platform=company.platform,
        board=company.board_name,
        api_base=company.api_base or feeds.PUBLIC_BASES[company.platform],
        careers_url=company.careers_url,
        region=company.region,
        name_guess=company.name,
    )


def sync_company(db: Session, user: User, company: WatchlistCompany, *, force: bool = False) -> dict:
    s = get_settings()
    if not force and company.last_synced_at and now() - company.last_synced_at < timedelta(hours=s.feed_poll_hours):
        return {"skipped": True}
    if force and company.last_synced_at and now() - company.last_synced_at < timedelta(minutes=s.feed_min_manual_interval_minutes) \
            and company.last_sync_status == "ok":
        raise conflict("too_soon", "This board was just synced. Lintel polls each board gently, a few times a day.")
    ref = _ref(company)
    try:
        result = feeds.fetch_board(ref, etag=company.etag)
    except feeds.FeedError as exc:
        company.last_synced_at = now()
        company.last_sync_status = "error"
        company.last_error = str(exc)
        return {"error": str(exc)}
    company.last_synced_at = now()
    company.last_sync_status = "ok"
    company.last_error = None
    if result.not_modified or (result.content_hash and result.content_hash == company.content_hash and not force):
        return {"not_modified": True, "created": 0, "closed": 0}
    company.etag = result.etag
    company.content_hash = result.content_hash
    if result.company_name and company.name == feeds._title_from_slug(company.board_name):
        company.name = result.company_name

    existing = {j.posting_id: j for j in db.scalars(select(Job).where(Job.watchlist_company_id == company.id))}
    seen: set[str] = set()
    created = matched = 0
    for nj in result.jobs:
        seen.add(nj.posting_id)
        job = existing.get(nj.posting_id)
        is_match, reason = target_match(user, nj)
        if job is None:
            host = urlparse(nj.apply_url).netloc.lower() or urlparse(company.careers_url).netloc.lower()
            job = Job(
                user_id=user.id,
                watchlist_company_id=company.id,
                platform=company.platform,
                board_name=company.board_name,
                posting_id=nj.posting_id,
                host=host,
                title=nj.title,
                company_name=company.name or nj.company_name,
                apply_url=nj.apply_url,
            )
            db.add(job)
            created += 1
        _apply_fields(job, nj)
        job.company_name = company.name
        job.target_match, job.match_reason = is_match, reason
        job.last_seen_at = now()
        job.closed_at = None
        db.flush()
        if is_match:
            matched += 1
            if company.platform == "greenhouse" and job.questions is None:
                try:
                    qs = feeds.fetch_greenhouse_questions(ref, job.posting_id)
                    job.questions = {"fields": qs} if qs else None
                except (feeds.FeedError, Exception):  # noqa: BLE001 - questions are optional; the runner reads the form
                    pass
            ensure_application(db, user, job)
    closed = 0
    for pid, job in existing.items():
        if pid not in seen and job.closed_at is None:
            job.closed_at = now()
            closed += 1
            close_applications_for(db, job)
    company.job_count = len(seen)
    return {"created": created, "matched": matched, "closed": closed, "total": len(seen)}


def _apply_fields(job: Job, nj: feeds.NormalizedJob) -> None:
    job.title = nj.title
    job.location = nj.location
    job.workplace = nj.workplace
    job.department = nj.department
    job.employment_type = nj.employment_type
    job.description = nj.description
    job.apply_url = nj.apply_url or job.apply_url
    job.comp_min = Decimal(str(nj.comp_min)) if nj.comp_min else None
    job.comp_max = Decimal(str(nj.comp_max)) if nj.comp_max else None
    job.comp_currency = nj.comp_currency
    job.comp_interval = nj.comp_interval
    if nj.questions is not None:
        job.questions = {"fields": nj.questions}
    job.content_hash = nj.content_hash()
    job.updated_at = now()


def close_applications_for(db: Session, job: Job) -> None:
    for app in db.scalars(select(Application).where(Application.job_id == job.id)):
        if app.state in EARLY_STATES and ApplicationState(app.state) not in TERMINAL_STATES:
            transition(db, app, ApplicationState.expired, actor="worker", reason="the posting disappeared from its feed",
                       notify_user=False)
            from .core import notify

            notify(db, app.user_id, "job.closed", "A posting closed",
                   f"{job.title} at {job.company_name} is no longer listed.", link=f"/applications/{app.id}")


def ensure_application(db: Session, user: User, job: Job, *, requested_by_user: bool = False) -> Application:
    app = db.scalar(select(Application).where(Application.job_id == job.id))
    if app:
        return app
    dest = registry.for_host(db, job.host)
    mode = registry.max_mode(dest)
    # Assisted fill is the default even where agent-clicked submit is allowed; the user may opt in per application.
    if mode.value == "approved_submission":
        mode = registry.cap_mode("assisted_fill", dest)
    app = Application(
        user_id=user.id,
        job_id=job.id,
        destination_id=dest.id if dest else None,
        support_mode=mode.value,
    )
    from ..db import set_actor

    set_actor(db, "user" if requested_by_user else "worker",
              "you added this role" if requested_by_user else "matched your targets on the watchlist")
    db.add(app)
    db.flush()
    if registry.prohibited(dest):
        transition(db, app, ApplicationState.draft_only, actor="system",
                   reason=f"{dest.domain if dest else job.host} is prohibited for automation", notify_user=False)
    else:
        enqueue(db, user.id, "fit_brief", {"application_id": str(app.id)}, dedupe_key=f"fit:{app.id}")
    return app


def import_posting(db: Session, user: User, url: str) -> Application:
    """Add one posting by URL. Its company joins the watchlist too."""

    try:
        ref = feeds.detect(url)
    except feeds.FeedError as exc:
        raise bad_request("detect_failed", str(exc)) from exc
    if not ref.posting_id:
        raise bad_request("not_a_posting", "That's a careers page. Add it to the watchlist instead, or paste a single job's URL.")
    board_url = url.split("/jobs/")[0] if "/jobs/" in url else url.rstrip("/").rsplit("/", 1)[0]
    company = add_company(db, user, board_url)
    db.flush()
    if company.last_synced_at is None:
        sync_company(db, user, company, force=True)
    job = db.scalar(select(Job).where(Job.watchlist_company_id == company.id, Job.posting_id == ref.posting_id))
    if job is None:
        raise bad_request("posting_not_found", "That posting isn't on the company's public board (it may have closed).")
    if job.platform == "greenhouse" and job.questions is None:
        try:
            qs = feeds.fetch_greenhouse_questions(_ref(company), job.posting_id)
            job.questions = {"fields": qs} if qs else None
        except Exception:  # noqa: BLE001
            pass
    return ensure_application(db, user, job, requested_by_user=True)


def consider_job(db: Session, user: User, job_id: uuid.UUID) -> Application:
    job = db.get(Job, job_id)
    if job is None:
        raise bad_request("job_not_found", "Job not found.")
    if job.closed_at:
        raise conflict("job_closed", "That posting has closed.")
    return ensure_application(db, user, job, requested_by_user=True)
