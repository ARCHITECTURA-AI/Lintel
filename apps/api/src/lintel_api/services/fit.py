"""Fit brief (gate 1): requirements met with evidence, gaps, uncertain items, conflicts with hard
filters, and a recommendation of apply, skip or ask. Effort goes to roles that can convert."""

from __future__ import annotations

import re

from lintel_schemas import (
    ApplicationState,
    FilterConflict,
    FitBrief,
    FitLabel,
    Recommendation,
    Requirement,
    RequirementStatus,
)
from sqlalchemy.orm import Session

from ..db.models import Application, Job, User
from ..llm import provider_for
from ..llm.base import RequirementOut
from . import facts as ledger
from .core import now, transition

SENIORITY = ["intern", "junior", "associate", "mid", "senior", "staff", "principal", "lead", "director", "head", "vp"]
NO_SPONSOR = re.compile(
    r"\b(no|not able to|unable to|cannot|can't|will not|won't|does not|do not)\s+(provide\s+|offer\s+)?(visa\s+)?sponsor",
    re.IGNORECASE,
)
MUST_BE_AUTHORIZED = re.compile(r"must (be|have) (legally )?(authori[sz]ed|eligible|the right) to work in (the )?([A-Z][\w. ]+)", re.I)


def _comp_text(job: Job) -> str | None:
    if not job.comp_min and not job.comp_max:
        return None
    cur = job.comp_currency or ""
    lo = f"{int(job.comp_min):,}" if job.comp_min else "?"
    hi = f"{int(job.comp_max):,}" if job.comp_max else "?"
    per = f" per {job.comp_interval}" if job.comp_interval else ""
    return f"{cur} {lo} to {hi}{per}".strip()


def _country_of(location: str) -> str | None:
    low = location.lower()
    for pat, code in [
        (r"\b(united states|usa|u\.s\.|us|new york|san francisco|seattle|austin|boston|nyc|remote - us|remote \(us\))\b", "US"),
        (r"\b(united kingdom|uk|london|manchester|edinburgh)\b", "UK"),
        (r"\b(india|bengaluru|bangalore|mumbai|delhi|hyderabad|pune|chennai)\b", "IN"),
        (r"\b(canada|toronto|vancouver|montreal)\b", "CA"),
        (r"\b(germany|berlin|munich)\b", "DE"),
    ]:
        if re.search(pat, low):
            return code
    return None


def conflicts_for(user: User, job: Job, facts) -> list[FilterConflict]:
    hf = user.hard_filters or {}
    out: list[FilterConflict] = []
    loc = f"{job.location} {job.workplace}".lower()
    remote = "remote" in loc
    if hf.get("remote_only") and not remote:
        out.append(FilterConflict(filter="Remote only", detail=f"This role is listed as {job.location or 'on-site'}."))
    allowed = [x.lower() for x in hf.get("locations") or [] if x.strip()]
    if allowed and not remote and not any(a in loc for a in allowed):
        out.append(FilterConflict(filter="Locations", detail=f"{job.location or 'Location not stated'} isn't one of your locations."))

    # Sponsorship: compare what the posting says with the user's confirmed eligibility facts.
    country = _country_of(job.location) or (hf.get("default_country") or None)
    needs = {k.upper(): bool(v) for k, v in (hf.get("needs_sponsorship") or {}).items()}
    for f in facts:
        a = f.attributes or {}
        if f.kind == "eligibility" and a.get("field") == "sponsorship":
            needs[(a.get("country") or "US").upper()] = str(a.get("value", "")).lower().startswith("y")
    text = job.description or ""
    if country and needs.get(country) and (NO_SPONSOR.search(text) or MUST_BE_AUTHORIZED.search(text)):
        out.append(FilterConflict(filter="Sponsorship", detail=f"The posting says it won't sponsor, and you need sponsorship in {country}."))
    elif country and needs.get(country) and remote is False and not NO_SPONSOR.search(text):
        out.append(FilterConflict(filter="Sponsorship", severity="soft",
                                  detail=f"You need sponsorship in {country}; the posting doesn't say whether it sponsors."))

    min_salary = hf.get("min_salary") or {}
    if min_salary.get("amount") and job.comp_max and (job.comp_currency or "").upper() == str(min_salary.get("currency", "")).upper():
        if float(job.comp_max) < float(min_salary["amount"]):
            out.append(FilterConflict(filter="Minimum pay", detail=f"Tops out at {_comp_text(job)}, below your floor."))

    title = job.title.lower()
    for word in hf.get("exclude_seniority") or []:
        if re.search(r"\b" + re.escape(word.lower()) + r"\b", title):
            out.append(FilterConflict(filter="Seniority", detail=f'"{job.title}" is a {word} role, which you excluded.'))
            break
    types = [t.lower() for t in hf.get("employment_types") or []]
    if types and job.employment_type and not any(t in job.employment_type.lower() for t in types):
        out.append(FilterConflict(filter="Employment type", severity="soft", detail=f"Listed as {job.employment_type}."))
    for name in hf.get("exclude_companies") or []:
        if name.strip() and name.strip().lower() in job.company_name.lower():
            out.append(FilterConflict(filter="Excluded company", detail=f"You excluded {job.company_name}."))
    return out


def build_fit_brief(db: Session, user: User, app: Application, job: Job) -> FitBrief:
    facts = ledger.current_facts(db, app.id)
    provider = provider_for(db, user.id)
    reqs: list[RequirementOut] = provider.extract_requirements(job.title, job.description or "")
    summaries = ledger.model_summaries(facts)
    assessments = provider.assess_requirements(reqs, summaries) if reqs else []
    requirements = [
        Requirement(
            text=r.text,
            importance="nice" if r.importance == "nice" else "must",
            status=RequirementStatus(a.status),
            evidence_fact_ids=a.evidence_fact_ids,
            note=a.note,
            interview_question=a.interview_question,
        )
        for r, a in zip(reqs, assessments, strict=True)
    ]
    conflicts = conflicts_for(user, job, facts)
    hard = [c for c in conflicts if c.severity == "hard"]

    weights = {"must": 1.0, "nice": 0.4}
    value = {RequirementStatus.met: 1.0, RequirementStatus.uncertain: 0.5, RequirementStatus.gap: 0.0}
    total = sum(weights[r.importance] for r in requirements) or 1.0
    score = sum(weights[r.importance] * value[r.status] for r in requirements) / total if requirements else 0.5
    askable = [r for r in requirements if r.status != RequirementStatus.met and r.interview_question and r.importance == "must"]

    if hard:
        label, rec = FitLabel.conflict, Recommendation.skip
        reason = "Conflicts with your hard filters: " + "; ".join(c.filter.lower() for c in hard) + "."
    elif not requirements:
        label, rec = FitLabel.possible, Recommendation.apply
        reason = "The posting states no requirements Lintel could check. Read it yourself before you decide."
    elif score >= 0.75:
        label, rec = FitLabel.strong, Recommendation.apply
        reason = "Your confirmed facts cover most of what the role asks for."
    elif score >= 0.5:
        label = FitLabel.possible
        if askable:
            rec = Recommendation.ask
            reason = f"Answer {len(askable)} question{'s' if len(askable) != 1 else ''} first; true experience may be missing from your ledger."
        else:
            rec = Recommendation.apply
            reason = "A reasonable match with a few gaps."
    else:
        label = FitLabel.stretch
        if askable and score >= 0.3:
            rec = Recommendation.ask
            reason = "A stretch on current facts. If the questions surface real experience, it may be worth it."
        else:
            rec = Recommendation.skip
            reason = "Your confirmed facts cover little of what this role asks for."

    met = sum(1 for r in requirements if r.status == RequirementStatus.met)
    summary = (
        (f"{met} of {len(requirements)} requirements met with evidence" if requirements else "No checkable requirements in the posting")
        + (f", {len(askable)} worth asking about" if askable else "")
        + (f", {len(hard)} hard-filter conflict{'s' if len(hard) != 1 else ''}" if hard else "")
        + "."
    )
    return FitBrief(
        summary=summary,
        label=label,
        score=round(score, 3),
        recommendation=rec,
        recommendation_reason=reason,
        requirements=requirements,
        conflicts=conflicts,
        compensation=_comp_text(job),
        location=job.location or None,
    )


def generate(db: Session, user: User, app: Application) -> FitBrief:
    job = db.get(Job, app.job_id)
    brief = build_fit_brief(db, user, app, job)
    app.fit_brief = brief.model_dump(mode="json")
    app.fit_label = brief.label.value
    app.fit_score = brief.score
    app.fit_generated_at = now()
    if app.state == ApplicationState.imported.value:
        transition(db, app, ApplicationState.fit_review, actor="worker", reason="fit brief prepared")
    return brief
