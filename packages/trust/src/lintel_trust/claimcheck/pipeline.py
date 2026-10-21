"""The claim check: token check, scope check, verifier pass. In this order, each fails closed."""

from __future__ import annotations

import re
from collections.abc import Iterable

from lintel_schemas import CheckOutcome, CheckResult, Fact, SentenceCheck, VerifierVerdict

from .lexicon import WELL_KNOWN_ORGS
from .scope import scope_issues
from .tokens import unsupported_tokens
from .verifier import HeuristicVerifier, Verifier

_KIND_LABEL = {
    "number": "number",
    "magnitude": "quantity",
    "month": "date",
    "org": "organization",
    "tool": "tool",
    "name": "name",
}


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])|\n{2,}|\n(?=[-•*]\s)", text)
    return [p.strip() for p in parts if p.strip()]


def known_orgs_from(facts: Iterable[Fact], extra: Iterable[str] = ()) -> list[str]:
    orgs: set[str] = set(WELL_KNOWN_ORGS)
    for f in facts:
        for attr in (f.attributes.employer, f.attributes.school, f.attributes.issuer):
            if attr:
                orgs.add(attr)
    orgs.update(e for e in extra if e)
    return sorted(orgs)


def check_sentence(
    sentence: str,
    cited: list[Fact],
    *,
    all_facts: list[Fact] | None = None,
    context_terms: list[str] | None = None,
    verifier: Verifier | None = None,
) -> SentenceCheck:
    """Run the three checks on one sentence against the facts it cites."""

    all_facts = all_facts if all_facts is not None else cited
    context_terms = context_terms or []
    checks: list[CheckResult] = []

    # 1. Token check
    missing = unsupported_tokens(
        sentence,
        cited,
        known_orgs=known_orgs_from(all_facts, context_terms),
        context_terms=context_terms,
    )
    if missing:
        listed = ", ".join(f'{_KIND_LABEL[t.kind]} "{t.raw}"' for t in missing)
        checks.append(
            CheckResult(
                name="token",
                outcome=CheckOutcome.failed,
                detail=f"Not found in any cited fact: {listed}.",
                offending=[t.raw for t in missing],
            )
        )
        checks.append(CheckResult(name="scope", outcome=CheckOutcome.skipped))
        checks.append(CheckResult(name="verifier", outcome=CheckOutcome.skipped))
        return SentenceCheck(passed=False, checks=checks)
    checks.append(CheckResult(name="token", outcome=CheckOutcome.passed, detail="Every specific traces to a cited fact."))

    # 2. Scope check
    employers = sorted({f.attributes.employer for f in all_facts if f.attributes.employer})
    issues = scope_issues(sentence, cited, employers=employers, other_orgs=context_terms)
    if issues:
        checks.append(
            CheckResult(
                name="scope",
                outcome=CheckOutcome.failed,
                detail=" ".join(i.message for i in issues),
                offending=[o for i in issues for o in i.offending],
            )
        )
        checks.append(CheckResult(name="verifier", outcome=CheckOutcome.skipped))
        return SentenceCheck(passed=False, checks=checks)
    checks.append(CheckResult(name="scope", outcome=CheckOutcome.passed, detail="Claim types match the cited facts."))

    # 3. Verifier pass
    v = verifier or HeuristicVerifier(context_terms=context_terms)
    try:
        verdict, reason = v.verify(sentence, cited)
    except Exception as exc:  # the verifier fails closed
        verdict, reason = VerifierVerdict.unsupported, f"Verifier unavailable ({type(exc).__name__}); failing closed."
    checks.append(
        CheckResult(
            name="verifier",
            outcome=CheckOutcome.passed if verdict == VerifierVerdict.supported else CheckOutcome.failed,
            detail=reason,
            verdict=verdict,
        )
    )
    return SentenceCheck(passed=verdict == VerifierVerdict.supported, checks=checks)
