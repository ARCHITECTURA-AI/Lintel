"""A demo account wired to Lintel Lab: résumé confirmed, targets set, watchlist added."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, text

from .config import ROOT, get_settings
from .db import anon_session, user_session
from .db.models import FactCandidate, User
from .security import hash_password
from .services import discovery, ingestion

SAMPLE = ROOT / "lab" / "src" / "lintel_lab" / "sample" / "resume.txt"


def seed_demo(email: str, password: str, *, drain: bool = True) -> str:
    lab = get_settings().lab_base_url.rstrip("/")
    with anon_session() as db:
        found = db.execute(text("SELECT id FROM auth_lookup(:e)"), {"e": email}).first()
        uid = found.id if found else db.scalar(text("SELECT auth_register(:e, :h, :n)"),
                                              {"e": email, "h": hash_password(password), "n": "Riya Sharma"})
    with user_session(uid) as db:
        user = db.get(User, uid)
        user.full_name = "Riya Sharma"
        user.timezone = "Asia/Kolkata"
        user.weekly_budget = 5
        user.no_reply_days = 10
        user.targets = {
            "titles": ["engineer"],
            "exclude_titles": ["senior staff", "principal", "director"],
            "locations": ["remote", "india", "bengaluru"],
            "remote_ok": True,
        }
        user.hard_filters = {
            "locations": ["Remote", "India", "Bengaluru"],
            "exclude_seniority": ["staff", "principal", "director"],
            "needs_sponsorship": {"US": True, "UK": True},
            "default_country": "US",
        }
        user.onboarding = {"done": True, "steps": ["resume", "facts", "targets", "filters", "budget", "watchlist"]}
        if found is None:
            data = Path(SAMPLE).read_bytes()
            ingestion.upload_resume(db, user, data, "riya-sharma-resume.txt", "text/plain")
            db.flush()
            for c in db.scalars(select(FactCandidate).where(FactCandidate.status == "pending")):
                ingestion.confirm_candidate(db, user, c.id)
        for slug, platform, size in [("acme", "greenhouse", "51-200"), ("northwind", "lever", "201-1000"),
                                     ("globex", "ashby", "1-50"), ("initech", "greenhouse", "1000+")]:
            try:
                discovery.add_company(db, user, f"{lab}/{platform}/{slug}", company_size=size)
            except Exception as exc:  # noqa: BLE001
                print(f"watchlist {slug}: {exc}")
    if drain:
        from .worker import drain as run_queue

        for _ in range(3):
            run_queue(200)
    print(f"demo account ready: {email} / {password}")
    return str(uid)
