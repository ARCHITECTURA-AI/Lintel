"""The outcome loop, follow-ups, referral nudges, the weekly review and trust metrics.

No feature here promises an interview. The outcome loop exists so the user can see what is
working for them instead of trusting a headline number. Lintel never messages anyone.
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from lintel_schemas import (
    INTERVIEW_OUTCOME_STAGES,
    REPLY_OUTCOME_STAGES,
    ApplicationState,
    ClaimScope,
    Fact,
    FactKind,
    OutcomeStage,
    SourceType,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    AnswerDraft,
    Application,
    ApprovalRecord,
    AuditEvent,
    Contact,
    FollowUp,
    Job,
    OutcomeEvent,
    SubmitIntent,
    User,
    WatchlistCompany,
)
from ..errors import bad_request, conflict, not_found
from . import facts as ledger
from .core import audit, notify, now, open_task

SENT_STATES = {ApplicationState.confirmed.value, ApplicationState.user_reported_submitted.value}
RELATIONSHIP_RANK = {"former_colleague": 0, "friend": 1, "alum": 2, "acquaintance": 3, "recruiter": 4, "other": 5}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _sent_at(db: Session, app: Application) -> datetime | None:
    if app.confirmed_at:
        return app.confirmed_at
    ev = db.scalar(select(OutcomeEvent.occurred_at).where(OutcomeEvent.application_id == app.id,
                                                         OutcomeEvent.stage.in_(["user_reported_submitted", "submitted"]))
                   .order_by(OutcomeEvent.occurred_at))
    return ev or app.submitted_at


def is_sent(db: Session, app: Application) -> bool:
    if app.state in SENT_STATES:
        return True
    return db.scalar(select(func.count()).select_from(OutcomeEvent).where(
        OutcomeEvent.application_id == app.id,
        OutcomeEvent.stage.in_(["user_reported_submitted", "submitted", *[s.value for s in REPLY_OUTCOME_STAGES]]))) > 0


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def record_stage(db: Session, user: User, app: Application, stage: str, *, note: str = "",
                 occurred_at: datetime | None = None) -> OutcomeEvent:
    try:
        st = OutcomeStage(stage)
    except ValueError as exc:
        raise bad_request("bad_stage", "Unknown stage.") from exc
    if st in (OutcomeStage.submitted, OutcomeStage.submission_uncertain, OutcomeStage.prepared):
        raise bad_request("system_stage", "That stage is recorded by Lintel itself.")
    if st == OutcomeStage.user_reported_submitted:
        if app.state in (ApplicationState.draft_only.value, ApplicationState.submission_uncertain.value):
            pass  # a correction recorded as a new event; the lifecycle state is never overwritten
        else:
            raise bad_request("use_report", "Use “I sent it myself” on the application instead.")
    elif not is_sent(db, app) and app.state != ApplicationState.submission_uncertain.value:
        raise conflict("not_sent", "Record replies once the application has been sent.")
    ev = OutcomeEvent(user_id=user.id, application_id=app.id, stage=st.value, source="user", note=note[:500],
                      occurred_at=occurred_at or now())
    db.add(ev)
    db.flush()
    if st in REPLY_OUTCOME_STAGES or st == OutcomeStage.withdrawn:
        for fu in db.scalars(select(FollowUp).where(FollowUp.application_id == app.id, FollowUp.status.in_(["scheduled", "ready"]))):
            fu.status = "dismissed"
    if st == OutcomeStage.user_reported_submitted:
        schedule_follow_up(db, user, app)
    audit(db, user.id, "user", "outcome.recorded", "application", app.id, stage=st.value)
    return ev


def timeline(db: Session, app_id: uuid.UUID) -> list[OutcomeEvent]:
    return list(db.scalars(select(OutcomeEvent).where(OutcomeEvent.application_id == app_id).order_by(OutcomeEvent.occurred_at)))


# ---------------------------------------------------------------------------
# Follow-ups and referral nudges
# ---------------------------------------------------------------------------


def schedule_follow_up(db: Session, user: User, app: Application) -> None:
    exists = db.scalar(select(FollowUp).where(FollowUp.application_id == app.id, FollowUp.kind == "follow_up",
                                              FollowUp.status.in_(["scheduled", "ready"])))
    if exists:
        return
    db.add(FollowUp(user_id=user.id, application_id=app.id, kind="follow_up",
                    due_at=now() + timedelta(days=user.no_reply_days)))


def draft_follow_up(db: Session, user: User, app: Application) -> tuple[str, list[dict[str, Any]]]:
    from .drafting import check

    job = db.get(Job, app.job_id)
    facts_now = ledger.current_facts(db, app.id)
    sent = _sent_at(db, app)
    name = ledger.handle_values(facts_now).get("contact.first_name")
    when = f"on {sent:%B} {sent.day}" if sent else "recently"
    # When it was sent is Lintel's own record, not a claim about the person; the sentence cites it.
    record = Fact(id="lintel:sent", kind=FactKind.achievement, claim_scope=ClaimScope.personal,
                  statement=f"Applied for {job.title} at {job.company_name} {when}.", source_type=SourceType.user_entry,
                  source_ref="Lintel's send record")
    sentences: list[tuple[str, list[str]]] = [
        (f"Hello {job.company_name} team,", []),
        (f"I applied for the {job.title} role {when} and wanted to follow up.", [record.id]),
    ]
    from ..llm.heuristics import first_person, relevance

    best = sorted([f for f in facts_now if f.kind in ("achievement", "role")],
                  key=lambda f: relevance(job.title + " " + (job.description or "")[:2000], f.statement), reverse=True)[:1]
    if best:
        sentences.append((first_person(best[0].statement), [str(best[0].id)]))
    sentences.append(("I'd welcome the chance to talk about the role.", []))
    sentences.append((f"Thank you, {name[0]}." if name else "Thank you.", [name[1]] if name else []))
    out = []
    for text, ids in sentences:
        res = check(db, user, job, text, [i for i in ids if i != record.id], facts_now,
                    records=[record] if record.id in ids else None)
        out.append({"text": text, "fact_ids": ids, "check": res.model_dump(mode="json")})
    passing = [s["text"] for s in out if s["check"]["passed"]]
    body = passing[0] + "\n\n" + " ".join(passing[1:-1]) + "\n\n" + passing[-1] if len(passing) > 2 else " ".join(passing)
    return body, out


def sweep_no_reply(db: Session, user: User) -> int:
    n = 0
    for fu in db.scalars(select(FollowUp).where(FollowUp.status == "scheduled", FollowUp.due_at <= now(), FollowUp.kind == "follow_up")):
        app = db.get(Application, fu.application_id)
        replied = db.scalar(select(func.count()).select_from(OutcomeEvent).where(
            OutcomeEvent.application_id == app.id, OutcomeEvent.stage.in_([s.value for s in REPLY_OUTCOME_STAGES] + ["withdrawn"])))
        if replied:
            fu.status = "dismissed"
            continue
        if not db.scalar(select(func.count()).select_from(OutcomeEvent).where(OutcomeEvent.application_id == app.id,
                                                                              OutcomeEvent.stage == "no_reply")):
            db.add(OutcomeEvent(user_id=user.id, application_id=app.id, stage="no_reply", source="system",
                                note=f"no reply after {user.no_reply_days} days"))
        fu.draft, fu.draft_sentences = draft_follow_up(db, user, app)
        fu.status = "ready"
        fu.updated_at = now()
        job = db.get(Job, app.job_id)
        notify(db, user.id, "follow_up.ready", "A follow-up is ready to send",
               f"No reply from {job.company_name} after {user.no_reply_days} days. Lintel drafted a short note for you to send.",
               link="/outcomes", dedupe_key=f"followup:{fu.id}")
        n += 1
    return n


def contacts_at(db: Session, company: str) -> list[Contact]:
    rows = list(db.scalars(select(Contact).where(func.lower(Contact.company) == company.lower())))
    return sorted(rows, key=lambda c: RELATIONSHIP_RANK.get(c.relationship, 9))


def referral_nudge(db: Session, user: User, app: Application) -> None:
    job = db.get(Job, app.job_id)
    people = contacts_at(db, job.company_name)
    if people:
        best = people[0]
        open_task(db, user.id, "referral", title=f"Ask {best.name} about {job.company_name}?",
                  body=f"{best.name} ({best.relationship.replace('_', ' ')}) is at {job.company_name}. A referral is a human lever "
                       "autofill can't pull. Lintel drafted a note; you send it.",
                  application_id=app.id, data={"contact_id": str(best.id), "company": job.company_name},
                  dedupe_key=f"referral:{app.id}")
    else:
        open_task(db, user.id, "referral", title=f"Do you know anyone at {job.company_name}?",
                  body="List people you know there. Lintel suggests who to ask and drafts the note; it never messages anyone.",
                  application_id=app.id, data={"company": job.company_name}, dedupe_key=f"referral:{app.id}")


def draft_referral(db: Session, user: User, app: Application, contact: Contact) -> dict[str, Any]:
    job = db.get(Job, app.job_id)
    first = ledger.handle_values(ledger.current_facts(db)).get("contact.first_name", ("",))[0]
    text = (f"Hi {contact.name.split()[0]},\n\nI'm applying for the {job.title} role at {job.company_name}. "
            "Would you be open to referring me, or pointing me to the right person? I can send my résumé and a short note "
            f"on why I'm a fit.\n\nThanks,\n{first}").strip()
    fu = db.scalar(select(FollowUp).where(FollowUp.application_id == app.id, FollowUp.kind == "referral_ask",
                                          FollowUp.contact_id == contact.id, FollowUp.status.in_(["scheduled", "ready"])))
    if fu is None:
        fu = FollowUp(user_id=user.id, application_id=app.id, kind="referral_ask", contact_id=contact.id, due_at=now())
        db.add(fu)
    fu.draft = text
    fu.status = "ready"
    db.flush()
    return {"follow_up_id": str(fu.id), "text": text}


def mark_follow_up(db: Session, fu_id: uuid.UUID, status: str) -> FollowUp:
    fu = db.get(FollowUp, fu_id)
    if fu is None:
        raise not_found("Follow-up not found.")
    if status not in ("sent", "dismissed"):
        raise bad_request("bad_status", "Mark it sent or dismissed.")
    fu.status = status
    fu.sent_at = now() if status == "sent" else None
    fu.updated_at = now()
    return fu


# ---------------------------------------------------------------------------
# Weekly review and metrics
# ---------------------------------------------------------------------------


def _sent_apps(db: Session) -> list[Application]:
    apps = list(db.scalars(select(Application)))
    return [a for a in apps if is_sent(db, a)]


def weekly_review(db: Session, user: User, weeks: int = 12) -> dict[str, Any]:
    since = now() - timedelta(weeks=weeks)
    sent = [a for a in _sent_apps(db) if (_sent_at(db, a) or a.created_at) >= since]
    stages: dict[uuid.UUID, set[str]] = defaultdict(set)
    for ev in db.scalars(select(OutcomeEvent).where(OutcomeEvent.application_id.in_([a.id for a in sent]) if sent else False)):
        stages[ev.application_id].add(ev.stage)
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_([a.job_id for a in sent]))) } if sent else {}
    companies = {c.id: c for c in db.scalars(select(WatchlistCompany))}

    def bucket(key_fn) -> list[dict[str, Any]]:
        groups: dict[str, list[Application]] = defaultdict(list)
        for a in sent:
            groups[key_fn(a)].append(a)
        rows = []
        for key, apps in groups.items():
            replies = sum(1 for a in apps if stages[a.id] & {s.value for s in REPLY_OUTCOME_STAGES})
            interviews = sum(1 for a in apps if stages[a.id] & {s.value for s in INTERVIEW_OUTCOME_STAGES})
            lo, hi = wilson(interviews, len(apps))
            rows.append({"key": key, "sent": len(apps), "replies": replies, "interviews": interviews,
                         "interview_rate": interviews / len(apps), "ci": [lo, hi]})
        return sorted(rows, key=lambda r: -r["sent"])

    def variant_key(a: Application) -> str:
        return "Tailored variant" if a.resume_variant_id else "Base résumé"

    def source_key(a: Application) -> str:
        j = jobs.get(a.job_id)
        return f"{j.platform.title()} · {j.company_name}" if j else "Unknown"

    def size_key(a: Application) -> str:
        j = jobs.get(a.job_id)
        c = companies.get(j.watchlist_company_id) if j else None
        return (c.company_size if c and c.company_size else "Size not set")

    total = len(sent)
    interviews = sum(1 for a in sent if stages[a.id] & {s.value for s in INTERVIEW_OUTCOME_STAGES})
    replies = sum(1 for a in sent if stages[a.id] & {s.value for s in REPLY_OUTCOME_STAGES})
    lo, hi = wilson(interviews, total)
    week_rows = []
    for w in range(weeks - 1, -1, -1):
        start = now() - timedelta(weeks=w + 1)
        end = now() - timedelta(weeks=w)
        in_week = [a for a in sent if start <= (_sent_at(db, a) or a.created_at) < end]
        week_rows.append({"week_start": start.date().isoformat(), "sent": len(in_week),
                          "replies": sum(1 for a in in_week if stages[a.id] & {s.value for s in REPLY_OUTCOME_STAGES}),
                          "interviews": sum(1 for a in in_week if stages[a.id] & {s.value for s in INTERVIEW_OUTCOME_STAGES})})
    return {
        "weeks": weeks,
        "sent": total,
        "replies": replies,
        "interviews": interviews,
        "interviews_per_sent": (interviews / total) if total else None,
        "ci": [lo, hi],
        "note": "A single person's sample is small, and Lintel can't prove it caused any interview. Read the interval, not the point.",
        "by_variant": bucket(variant_key),
        "by_source": bucket(source_key),
        "by_company_size": bucket(size_key),
        "by_week": week_rows,
    }


def trust_metrics(db: Session, user: User) -> dict[str, Any]:
    apps = list(db.scalars(select(Application)))
    sent = [a for a in apps if is_sent(db, a)]
    sent_ids = [a.id for a in sent]
    # 1. unsupported claims in sent applications
    unsupported = 0
    if sent_ids:
        for d in db.scalars(select(AnswerDraft).where(AnswerDraft.application_id.in_(sent_ids), AnswerDraft.decision == "draft_needed")):
            payload_text = d.value or ""
            for s in d.sentences or []:
                if not s["check"]["passed"] and s["text"] in payload_text:
                    unsupported += 1
    flagged = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "claim.flagged")) or 0
    intents = list(db.scalars(select(SubmitIntent)))
    unapproved = sum(1 for i in intents if i.approval_id is None)
    per_app: dict[uuid.UUID, int] = defaultdict(int)
    for i in intents:
        per_app[i.application_id] += 1
    duplicates = sum(1 for c in per_app.values() if c > 1)
    confirmed = [a for a in apps if a.state == ApplicationState.confirmed.value]
    covered = 0
    for a in confirmed:
        has_approval = db.scalar(select(func.count()).select_from(ApprovalRecord).where(ApprovalRecord.application_id == a.id,
                                                                                       ApprovalRecord.consumed_at.isnot(None)))
        has_intent = per_app.get(a.id, 0) > 0
        has_outcome = db.scalar(select(func.count()).select_from(OutcomeEvent).where(OutcomeEvent.application_id == a.id,
                                                                                   OutcomeEvent.source == "adapter"))
        covered += 1 if (has_approval and has_intent and has_outcome) else 0
    minutes = [e.detail.get("minutes_since_decision") for e in db.scalars(
        select(AuditEvent).where(AuditEvent.action == "approval.created").order_by(AuditEvent.id))]
    minutes = [m for m in minutes if isinstance(m, int | float)]
    after_first = minutes[1:] if len(minutes) > 1 else []
    drafted = list(db.scalars(select(AnswerDraft).where(AnswerDraft.decision == "draft_needed", AnswerDraft.original_value.isnot(None))))
    edited = sum(1 for d in drafted if d.edited_by_user)
    decisions = [e.detail for e in db.scalars(select(AuditEvent).where(AuditEvent.action == "fit.decided"))]
    apply_recs = [d for d in decisions if d.get("recommendation") == "apply"]
    accepted = sum(1 for d in apply_recs if d.get("decision") in ("go", "go_next_week"))
    uncertain = sum(1 for a in apps if a.state == ApplicationState.submission_uncertain.value)
    lintel_sends = len(confirmed) + uncertain
    interviews = 0
    for a in sent:
        st = set(db.scalars(select(OutcomeEvent.stage).where(OutcomeEvent.application_id == a.id)))
        if st & {s.value for s in INTERVIEW_OUTCOME_STAGES}:
            interviews += 1
    lo, hi = wilson(interviews, len(sent))
    return {
        "unsupported_claims": {"value": unsupported + flagged, "target": 0, "detail": f"{flagged} flagged by you"},
        "unapproved_submissions": {"value": unapproved, "target": 0},
        "duplicate_sends": {"value": duplicates, "target": 0},
        "audit_coverage": {"value": (covered / len(confirmed)) if confirmed else None, "target": 1.0,
                           "detail": f"{covered} of {len(confirmed)} sent by Lintel have an approval, an intent and an outcome"},
        "user_minutes_per_application": {"value": statistics.median(after_first) if after_first else None, "target": 10,
                                         "detail": f"median of {len(after_first)} after the first"},
        "draft_correction_rate": {"value": (edited / len(drafted)) if drafted else None, "target": None,
                                  "detail": f"{edited} of {len(drafted)} drafted answers edited"},
        "fit_brief_acceptance": {"value": (accepted / len(apply_recs)) if apply_recs else None, "target": None,
                                 "detail": f"{accepted} of {len(apply_recs)} apply recommendations accepted"},
        "uncertain_outcome_rate": {"value": (uncertain / lintel_sends) if lintel_sends else None, "target": None},
        "interviews_per_sent": {"value": (interviews / len(sent)) if sent else None, "ci": [lo, hi], "n": len(sent)},
    }
