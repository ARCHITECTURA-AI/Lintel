"""Scope check (deterministic).

A sentence that claims employment must cite employment facts. "Familiar with" never becomes
"expert in". Leadership, degrees and certifications need a fact that says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lintel_schemas import ClaimScope, Fact, FactKind

from .lexicon import (
    ASPIRATIONAL,
    CERTIFICATION_PATTERNS,
    EDUCATION_PATTERNS,
    EMPLOYMENT_PATTERNS,
    LEADERSHIP,
    LEVEL_NAMES,
    PROFICIENCY_ATTR,
    PROFICIENCY_PHRASES,
)
from .tokens import normalize_org


@dataclass
class ScopeIssue:
    code: str
    message: str
    offending: list[str]


def _matches(patterns: list[str], text: str) -> list[str]:
    hits = []
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def proficiency_level(text: str) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for pattern, level in PROFICIENCY_PHRASES:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and (best is None or level > best[0]):
            best = (level, m.group(0))
    return best


def _fact_level(fact: Fact) -> int:
    if fact.attributes.proficiency:
        return PROFICIENCY_ATTR[fact.attributes.proficiency]
    found = proficiency_level(fact.statement)
    if found:
        return found[0]
    # A plain record of doing something is working experience, not expertise.
    return 2


def scope_issues(sentence: str, facts: list[Fact], *, employers: list[str] | None = None,
                 other_orgs: list[str] | None = None) -> list[ScopeIssue]:
    issues: list[ScopeIssue] = []
    scopes = {f.claim_scope for f in facts}
    fact_text = " ".join(f.statement for f in facts)

    # 1. Employment claims need employment facts.
    employment_hits = _matches(EMPLOYMENT_PATTERNS, sentence)
    employer_hits: list[str] = []
    for employer in employers or []:
        if employer and re.search(
            r"\b(at|for|with|joined)\s+" + re.escape(employer) + r"(?![\w])", sentence, re.IGNORECASE
        ):
            employer_hits.append(employer)
    # The company being applied to, or any other organization: "At Acme I set up CI" claims a job
    # there unless the sentence is about the future ("I'd like to set up CI at Acme").
    if not re.search(ASPIRATIONAL, sentence, re.IGNORECASE):
        for org in other_orgs or []:
            if org and org not in employer_hits and re.search(
                r"\b(at|for)\s+" + re.escape(org) + r"(?![\w])", sentence, re.IGNORECASE
            ):
                employer_hits.append(org)
    if employment_hits or employer_hits:
        if ClaimScope.employment not in scopes:
            cited = ", ".join(sorted(s.value for s in scopes)) or "nothing"
            issues.append(
                ScopeIssue(
                    "employment_without_employment_fact",
                    f"The sentence describes a job, but it cites {cited}. "
                    "A project or coursework can't be written up as employment.",
                    employment_hits + employer_hits,
                )
            )
        else:
            emp_facts = [f for f in facts if f.claim_scope == ClaimScope.employment]
            for employer in employer_hits:
                if not any(
                    normalize_org(employer) in normalize_org(f.statement + " " + (f.attributes.employer or ""))
                    for f in emp_facts
                ):
                    issues.append(
                        ScopeIssue(
                            "employer_mismatch",
                            f"The sentence places the work at {employer}, but no cited employment fact is at {employer}.",
                            [employer],
                        )
                    )
            # The work itself must have happened there, not just a role cited alongside it.
            work = [f for f in emp_facts if f.kind != FactKind.role and f.attributes.employer]
            named = {normalize_org(e) for e in employer_hits}
            if named and work and not any(normalize_org(f.attributes.employer or "") in named for f in work):
                where = sorted({f.attributes.employer or "" for f in work})
                issues.append(
                    ScopeIssue(
                        "employer_mismatch",
                        f"The sentence places the work at {', '.join(employer_hits)}, but the cited work was done at "
                        f"{', '.join(where)}.",
                        list(employer_hits),
                    )
                )

    # 2. Proficiency never escalates.
    claimed = proficiency_level(sentence)
    if claimed:
        level, phrase = claimed
        cited_level = max((_fact_level(f) for f in facts), default=0)
        if level > cited_level:
            have = LEVEL_NAMES.get(cited_level, "no stated level")
            issues.append(
                ScopeIssue(
                    "proficiency_escalation",
                    f'The sentence says "{phrase}", but the cited facts support at most "{have}".',
                    [phrase],
                )
            )

    # 3. Leadership needs a fact that states it.
    lead = re.search(LEADERSHIP, sentence, re.IGNORECASE)
    if lead and not re.search(LEADERSHIP, fact_text, re.IGNORECASE):
        issues.append(
            ScopeIssue(
                "leadership_unconfirmed",
                f'The sentence claims leadership ("{lead.group(0)}"), and no cited fact says you led or managed anyone.',
                [lead.group(0)],
            )
        )

    # 4. Degrees and certifications need education or certification facts.
    if _matches(EDUCATION_PATTERNS, sentence) and not scopes & {ClaimScope.education, ClaimScope.coursework}:
        issues.append(
            ScopeIssue(
                "education_unconfirmed",
                "The sentence mentions a degree or grades without citing an education fact.",
                _matches(EDUCATION_PATTERNS, sentence),
            )
        )
    if _matches(CERTIFICATION_PATTERNS, sentence) and ClaimScope.certification not in scopes:
        issues.append(
            ScopeIssue(
                "certification_unconfirmed",
                "The sentence claims a certification without citing a certification fact.",
                _matches(CERTIFICATION_PATTERNS, sentence),
            )
        )

    # 5. A project fact cited for a sentence that hides the project framing.
    if (
        scopes
        and scopes <= {ClaimScope.project, ClaimScope.coursework}
        and re.search(r"\b(clients?|customers?|employer|company's|production traffic|paying users)\b", sentence, re.IGNORECASE)
        and not re.search(r"\b(clients?|customers?|employer|production|paying)\b", fact_text, re.IGNORECASE)
    ):
        issues.append(
            ScopeIssue(
                "project_inflated",
                "The sentence describes commercial use that the cited project facts don't mention.",
                [],
            )
        )
    return issues
