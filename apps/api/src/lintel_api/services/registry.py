"""The destination registry decides the support mode, never a model."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from lintel_schemas import SupportMode
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import Destination

_ORDER = [SupportMode.draft_only, SupportMode.assisted_fill, SupportMode.approved_submission]


def default_destinations() -> list[dict]:
    lab = urlparse(get_settings().lab_base_url).netloc
    return [
        {
            "domain": lab,
            "platform": "lab",
            "permitted_paths": ["/greenhouse/", "/lever/", "/ashby/", "/edge/", "/static/"],
            "adapter_version": "lab-1",
            "support_mode": "approved_submission",
            "policy_review_status": "approved",
            "policy_review_date": date.today(),
            "enabled": True,
            "known_limitations": "Lintel Lab is a local test site. Agent-clicked submit is allowed here and nowhere else at launch.",
            "asset_hosts": [],
        },
        {
            "domain": "job-boards.greenhouse.io",
            "platform": "greenhouse",
            "permitted_paths": ["/"],
            "known_limitations": (
                "The apply endpoint needs the employer's Job Board API key, so Lintel fills the employer's own form "
                "in your browser. Testers report CAPTCHA walls on some tenants, and Greenhouse's fraud checks flag "
                "data-center IPs, so fills run from your own connection. Terms review pending."
            ),
            "asset_hosts": ["boards.cdn.greenhouse.io", "job-boards.cdn.greenhouse.io", "boards.greenhouse.io"],
        },
        {
            "domain": "boards.greenhouse.io",
            "platform": "greenhouse",
            "permitted_paths": ["/"],
            "known_limitations": "Legacy Greenhouse board host. Same limits as job-boards.greenhouse.io. Terms review pending.",
            "asset_hosts": ["boards.cdn.greenhouse.io"],
        },
        {
            "domain": "jobs.lever.co",
            "platform": "lever",
            "permitted_paths": ["/"],
            "known_limitations": (
                "The apply POST needs a key issued by the employer and the Postings API does not cover custom "
                "questions, so Lintel reads questions from the hosted form. The public feed can return HTML "
                "intermittently. Terms review pending."
            ),
            "asset_hosts": ["lever-client-logos.s3.us-west-2.amazonaws.com", "cdnjs.cloudflare.com"],
        },
        {
            "domain": "jobs.eu.lever.co",
            "platform": "lever",
            "permitted_paths": ["/"],
            "known_limitations": "EU Lever boards live on a separate regional host. Terms review pending.",
            "asset_hosts": [],
        },
        {
            "domain": "jobs.ashbyhq.com",
            "platform": "ashby",
            "permitted_paths": ["/"],
            "known_limitations": (
                "The authenticated API needs a key from the employer. Published pay bands feed the fit brief. "
                "Ashby has no endpoint listing its customers, so companies are added by careers URL. Terms review pending."
            ),
            "asset_hosts": ["app.ashbyhq.com", "cdn.ashbyprd.com"],
        },
        {
            "domain": "www.linkedin.com",
            "platform": "linkedin",
            "permitted_paths": [],
            "policy_review_status": "rejected",
            "known_limitations": "LinkedIn prohibits bots in its User Agreement. Draft-only: Lintel prepares a packet, you apply.",
            "disabled_reason": "Prohibited by the site's terms.",
        },
        {
            "domain": "myworkdayjobs.com",
            "platform": "workday",
            "permitted_paths": [],
            "policy_review_status": "rejected",
            "known_limitations": "Workday hides form fields in a way that breaks autofill. Draft-only or manual handoff.",
            "disabled_reason": "Out of scope at launch.",
        },
        {
            "domain": "www.indeed.com",
            "platform": "indeed",
            "permitted_paths": [],
            "policy_review_status": "rejected",
            "known_limitations": "Indeed adds CAPTCHA walls. Draft-only or manual handoff.",
            "disabled_reason": "Out of scope at launch.",
        },
    ]


def seed(db: Session) -> int:
    """Insert missing registry rows. Existing rows (and any admin changes) are left alone."""

    n = 0
    for row in default_destinations():
        values = {"support_mode": "draft_only", "enabled": False, "policy_review_status": "pending", **row}
        inserted = db.execute(
            insert(Destination).values(**values).on_conflict_do_nothing(index_elements=["domain"]).returning(Destination.id)
        ).first()
        n += 1 if inserted else 0
    return n


def for_host(db: Session, host: str) -> Destination | None:
    host = host.lower()
    dest = db.scalar(select(Destination).where(Destination.domain == host))
    if dest is None:
        # myworkdayjobs.com tenants live on subdomains
        for d in db.scalars(select(Destination)):
            if host.endswith("." + d.domain):
                return d
    return dest


def max_mode(dest: Destination | None) -> SupportMode:
    if dest is None or not dest.enabled or dest.policy_review_status != "approved":
        return SupportMode.draft_only
    return SupportMode(dest.support_mode)


def prohibited(dest: Destination | None) -> bool:
    return dest is not None and dest.policy_review_status == "rejected"


def cap_mode(requested: SupportMode | str, dest: Destination | None) -> SupportMode:
    req = SupportMode(requested)
    allowed = max_mode(dest)
    return req if _ORDER.index(req) <= _ORDER.index(allowed) else allowed


def path_permitted(dest: Destination, url: str) -> bool:
    path = urlparse(url).path or "/"
    return any(path.startswith(p) for p in dest.permitted_paths or [])
