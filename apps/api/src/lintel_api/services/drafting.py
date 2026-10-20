"""Drafting with a claim check on every sentence, and the canonical payload.

The drafter attaches supporting_fact_ids to each sentence. Then the token check, the scope check
and the verifier run in that order, each failing closed. A sentence that fails goes back to the
drafter once; if it fails again it becomes a question for the user.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from lintel_schemas import (
    ApplicationState,
    CanonicalPayload,
    Destination,
    Fact,
    FitBrief,
    PayloadAnswer,
    PayloadConsent,
    PayloadDocument,
    Platform,
    SentenceCheck,
)
from lintel_trust import payload_hash
from lintel_trust.claimcheck import check_sentence, split_sentences
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AnswerDraft,
    Application,
    ApprovalRecord,
    Document,
    Job,
    ProfileFact,
    ResumeVariant,
    User,
    UserTask,
)
from ..errors import bad_request, conflict, not_found
from ..llm import MeteredProvider, provider_for
from ..llm.heuristics import relevance
from . import facts as ledger
from .core import audit, close_task, now, open_task, require_state, transition

PLATFORM_PREFIX = {"greenhouse": "gh", "lever": "lv", "ashby": "ab"}


class ProviderVerifier:
    """Adapts the model provider to the claim check's Verifier protocol."""

    def __init__(self, provider: MeteredProvider):
        self.provider = provider

    def verify(self, sentence: str, facts: list[Fact]):
        return self.provider.verify(sentence, [ledger.summary(f) for f in facts])


def _context(job: Job) -> list[str]:
    return [job.company_name, job.title]


def check(db: Session, user: User, job: Job, text: str, fact_ids: list[str], all_facts: list[ProfileFact],
          provider: MeteredProvider | None = None) -> SentenceCheck:
    by_id = {str(f.id): f for f in all_facts}
    cited = [ledger.to_schema(by_id[i]) for i in fact_ids if i in by_id]
    provider = provider or provider_for(db, user.id)
    return check_sentence(
        text,
        cited,
        all_facts=[ledger.to_schema(f) for f in all_facts],
        context_terms=_context(job),
        verifier=ProviderVerifier(provider),
    )


def _relevant_facts(job: Job, question: str, facts: list[ProfileFact], k: int = 8) -> list[ProfileFact]:
    visible = [f for f in facts if f.kind in ledger.MODEL_VISIBLE_KINDS]
    q = f"{question} {job.title} {(job.description or '')[:3000]}"
    return sorted(visible, key=lambda f: relevance(q, f.statement + " " + " ".join((f.attributes or {}).get("skills") or [])), reverse=True)[:k]


def draft_one(db: Session, user: User, app: Application, d: AnswerDraft, *, facts: list[ProfileFact] | None = None) -> None:
    job = db.get(Job, app.job_id)
    facts = facts if facts is not None else ledger.current_facts(db, app.id)
    provider = provider_for(db, user.id)
    pool = _relevant_facts(job, d.label, facts)
    feedback: list[str] = []
    final: list[dict[str, Any]] = []
    for attempt in (1, 2):
        sentences = provider.draft_answer(
            question=d.label, company=job.company_name, title=job.title, description=job.description or "",
            facts=[ledger.summary(f) for f in pool], max_chars=d.max_length, feedback=feedback or None,
        )
        d.attempts = attempt
        if not sentences:
            final = []
            break
        results = []
        feedback = []
        for s in sentences:
            res = check(db, user, job, s.text, s.fact_ids, facts, provider)
            results.append({"text": s.text, "fact_ids": s.fact_ids, "check": res.model_dump(mode="json")})
            if not res.passed:
                fail = res.first_failure
                feedback.append(f'"{s.text}" failed the {fail.name} check: {fail.detail}')
        final = results
        if not feedback:
            break
    passing = [s for s in final if s["check"]["passed"]]
    failing = [s for s in final if not s["check"]["passed"]]
    d.sentences = final
    d.fact_ids = sorted({uuid.UUID(i) for s in passing for i in s["fact_ids"]})
    d.value = " ".join(s["text"] for s in passing) if passing else None
    if d.original_value is None and d.value:
        d.original_value = d.value
    d.updated_at = now()
    if not final:
        d.status = "needs_user"
        d.status_detail = "No confirmed fact answers this question yet. Tell Lintel what's true and it will draft from that."
        open_task(
            db, user.id, "claim_review", title=f"Nothing in your ledger answers: {d.label}",
            body=f"{job.title} at {job.company_name} asks this. Answer in your own words; your answer becomes a fact the draft cites.",
            application_id=app.id,
            data={"field_key": d.field_key, "question": d.label, "kind": "no_facts"},
            dedupe_key=f"claim:{app.id}:{d.field_key}",
        )
    elif failing:
        d.status = "needs_user"
        d.status_detail = f"{len(failing)} sentence(s) failed the claim check twice and were left out. Answer the question to add the fact, or accept the answer without them."
        open_task(
            db, user.id, "claim_review",
            title=f"A sentence for “{d.label}” couldn't be backed by your facts",
            body=" ".join(f'“{s["text"]}”: {_first_fail(s)}' for s in failing),
            application_id=app.id,
            data={"field_key": d.field_key, "question": d.label, "kind": "failed_sentences",
                  "sentences": [{"text": s["text"], "reason": _first_fail(s)} for s in failing]},
            dedupe_key=f"claim:{app.id}:{d.field_key}",
        )
    else:
        d.status = "ready"
        d.status_detail = f"{len(passing)} sentence(s), each traced to cited facts."


def _first_fail(s: dict[str, Any]) -> str:
    for c in s["check"]["checks"]:
        if c["outcome"] == "fail":
            return f'{c["name"]} check: {c["detail"]}'
    return "failed"


def draft_application(db: Session, user: User, app: Application) -> None:
    if app.state != ApplicationState.grounding.value:
        return
    facts = ledger.current_facts(db, app.id)
    for d in db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.decision == "draft_needed")):
        if d.status in ("pending", "needs_user") and not d.edited_by_user:
            draft_one(db, user, app, d, facts=facts)
    from .variants import propose_variant

    try:
        propose_variant(db, user, app)
    except Exception as exc:  # noqa: BLE001 - a variant is optional; the base résumé still works
        audit(db, user.id, "worker", "variant.failed", "application", app.id, error=str(exc)[:200])
    app.profile_version_id = ledger.ensure_profile_version(db, user.id, app.id).id
    refresh_payload(db, app)
    transition(db, app, ApplicationState.drafted, actor="worker", reason="answers drafted and claim checked")


def edit_answer(db: Session, user: User, app: Application, field_key: str, text: str) -> AnswerDraft:
    require_state(app, ApplicationState.drafted, ApplicationState.in_review, ApplicationState.grounding,
                  ApplicationState.approved, ApplicationState.filling)
    d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == field_key))
    if d is None:
        raise not_found("That answer isn't on this application.")
    if d.decision != "draft_needed":
        raise bad_request("not_free_text", "Only drafted answers are edited as text. Change other answers from the question.")
    text = (text or "").strip()
    if d.max_length and len(text) > d.max_length:
        raise bad_request("too_long", f"Keep it under {d.max_length} characters.")
    job = db.get(Job, app.job_id)
    facts = ledger.current_facts(db, app.id)
    provider = provider_for(db, user.id)
    prior = {s["text"].strip(): s["fact_ids"] for s in d.sentences or []}
    results = []
    for sentence in split_sentences(text):
        if sentence in prior:
            ids = prior[sentence]
        else:
            ranked = _relevant_facts(job, sentence, facts, k=3)
            ids = [str(f.id) for f in ranked if relevance(sentence, f.statement + " " + " ".join((f.attributes or {}).get("skills") or [])) > 0.15]
        res = check(db, user, job, sentence, ids, facts, provider)
        results.append({"text": sentence, "fact_ids": ids, "check": res.model_dump(mode="json"), "edited": sentence not in prior})
    failing = [s for s in results if not s["check"]["passed"]]
    d.sentences = results
    d.edited_by_user = True
    d.updated_at = now()
    if failing:
        d.status = "blocked"
        d.status_detail = "The claim check blocked this edit: " + " ".join(f'“{s["text"]}”: {_first_fail(s)}' for s in failing)
        d.value = text
    else:
        d.status = "ready"
        d.status_detail = "Edited by you; every sentence traces to cited facts."
        d.value = text
        d.fact_ids = sorted({uuid.UUID(i) for s in results for i in s["fact_ids"]})
        task = db.scalar(select(UserTask).where(UserTask.dedupe_key == f"claim:{app.id}:{field_key}", UserTask.status == "open"))
        if task:
            close_task(task, "done", {"resolved_by": "edit"})
    audit(db, user.id, "user", "answer.edited", "application", app.id, field_key=field_key, passed=not failing)
    refresh_payload(db, app)
    return d


def accept_without_failed(db: Session, user: User, app: Application, field_key: str) -> AnswerDraft:
    d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == field_key))
    if d is None:
        raise not_found("That answer isn't on this application.")
    passing = [s for s in d.sentences or [] if s["check"]["passed"]]
    if not passing:
        raise conflict("nothing_left", "No sentence passed the claim check. Answer the question or write the answer yourself.")
    d.sentences = passing
    d.value = " ".join(s["text"] for s in passing)
    d.status = "ready"
    d.status_detail = "Kept only the sentences that trace to your facts."
    task = db.scalar(select(UserTask).where(UserTask.dedupe_key == f"claim:{app.id}:{field_key}", UserTask.status == "open"))
    if task:
        close_task(task, "done", {"resolved_by": "accept_partial"})
    refresh_payload(db, app)
    return d


def redraft(db: Session, user: User, app: Application, field_key: str) -> AnswerDraft:
    d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == field_key))
    if d is None or d.decision != "draft_needed":
        raise not_found("That answer isn't drafted.")
    d.edited_by_user = False
    task = db.scalar(select(UserTask).where(UserTask.dedupe_key == f"claim:{app.id}:{field_key}", UserTask.status == "open"))
    if task:
        close_task(task, "done", {"resolved_by": "redraft"})
    draft_one(db, user, app, d)
    refresh_payload(db, app)
    return d


def set_consent(db: Session, app: Application, field_key: str, value: bool) -> AnswerDraft:
    d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == field_key))
    if d is None or d.category != "consent":
        raise not_found("That consent isn't on this application.")
    d.value = bool(value)
    d.status = "ready" if value or not d.required else "needs_user"
    d.status_detail = "Ticked by you." if value else "Not ticked."
    refresh_payload(db, app)
    return d


def set_choice(db: Session, user: User, app: Application, field_key: str, value: Any) -> AnswerDraft:
    """Change a non-text answer (e.g. a demographic choice) directly at review."""

    from .grounding import answer_field

    d = answer_field(db, user, app, field_key, value, scope="application")
    refresh_payload(db, app)
    return d


# ---------------------------------------------------------------------------
# Canonical payload
# ---------------------------------------------------------------------------


def resume_document(db: Session, app: Application) -> Document | None:
    if app.resume_variant_id:
        v = db.get(ResumeVariant, app.resume_variant_id)
        if v and v.status == "approved" and v.document_id:
            return db.get(Document, v.document_id)
    return db.scalar(
        select(Document).where(Document.kind == "resume_base", Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
    )


def readiness(db: Session, app: Application) -> dict[str, Any]:
    drafts = list(db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id).order_by(AnswerDraft.position)))
    issues = []
    for d in drafts:
        if d.status in ("needs_user", "blocked", "pending") and (d.required or d.status == "blocked"):
            issues.append({"field_key": d.field_key, "label": d.label, "status": d.status, "detail": d.status_detail})
    if any(d.category == "document" and d.status != "skipped" for d in drafts) and resume_document(db, app) is None:
        issues.append({"field_key": None, "label": "Résumé", "status": "needs_user", "detail": "Upload a résumé first."})
    return {"ready": not issues, "issues": issues}


def build_payload(db: Session, app: Application) -> CanonicalPayload:
    job = db.get(Job, app.job_id)
    drafts = list(db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id).order_by(AnswerDraft.position)))
    answers, documents, consents = [], [], []
    for d in drafts:
        if d.status == "skipped" or d.decision == "skip":
            continue
        if d.category == "consent":
            consents.append(PayloadConsent(field_key=d.field_key, value=bool(d.value)))
            continue
        if d.category == "document":
            doc = resume_document(db, app)
            if doc is not None:
                documents.append(PayloadDocument(role="resume", sha256=doc.sha256, field_key=d.field_key))
            continue
        if d.status != "ready" or d.value in (None, ""):
            continue
        answers.append(PayloadAnswer(field_key=d.field_key, value=d.value, fact_ids=sorted(str(i) for i in d.fact_ids or [])))
    host = urlparse(job.apply_url).netloc.lower() or job.host
    platform = job.platform if job.platform in Platform.__members__ else "unknown"
    return CanonicalPayload(
        application_id=str(app.id),
        destination=Destination(
            platform=Platform(platform),
            job_identity=f"{PLATFORM_PREFIX.get(job.platform, job.platform)}:{job.board_name}:{job.posting_id}",
            host=host,
        ),
        profile_version_id=str(app.profile_version_id) if app.profile_version_id else "",
        answers=answers,
        documents=documents,
        consents=consents,
    )


def refresh_payload(db: Session, app: Application) -> str:
    """Rebuild the payload. Any change to any field voids a live approval."""

    db.flush()
    payload = build_payload(db, app)
    new_hash = payload_hash(payload)
    if new_hash == app.payload_hash:
        return new_hash
    app.payload = payload.model_dump(mode="json")
    app.payload_hash = new_hash
    live = db.scalar(
        select(ApprovalRecord).where(ApprovalRecord.application_id == app.id, ApprovalRecord.consumed_at.is_(None),
                                     ApprovalRecord.revoked_at.is_(None))
    )
    if live is not None:
        live.revoked_at = now()
        live.revoked_reason = "the payload changed after approval"
        if app.state == ApplicationState.approved.value:
            transition(db, app, ApplicationState.in_review, actor="system", reason="payload changed; the approval was voided")
    return new_hash


def fit_requirements(app: Application) -> list[str]:
    if not app.fit_brief:
        return []
    return [r.text for r in FitBrief.model_validate(app.fit_brief).requirements]
