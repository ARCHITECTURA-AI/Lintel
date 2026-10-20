"""Verifier pass (model).

A separate prompt sees only the sentence and its cited facts and returns supported, overreach or
unsupported. The Verifier protocol lets the API plug in a model; HeuristicVerifier is the
offline fallback used in tests, in the Lab and when no model key is configured.
"""

from __future__ import annotations

import re
from typing import Protocol

from lintel_schemas import Fact, VerifierVerdict

from .lexicon import GENERIC_WORDS, OVERREACH_WORDS, STOPWORDS
from .tokens import _norm_word

_CLAIM_PATTERNS = [
    r"\bI (have|had|was|am|built|led|created|designed|developed|shipped|wrote|ran|launched|reduced|improved|increased|grew|owned|implemented|deployed|maintained|scaled|delivered|won|published|taught|automated|migrated)\b",
    r"\bI've\b",
    r"\bmy (experience|work|project|research|background|role|thesis|internship)\b",
]


class Verifier(Protocol):
    def verify(self, sentence: str, facts: list[Fact]) -> tuple[VerifierVerdict, str]: ...


def _stem(word: str) -> str:
    w = _norm_word(word)
    for suffix in ("ing", "ed", "ly", "er", "ment", "tion"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def content_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#'-]*", text)
    out = []
    for w in words:
        lw = w.lower()
        if len(lw) < 3 or lw in STOPWORDS or lw in GENERIC_WORDS:
            continue
        out.append(lw)
    return out


class HeuristicVerifier:
    """Lexical-overlap verifier. Conservative: it prefers a false 'unsupported' to a false pass."""

    def __init__(self, coverage_threshold: float = 0.6, context_terms: list[str] | None = None):
        self.coverage_threshold = coverage_threshold
        self.context = {_stem(w) for t in (context_terms or []) for w in re.findall(r"[A-Za-z0-9+#]+", t)}

    def verify(self, sentence: str, facts: list[Fact]) -> tuple[VerifierVerdict, str]:
        fact_text = " ".join(
            [f.statement for f in facts]
            + [" ".join(str(v) for v in f.attributes.model_dump(exclude_none=True).values()) for f in facts]
        )
        fact_stems = {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z0-9+#'-]*", fact_text)}
        lower = sentence.lower()

        for word in OVERREACH_WORDS:
            if re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", lower) and _stem(word) not in fact_stems:
                return VerifierVerdict.overreach, f'"{word}" goes beyond what the cited facts say.'

        words = [w for w in content_words(sentence) if _stem(w) not in self.context]
        is_claim = any(re.search(p, sentence, re.IGNORECASE) for p in _CLAIM_PATTERNS)
        if not facts:
            if is_claim:
                return VerifierVerdict.unsupported, "The sentence makes a claim about you but cites no facts."
            if words and len(words) > 6:
                return VerifierVerdict.unsupported, "The sentence carries specifics but cites no facts."
            return VerifierVerdict.supported, "Connective sentence with no factual claim."
        if not words:
            return VerifierVerdict.supported, "No specific content beyond the cited facts."
        covered = [w for w in words if _stem(w) in fact_stems]
        coverage = len(covered) / len(words)
        if coverage >= self.coverage_threshold:
            return VerifierVerdict.supported, f"{len(covered)} of {len(words)} specific words trace to the cited facts."
        missing = [w for w in words if _stem(w) not in fact_stems][:5]
        return (
            VerifierVerdict.unsupported,
            "Words with no source in the cited facts: " + ", ".join(missing) + ".",
        )
