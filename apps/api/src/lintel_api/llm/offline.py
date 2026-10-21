"""Offline provider: deterministic heuristics with the same interface as the model provider.

Used in tests, in the Lab, when no API key is configured and when a user's daily model budget
is spent. It never invents: drafts are confirmed fact statements in the first person.
"""

from __future__ import annotations

import re
from typing import Any

from lintel_schemas import VerifierVerdict
from lintel_trust.claimcheck import HeuristicVerifier

from .base import (
    AssessmentOut,
    FactSummary,
    FieldSpec,
    HandleSpec,
    MappingOut,
    RequirementOut,
    ResumeFactOut,
    SentenceOut,
    Usage,
    VariantBulletOut,
)
from .heuristics import first_person, relevance, requirement_lines, tools_in, top_k, years_required

COUNTRY_PATTERNS = [
    (r"\b(united states|u\.s\.a?\.?|usa|us)\b", "US"),
    (r"\b(united kingdom|u\.k\.|uk|britain|england)\b", "UK"),
    (r"\b(canada)\b", "CA"),
    (r"\b(india)\b", "IN"),
    (r"\b(germany)\b", "DE"),
    (r"\b(european union|eu)\b", "EU"),
    (r"\b(singapore)\b", "SG"),
    (r"\b(australia)\b", "AU"),
]

LABEL_RULES: list[tuple[str, str, str]] = [
    # (pattern, handle or special, category)
    (r"\bfirst\s*name\b|\bgiven name\b", "contact.first_name", "contact"),
    (r"\blast\s*name\b|\bsurname\b|\bfamily name\b", "contact.last_name", "contact"),
    (r"^\s*(full\s*)?name\s*\*?$|\byour name\b|\blegal name\b", "contact.full_name", "contact"),
    (r"\be-?mail\b", "contact.email", "contact"),
    (r"\bphone\b|\bmobile\b|\btelephone\b", "contact.phone", "contact"),
    (r"\blinked\s*in\b", "links.linkedin", "contact"),
    (r"\bgit\s*hub\b", "links.github", "contact"),
    (r"\b(portfolio|personal website|website|other website)\b", "links.portfolio", "contact"),
    (r"\b(current|most recent) (company|employer|organization)\b|^\s*company\s*$", "work[0].employer", "contact"),
    (r"\b(current|most recent) (title|role|position)\b", "work[0].title", "contact"),
    (r"\b(school|university|college)\b", "education[0].school", "contact"),
    (r"\bdegree\b", "education[0].degree", "contact"),
    (r"\b(resume|résumé|cv)\b", "document:resume", "document"),
    (r"\bcover letter\b", "cover_letter", "free_text"),
    (r"\b(legally )?authori[sz]ed to work\b|\bwork authori[sz]ation\b|\bright to work\b|\beligible to work\b",
     "eligibility.work_auth", "eligibility"),
    (r"\bsponsor(ship)?\b|\bvisa\b|\bh-?1b\b", "eligibility.sponsorship", "eligibility"),
    (r"\brelocat", "prefs.relocation", "preference"),
    (r"\bnotice period\b", "prefs.notice_period", "preference"),
    (r"\b(salary|compensation|pay) (expectation|requirement|range)s?\b|\bexpected (salary|compensation|ctc)\b|\bdesired (salary|pay)\b",
     "prefs.salary_expectation", "preference"),
    (r"\b(start date|when can you start|earliest start|available to start)\b", "prefs.start_date", "preference"),
    (r"\b(where are you (based|located)|current location|location|city)\b", "contact.location", "contact"),
    (r"\b(remote|in[- ]office|hybrid|onsite|on-site)\b.*\?", "prefs.workplace", "preference"),
    (r"\b(gender|pronouns|race|ethnicity|hispanic|latino|veteran|disability|sexual orientation|transgender)\b",
     "demographic", "demographic"),
    (r"\b(i (agree|acknowledge|consent|confirm|certify)|privacy (notice|policy)|terms|consent)\b", "consent", "consent"),
    (r"\bhow did you (hear|find)\b|\breferr(al|ed)\b", "ask", "unknown"),
]

INTERVIEW_TEMPLATES = [
    (r"\b(production|real users|customers|at scale|scale|traffic|high[- ]availability)\b",
     "Did real users call a service you built? Roughly how many, and over what period? If it was a personal project, say so."),
    (r"\b(lead|led|mentor|manage|ownership|own)\b",
     "Have you led or mentored anyone, or owned a piece of work end to end? Who, how many people, for how long, and in what setting?"),
    (r"\b(test|testing|ci/cd|ci|quality)\b",
     "How have you tested or shipped code you wrote? Name the tools and where you used them: a job, a project or a course."),
    (r"\b(llm|machine learning|ml|ai|model|nlp|rag)\b",
     "What have you built with machine learning or language models? What did it do, who used it, and was it a job, a project or a course?"),
    (r"\b(distributed|microservices|system design|architecture)\b",
     "Have you designed or worked on a system with several services? What did it do, what was your part, and in what setting?"),
]


def _country(label: str, default: str = "US") -> str:
    low = label.lower()
    for pattern, code in COUNTRY_PATTERNS:
        if re.search(pattern, low):
            return code
    return default


class OfflineProvider:
    name = "offline"

    def __init__(self) -> None:
        self._usage: list[Usage] = []

    def last_usage(self) -> list[Usage]:
        u, self._usage = self._usage, []
        return u

    # -- fit -----------------------------------------------------------------

    def extract_requirements(self, title: str, description: str) -> list[RequirementOut]:
        return [RequirementOut(text=t, importance=imp) for t, imp in requirement_lines(description)]

    def assess_requirements(self, requirements: list[RequirementOut], facts: list[FactSummary]) -> list[AssessmentOut]:
        out: list[AssessmentOut] = []
        docs = [(f.id, f"{f.statement} {' '.join(f.skills)}") for f in facts]
        role_facts = [f for f in facts if f.kind == "role"]
        for req in requirements:
            req_tools = tools_in(req.text)
            years = years_required(req.text)
            scored = top_k(req.text, docs, k=3, floor=0.2)
            ids = [i for i, _ in scored]
            best = scored[0][1] if scored else 0.0
            covered_tools: set[str] = set()
            strong_tools: set[str] = set()
            for f in facts:
                if f.id in ids:
                    ft = tools_in(f.statement + " " + " ".join(f.skills))
                    covered_tools |= ft
                    if f.proficiency != "familiar":
                        strong_tools |= ft
            any_of = bool(re.search(r"\bor\b|/|\beither\b", req.text, re.I))
            if req_tools:
                hit = req_tools & covered_tools
                strong_hit = req_tools & strong_tools
                complete = bool(hit) if any_of else not (req_tools - covered_tools)
                complete_strong = bool(strong_hit) if any_of else not (req_tools - strong_tools)
                if complete_strong and ids:
                    status, note = "met", "Named tools appear in confirmed facts."
                elif complete and ids:
                    status, note = "uncertain", "You've listed this as something you're familiar with; the role asks for experience."
                elif hit:
                    status, note = "uncertain", "Some of " + ", ".join(sorted(req_tools)) + " appear in your facts; not all."
                else:
                    status, note = "gap", "No confirmed fact mentions " + ", ".join(sorted(req_tools)) + "."
            elif best >= 0.45:
                status, note = "met", "Confirmed facts describe this."
            elif best >= 0.2:
                status, note = "uncertain", "Related facts exist; the match is loose."
            else:
                status, note = "gap", "No confirmed fact covers this yet."
            if years and status != "gap":
                emp_years = sum(_role_years(f) for f in role_facts)
                if emp_years < years:
                    status = "uncertain" if emp_years >= years / 2 else "gap"
                    note = f"Asks for {years}+ years; your confirmed roles add up to about {emp_years:.1f}."
            q = self.interview_question(req.text, facts) if status != "met" else None
            out.append(AssessmentOut(status=status, evidence_fact_ids=ids if status != "gap" else [], note=note,
                                     interview_question=q))
        return out

    def interview_question(self, requirement: str, facts: list[FactSummary]) -> str:
        low = requirement.lower()
        from lintel_trust.claimcheck.tokens import _tools_in

        raw: list[str] = []
        for t in _tools_in(requirement, case_insensitive=True):
            if t.raw not in raw:
                raw.append(t.raw)
        if raw:
            names = " or ".join(raw[:3]) if re.search(r"\bor\b|/", requirement) else ", ".join(raw[:3])
            return (f"The role asks for: “{requirement}”. Have you used {names}? Where (a job, a project or a "
                    f"course), for roughly how long, and what did you do with it?")
        for pattern, q in INTERVIEW_TEMPLATES:
            if re.search(pattern, low):
                return q
        return (f"The role asks for: “{requirement}”. Is there something you have done that shows this? "
                f"Say where, what you did and roughly how much. “No” is a fine answer.")

    # -- mapping -------------------------------------------------------------

    def map_fields(self, fields: list[FieldSpec], handles: list[HandleSpec]) -> list[MappingOut]:
        available = {h.handle for h in handles}
        out: list[MappingOut] = []
        for f in fields:
            label = f.label.strip()
            low = label.lower()
            decision = None
            for pattern, target, category in LABEL_RULES:
                if not re.search(pattern, low):
                    continue
                if target == "document:resume":
                    if f.type == "file":
                        decision = MappingOut(f.field_key, "handle", "document.resume", "document", "Résumé upload.")
                    else:
                        decision = MappingOut(f.field_key, "skip", None, "document", "Text résumé field; the file is attached.")
                elif target == "cover_letter":
                    if f.type == "file":
                        decision = MappingOut(f.field_key, "skip", None, "document",
                                              "Optional cover letter upload; Lintel drafts text answers only.")
                    else:
                        decision = MappingOut(f.field_key, "draft_needed", None, "free_text", "Cover letter text.")
                elif target in ("eligibility.work_auth", "eligibility.sponsorship"):
                    handle = f"{target}.{_country(label)}"
                    decision = MappingOut(
                        f.field_key, "handle" if handle in available else "ask_user", handle, "eligibility",
                        "Eligibility is never guessed." if handle not in available else "Confirmed eligibility answer.",
                    )
                elif target == "demographic":
                    decision = MappingOut(f.field_key, "ask_user", "demographic", "demographic",
                                          "Voluntary self-identification. Defaults to declining.")
                elif target == "consent":
                    decision = MappingOut(f.field_key, "ask_user", None, "consent", "You tick consents yourself at review.")
                elif target == "ask":
                    decision = MappingOut(f.field_key, "ask_user", None, "unknown", "Only you know this.")
                else:
                    handle = target
                    if handle in available:
                        decision = MappingOut(f.field_key, "handle", handle, category, "Matched by label.")
                    else:
                        decision = MappingOut(f.field_key, "ask_user", handle, category,
                                              "No confirmed fact for this yet.")
                break
            if decision is None:
                if f.type in ("textarea",) or (f.type == "text" and re.search(r"\?|\b(why|describe|tell us|what|how|explain)\b", low)):
                    decision = MappingOut(f.field_key, "draft_needed", None, "free_text", "Open question, drafted from facts.")
                elif not f.required:
                    decision = MappingOut(f.field_key, "skip", None, "unknown", "Optional and not covered by your facts.")
                else:
                    decision = MappingOut(f.field_key, "ask_user", None, "unknown", "Required and only you can answer it.")
            out.append(decision)
        return out

    # -- drafting ------------------------------------------------------------

    def draft_answer(
        self,
        *,
        question: str,
        company: str,
        title: str,
        description: str,
        facts: list[FactSummary],
        max_chars: int | None,
        feedback: list[str] | None = None,
    ) -> list[SentenceOut]:
        usable = [f for f in facts if f.kind in ("role", "achievement", "skill", "education", "certification")]
        reqs = " ".join(r for r, _ in requirement_lines(description)[:8])

        def score(f: FactSummary) -> float:
            text = f.statement + " " + " ".join(f.skills)
            s = 0.65 * relevance(question, text) + 0.35 * relevance(reqs + " " + title, text)
            if f.kind == "skill":
                s *= 0.45
            if f.kind == "achievement":
                s *= 1.15
            return s

        ranked = sorted(usable, key=score, reverse=True)
        chosen: list[FactSummary] = []
        for f in ranked:
            if score(f) <= 0.06 or len(chosen) >= 3:
                break
            if f.kind == "skill" and any(c.kind == "skill" for c in chosen):
                continue
            chosen.append(f)
        if not chosen:
            return []
        sentences: list[SentenceOut] = []
        if re.search(r"\bwhy\b.*\b(join|work|interested|apply|company|us|role)\b|\bmotivat|\binterests? you\b", question.lower()):
            sentences.append(SentenceOut(text=f"I'm applying for the {title} role at {company}.", fact_ids=[]))
        # achievements first, then roles, then a skills line
        order = {"achievement": 0, "role": 1, "education": 2, "certification": 2, "skill": 3}
        for f in sorted(chosen, key=lambda f: order.get(f.kind, 4)):
            sentences.append(SentenceOut(text=_render(f), fact_ids=[f.id]))
        if max_chars:
            while len(" ".join(s.text for s in sentences)) > max_chars and len(sentences) > 1:
                sentences.pop()
        return sentences

    def verify(self, sentence: str, facts: list[FactSummary]) -> tuple[VerifierVerdict, str]:
        from lintel_schemas import ClaimScope, Fact, FactAttributes, FactKind, SourceType

        as_facts = [
            Fact(
                id=f.id,
                kind=FactKind(f.kind),
                claim_scope=ClaimScope(f.claim_scope),
                statement=f.statement,
                attributes=FactAttributes(skills=f.skills, employer=f.employer),
                source_type=SourceType.user_entry,
            )
            for f in facts
        ]
        return HeuristicVerifier().verify(sentence, as_facts)

    def propose_variant(
        self, bullets: list[dict[str, Any]], requirements: list[str], facts: list[FactSummary]
    ) -> list[VariantBulletOut]:
        query = " ".join(requirements)
        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for b in bullets:
            key = b.get("group", "")
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(b)
        out: list[VariantBulletOut] = []
        for key in order:
            ranked = sorted(groups[key], key=lambda b: relevance(query, b["text"]), reverse=True)
            for b in ranked:
                score = relevance(query, b["text"])
                reason = "Moved up: matches the role's requirements." if score > 0.2 else "Kept."
                out.append(VariantBulletOut(bullet_id=b["id"], text=b["text"], reason=reason))
        return out

    # -- ingestion -----------------------------------------------------------

    def extract_resume_facts(self, redacted_text: str) -> list[ResumeFactOut]:
        from ..services.resume_parse import heuristic_facts

        return heuristic_facts(redacted_text)


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _render(f: FactSummary) -> str:
    """A fact as a sentence, adding nothing it doesn't say."""

    if f.kind == "skill" and f.skills:
        if f.proficiency == "familiar":
            return f"I'm familiar with {_join(f.skills)}."
        return f"The tools I list on my résumé include {_join(f.skills)}."
    return first_person(f.statement)


def _role_years(f: FactSummary) -> float:
    from datetime import date

    def parse(d: str | None) -> float | None:
        if not d:
            return None
        if d == "present":
            t = date.today()
            return t.year + (t.month - 1) / 12
        m = re.match(r"(\d{4})(?:-(\d{1,2}))?", d)
        if not m:
            return None
        return int(m.group(1)) + ((int(m.group(2)) - 1) / 12 if m.group(2) else 0)

    start, end = parse(f.start), parse(f.end)
    if start is None:
        return 0.0
    if end is None:
        end = start + 0.5
    return max(0.0, end - start)
