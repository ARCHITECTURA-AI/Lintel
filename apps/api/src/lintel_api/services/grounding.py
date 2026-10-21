"""Gate 1 decision and gate 2 grounding.

After a go, Lintel builds the form model, maps each field to a fact handle (the mapper sees
labels and handle names, never values), resolves handles locally, and asks the user for
anything only they can answer. Eligibility, sponsorship and preferences are never guessed.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from typing import Any

from lintel_schemas import (
    ApplicationState,
    FieldType,
    FitBrief,
    FormField,
    FormModel,
    RequirementStatus,
    page_version,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    AnswerDraft,
    Application,
    ApplicationRun,
    Job,
    ProfileFact,
    RunnerDevice,
    User,
    UserTask,
)
from ..errors import bad_request, conflict, not_found
from ..llm import provider_for
from ..llm.base import FieldSpec, HandleSpec
from . import facts as ledger
from .core import audit, close_task, enqueue, now, open_task, require_state, transition, week_start
from .feeds import DEFAULT_FORMS

DECLINE = re.compile(r"\b(decline|prefer not|don't wish|do not wish|not to (say|answer|disclose)|choose not)\b", re.I)


# ---------------------------------------------------------------------------
# Gate 1: go or skip, inside the weekly application budget.
# ---------------------------------------------------------------------------


def budget_status(db: Session, user: User) -> dict[str, Any]:
    start = week_start(user).date()
    used = db.scalar(
        select(func.count()).select_from(Application).where(
            Application.week_budget_slot == start,
            Application.state.notin_(["skipped", "cancelled", "expired"]),
        )
    ) or 0
    waiting = db.scalar(
        select(func.count()).select_from(Application).where(
            Application.week_budget_slot > start, Application.state == "fit_review"
        )
    ) or 0
    return {"week_start": start.isoformat(), "budget": user.weekly_budget, "used": used,
            "remaining": max(0, user.weekly_budget - used), "waiting_next_week": waiting}


def decide(db: Session, user: User, app: Application, *, go: bool, reason: str = "", next_week: bool = False) -> None:
    require_state(app, ApplicationState.fit_review)
    if not go:
        app.decided_at = now()
        transition(db, app, ApplicationState.skipped, actor="user", reason=reason or "you skipped this role")
        audit(db, user.id, "user", "fit.decided", "application", app.id, decision="skip",
              recommendation=(app.fit_brief or {}).get("recommendation"))
        return
    status = budget_status(db, user)
    this_week = week_start(user).date()
    if next_week:
        app.week_budget_slot = (week_start(user) + timedelta(days=7)).date()
        app.decided_at = now()
        audit(db, user.id, "user", "fit.decided", "application", app.id, decision="go_next_week",
              recommendation=(app.fit_brief or {}).get("recommendation"))
        return
    if status["remaining"] <= 0 and app.week_budget_slot != this_week:
        raise conflict(
            "budget_full",
            f"You've used all {user.weekly_budget} applications in this week's budget. Queue it for next week, or raise your budget.",
            status,
        )
    app.week_budget_slot = this_week
    app.decided_at = now()
    audit(db, user.id, "user", "fit.decided", "application", app.id, decision="go",
          recommendation=(app.fit_brief or {}).get("recommendation"))
    transition(db, app, ApplicationState.grounding, actor="user", reason=reason or "you chose to go ahead")
    prepare_grounding(db, user, app)


# ---------------------------------------------------------------------------
# Form model and mapping
# ---------------------------------------------------------------------------


def provisional_form(job: Job) -> FormModel:
    from urllib.parse import urlparse

    fields_raw = (job.questions or {}).get("fields") if job.questions else None
    source_fields = fields_raw or DEFAULT_FORMS.get(job.platform, DEFAULT_FORMS["greenhouse"])
    fields = [FormField.model_validate(f) for f in source_fields]
    return FormModel(
        url=job.apply_url,
        host=urlparse(job.apply_url).netloc.lower(),
        page_version=page_version([f.field_key for f in fields]),
        fields=fields,
        source="feed",
    )


def active_device(db: Session) -> RunnerDevice | None:
    return db.scalar(
        select(RunnerDevice).where(RunnerDevice.revoked_at.is_(None)).order_by(RunnerDevice.last_seen_at.desc().nullslast())
    )


def prepare_grounding(db: Session, user: User, app: Application) -> None:
    job = db.get(Job, app.job_id)
    if app.form_model is None:
        fm = provisional_form(job)
        app.form_model = fm.model_dump(mode="json")
        app.form_source = "feed"
    apply_form_model(db, user, app, FormModel.model_validate(app.form_model))
    # A form built from a standard template should be checked against the live page early.
    if not (job.questions or {}).get("fields") and app.support_mode != "draft_only" and active_device(db):
        queue_run(db, user, app, "read_form")
    create_interview_tasks(db, user, app)
    app.profile_version_id = ledger.ensure_profile_version(db, user.id, app.id).id


def queue_run(db: Session, user: User, app: Application, kind: str, payload_hash: str | None = None) -> ApplicationRun | None:
    active = db.scalar(
        select(ApplicationRun).where(
            ApplicationRun.application_id == app.id, ApplicationRun.state.in_(["queued", "running", "waiting_user"])
        )
    )
    if active is not None:
        if active.kind == kind:
            return active
        if active.state == "queued":
            active.state = "cancelled"
            active.ended_reason = f"replaced by a {kind} run"
            db.flush()
        else:
            raise conflict("run_active", "The runner is already working on this application. Wait for it, or cancel it.")
    run = ApplicationRun(user_id=user.id, application_id=app.id, kind=kind, payload_hash=payload_hash)
    db.add(run)
    db.flush()
    return run


def _field_specs(fields: list[FormField]) -> list[FieldSpec]:
    return [FieldSpec(f.field_key, f.label, f.type.value, [o.label for o in f.options], f.required) for f in fields]


def apply_form_model(db: Session, user: User, app: Application, fm: FormModel) -> dict[str, list[str]]:
    """Map a form model onto answer drafts. Existing answers for unchanged fields are kept."""

    facts_now = ledger.current_facts(db, app.id)
    hv = ledger.handle_values(facts_now)
    handles = [HandleSpec(h, desc) for h, (_v, _f, _c, desc) in hv.items()] + [HandleSpec("document.resume", "Your résumé file")]
    existing = {d.field_key: d for d in db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id))}
    fields = [f for f in fm.fields if f.visible or f.required]
    to_map = [f for f in fields if f.field_key not in existing]
    mappings = {}
    if to_map:
        provider = provider_for(db, user.id)
        for m in provider.map_fields(_field_specs(to_map), handles):
            mappings[m.field_key] = m
    added, removed = [], []
    for pos, f in enumerate(fields):
        d = existing.get(f.field_key)
        if d is not None:
            d.position = pos
            d.required = f.required
            d.options = [o.model_dump() for o in f.options]
            continue
        m = mappings.get(f.field_key)
        decision = m.decision if m else ("draft_needed" if f.type == FieldType.textarea else "ask_user")
        category = m.category if m else "unknown"
        if f.is_consent or (f.type == FieldType.checkbox and category == "unknown" and re.search(r"\b(agree|acknowledge|consent|confirm)\b", f.label, re.I)):
            decision, category = "ask_user", "consent"
        d = AnswerDraft(
            user_id=user.id,
            application_id=app.id,
            field_key=f.field_key,
            label=f.label,
            field_type=f.type.value,
            required=f.required,
            options=[o.model_dump() for o in f.options],
            max_length=f.max_length,
            position=pos,
            category=category,
            decision=decision,
            handle=m.handle if m else None,
            status_detail=m.reason if m else "",
        )
        db.add(d)
        added.append(f.field_key)
        resolve_draft(db, user, app, d, hv)
    keep = {f.field_key for f in fields}
    for key, d in existing.items():
        if key not in keep:
            removed.append(key)
            db.delete(d)
    db.flush()
    return {"added": added, "removed": removed}


def resolve_draft(db: Session, user: User, app: Application, d: AnswerDraft, hv: dict | None = None) -> None:
    """Fill a draft from facts where the policy allows; otherwise ask."""

    if hv is None:
        hv = ledger.handle_values(ledger.current_facts(db, app.id))
    job = db.get(Job, app.job_id)
    if d.decision == "skip":
        d.status, d.value = "skipped", None
        return
    if d.category == "consent":
        d.status, d.value = "needs_user", False
        d.status_detail = "You tick consents yourself when you review the payload."
        return
    if d.category == "document" or d.handle == "document.resume":
        d.decision, d.category, d.handle = "handle", "document", "document.resume"
        d.status = "ready"
        d.status_detail = "Your approved résumé is attached by hash."
        return
    if d.category == "demographic":
        own = next((v for h, v in hv.items() if h.startswith("demographic.") and h.split(".", 1)[1] in d.label.lower()), None)
        if own:
            choice = ledger.match_option(own[0], d.options) if d.options else own[0]
            if choice is not None:
                d.value, d.fact_ids, d.status = choice, [uuid.UUID(own[1])], "ready"
                d.status_detail = "From your self-identification answers."
                return
        decline = next((o["value"] for o in d.options if DECLINE.search(o.get("label", ""))), None)
        if decline is not None or not d.required:
            d.value = decline
            d.status = "ready" if decline is not None else "skipped"
            d.status_detail = "Voluntary. Lintel declines to self-identify unless you choose otherwise."
            return
    if d.decision == "handle" and d.handle in hv:
        value, fact_id, _cat, _desc = hv[d.handle]
        if d.options:
            choice = ledger.match_option(value, d.options)
            if choice is None:
                d.status = "needs_user"
                d.status_detail = f"Your answer ({value}) doesn't match any option. Choose one."
                _unknown_task(db, user, app, job, d)
                return
            value = choice
        d.value, d.fact_ids, d.status = value, [uuid.UUID(fact_id)], "ready"
        d.status_detail = f"From your fact: {d.handle}."
        return
    if d.decision == "draft_needed":
        d.status = "pending"
        d.status_detail = "Drafted from your confirmed facts after you confirm grounding."
        return
    # ask_user, or a handle the ledger doesn't have yet
    d.decision = "ask_user"
    d.status = "needs_user"  # optional questions left unanswered are simply omitted from the payload
    d.status_detail = {
        "eligibility": "Eligibility is never guessed. Your answer becomes a fact you can reuse.",
        "preference": "Only you know this. Your answer becomes a fact you can reuse.",
        "contact": "Lintel doesn't have this detail yet.",
    }.get(d.category, "Only you can answer this.")
    _unknown_task(db, user, app, job, d)


def _unknown_task(db: Session, user: User, app: Application, job: Job, d: AnswerDraft) -> None:
    open_task(
        db, user.id, "unknown_answer",
        title=d.label,
        body=f"{job.title} at {job.company_name} asks this. {d.status_detail}",
        application_id=app.id,
        data={"field_key": d.field_key, "category": d.category, "handle": d.handle, "options": d.options,
              "field_type": d.field_type, "required": d.required},
        dedupe_key=f"unknown:{app.id}:{d.field_key}",
    )


# ---------------------------------------------------------------------------
# Answers to unknown fields become facts (scoped to this application unless told otherwise).
# ---------------------------------------------------------------------------

_HANDLE_FACT = {
    "contact.": ("contact", "field"),
    "links.": ("link", "field"),
    "prefs.": ("preference", "field"),
    "eligibility.": ("eligibility", "field"),
    "demographic": ("demographic", "field"),
}


def _fact_for_answer(d: AnswerDraft, value: Any) -> tuple[str, dict[str, Any], str]:
    handle = d.handle or ""
    shown = value if not isinstance(value, list) else ", ".join(value)
    if d.options and not isinstance(value, list):
        shown = next((o["label"] for o in d.options if o["value"] == value), value)
    if handle.startswith("eligibility."):
        _, field, country = (handle.split(".") + ["US"])[:3]
        where = "the US" if country == "US" else country
        yes = str(shown).strip().lower().startswith(("yes", "true", "y"))
        no = str(shown).strip().lower().startswith(("no", "false", "n"))
        if field == "work_auth":
            text = f"I am authorized to work in {where}." if yes else f"I am not authorized to work in {where}." if no else f"Work authorization in {where}: {shown}."
        else:
            text = f"I will need visa sponsorship to work in {where}." if yes else f"I do not need visa sponsorship to work in {where}." if no else f"Visa sponsorship in {where}: {shown}."
        return "eligibility", {"field": field, "country": country, "value": shown}, text
    for prefix, (kind, _key) in _HANDLE_FACT.items():
        if handle.startswith(prefix) and "." in handle:
            field = handle.split(".", 1)[1].replace("[0]", "")
            return kind, {"field": field, "value": shown}, f"{d.label.rstrip(' *?:')}: {shown}."
    if d.category == "demographic":
        return "demographic", {"field": re.sub(r"\W+", "_", d.label.lower()).strip("_")[:40], "value": shown}, f"{d.label.rstrip(' *?:')}: {shown}."
    field = re.sub(r"\W+", "_", d.label.lower()).strip("_")[:40]
    return "preference", {"field": field, "value": shown}, f"{d.label.rstrip(' *?:')}: {shown}."


def answer_field(db: Session, user: User, app: Application, field_key: str, value: Any, *, scope: str = "application") -> AnswerDraft:
    d = db.scalar(select(AnswerDraft).where(AnswerDraft.application_id == app.id, AnswerDraft.field_key == field_key))
    if d is None:
        raise not_found("That question isn't on this application.")
    if d.category == "consent":
        raise bad_request("consent_at_review", "Consents are ticked at review, right before you approve.")
    if d.options:
        values = value if isinstance(value, list) else [value]
        allowed = {o["value"] for o in d.options}
        if not all(v in allowed for v in values):
            raise bad_request("bad_option", "Choose one of the listed options.")
    elif isinstance(value, str):
        value = value.strip()
        if not value and d.required:
            raise bad_request("empty_answer", "This question is required.")
        if d.max_length and len(value) > d.max_length:
            raise bad_request("too_long", f"Keep it under {d.max_length} characters.")
    kind, attrs, statement = _fact_for_answer(d, value)
    fact = ledger.add_fact(
        db, user.id,
        kind=kind, claim_scope="personal", statement=statement, attributes=attrs,
        source_type="user_entry", source_ref=f"answered for {d.label!r}",
        application_scope_id=app.id if scope == "application" else None,
    )
    d.value = value
    d.fact_ids = [fact.id]
    d.status = "ready"
    d.decision = "handle" if d.handle else "ask_user"
    d.status_detail = "Your answer" + (" (saved for all applications)." if scope == "all" else " (this application only).")
    d.updated_at = now()
    task = db.scalar(select(UserTask).where(UserTask.dedupe_key == f"unknown:{app.id}:{field_key}", UserTask.status == "open"))
    if task:
        close_task(task, "done", {"fact_id": str(fact.id), "scope": scope})
    return d


# ---------------------------------------------------------------------------
# Fact Interview: one pointed question when the role asks for evidence the ledger lacks.
# ---------------------------------------------------------------------------


def _req_key(text: str) -> str:
    return hashlib.sha256(text.lower().encode()).hexdigest()[:10]


def create_interview_tasks(db: Session, user: User, app: Application, limit: int = 3) -> int:
    if not app.fit_brief:
        return 0
    job = db.get(Job, app.job_id)
    brief = FitBrief.model_validate(app.fit_brief)
    n = 0
    for r in brief.requirements:
        if r.status == RequirementStatus.met or not r.interview_question:
            continue
        if r.importance != "must" and n >= 1:
            continue
        open_task(
            db, user.id, "fact_interview",
            title=r.interview_question,
            body=f"{job.title} at {job.company_name} asks for: {r.text}",
            application_id=app.id,
            data={"requirement": r.text, "question": r.interview_question, "status": r.status.value},
            dedupe_key=f"interview:{app.id}:{_req_key(r.text)}",
        )
        n += 1
        if n >= limit:
            break
    return n


def answer_interview(db: Session, user: User, task: UserTask, *, answer: str, claim_scope: str,
                     employer: str | None = None, skills: list[str] | None = None, none: bool = False,
                     reusable: bool = True) -> ProfileFact | None:
    if task.type not in ("fact_interview", "claim_review") or task.status != "open":
        raise conflict("task_closed", "That question was already answered.")
    app = db.get(Application, task.application_id) if task.application_id else None
    job = db.get(Job, app.job_id) if app else None
    if none:
        close_task(task, "done", {"answer": "none"})
        audit(db, user.id, "user", "interview.no_evidence", "user_task", task.id)
        return None
    answer = re.sub(r"\s+", " ", answer or "").strip()
    if len(answer) < 3:
        raise bad_request("empty_answer", "Write a sentence about what you did, or choose “I haven't done this”.")
    if claim_scope not in ("employment", "project", "coursework", "personal", "education"):
        raise bad_request("bad_scope", "Say whether this was a job, a project, coursework or something personal.")
    if claim_scope == "employment" and not employer:
        raise bad_request("employer_needed", "Name the employer for work done in a job.")
    kind = "achievement"
    answer = re.sub(r"^(yes|yeah|yep|yup|sure)\s*[,.!:-]?\s+", "", answer, flags=re.I)
    answer = answer[0].upper() + answer[1:]
    statement = answer if answer.endswith((".", "!", "?")) else answer + "."
    if claim_scope == "project" and not re.match(r"^(personal|side|course) project", statement, re.I):
        statement = "Personal project: " + statement
    from lintel_trust.claimcheck.tokens import _tools_in

    found_skills = sorted({t.norm for t in _tools_in(answer, case_insensitive=True)} | set(skills or []))
    fact = ledger.add_fact(
        db, user.id,
        kind=kind,
        claim_scope="personal" if claim_scope == "personal" else ("education" if claim_scope == "education" else claim_scope),
        statement=statement,
        attributes={"employer": employer, "skills": found_skills} if employer else {"skills": found_skills},
        source_type="user_interview",
        source_ref=(f"Fact Interview, {now():%b %d, %Y}" + (f", for {job.title} at {job.company_name}" if job else "")
                    + f": “{task.data.get('question') or task.title}”"),
        application_scope_id=None if reusable or not app else app.id,
    )
    close_task(task, "done", {"fact_id": str(fact.id)})
    if app and app.fit_brief:
        _reassess_requirement(db, user, app, task.data.get("requirement"), fact)
    return fact


def _reassess_requirement(db: Session, user: User, app: Application, requirement: str | None, fact: ProfileFact) -> None:
    if not requirement:
        return
    brief = FitBrief.model_validate(app.fit_brief)
    provider = provider_for(db, user.id)
    for r in brief.requirements:
        if r.text == requirement:
            from ..llm.base import RequirementOut

            a = provider.assess_requirements([RequirementOut(r.text, r.importance)], ledger.model_summaries(ledger.current_facts(db, app.id)))[0]
            r.status = RequirementStatus(a.status)
            r.evidence_fact_ids = a.evidence_fact_ids or [str(fact.id)]
            r.note = a.note + " (updated after your answer)"
            if r.status == RequirementStatus.met:
                r.interview_question = None
    app.fit_brief = brief.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Gate 2 view and confirmation
# ---------------------------------------------------------------------------


def grounding_view(db: Session, app: Application) -> dict[str, Any]:
    from ..llm.heuristics import relevance

    job = db.get(Job, app.job_id)
    facts_now = ledger.current_facts(db, app.id)
    visible = [f for f in facts_now if f.kind in ledger.MODEL_VISIBLE_KINDS]
    drafts = list(db.scalars(select(AnswerDraft).where(AnswerDraft.application_id == app.id).order_by(AnswerDraft.position)))
    plan = []
    for d in drafts:
        if d.decision != "draft_needed":
            continue
        q = d.label + " " + job.title
        ranked = sorted(visible, key=lambda f: relevance(q + " " + (job.description or "")[:2000], f.statement + " " + " ".join((f.attributes or {}).get("skills") or [])), reverse=True)[:4]
        plan.append({"field_key": d.field_key, "label": d.label, "fact_ids": [str(f.id) for f in ranked]})
    tasks = list(db.scalars(select(UserTask).where(UserTask.application_id == app.id, UserTask.status == "open")))
    blocking = [t for t in tasks if t.type == "unknown_answer" and t.data.get("required")]
    return {"plan": plan, "open_tasks": [str(t.id) for t in tasks], "blocking": [str(t.id) for t in blocking]}


def confirm_grounding(db: Session, user: User, app: Application) -> None:
    require_state(app, ApplicationState.grounding)
    view = grounding_view(db, app)
    if view["blocking"]:
        raise conflict("questions_open", f"Answer the {len(view['blocking'])} required question(s) first.",
                       {"task_ids": view["blocking"]})
    # Unanswered optional interview questions are set aside, not guessed.
    for t in db.scalars(select(UserTask).where(UserTask.application_id == app.id, UserTask.status == "open",
                                               UserTask.type == "fact_interview")):
        close_task(t, "dismissed", {"reason": "grounding confirmed without an answer"})
    app.profile_version_id = ledger.ensure_profile_version(db, user.id, app.id).id
    audit(db, user.id, "user", "grounding.confirmed", "application", app.id, profile_version_id=str(app.profile_version_id))
    enqueue(db, user.id, "draft_application", {"application_id": str(app.id)}, dedupe_key=f"draft:{app.id}")
