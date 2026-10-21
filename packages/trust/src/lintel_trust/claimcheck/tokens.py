"""Token check (deterministic).

Every number, date, employer, tool name, quantity and unrecognized proper name in a sentence
must appear in a cited fact after normalization. This catches the most common fabrication
class without trusting a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lintel_schemas import Fact

from .lexicon import (
    AMBIGUOUS_ALIASES,
    CASE_SENSITIVE_TOOLS,
    COMMON_CAPITALIZED,
    MAX_TOOL_WORDS,
    MONTHS,
    NUMBER_WORDS,
    ONE_UNITS,
    TOOLS,
    VAGUE_MAGNITUDES,
)

_CASE_ONLY = set(CASE_SENSITIVE_TOOLS.values())


@dataclass(frozen=True)
class Token:
    kind: str  # number | month | org | tool | name | magnitude
    raw: str
    norm: str


@dataclass
class FactIndex:
    numbers: set[float] = field(default_factory=set)
    months: set[int] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    words: set[str] = field(default_factory=set)
    text: str = ""


_NUM_RE = re.compile(
    r"(?<![\w.])([$£€₹])?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|bn|b|million|thousand|billion|lakh|crore)?(?![\w])(\s*%|\s*percent)?",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[.'/&-][A-Za-z0-9+#]+)*\+*")
_SENTENCE_START_RE = re.compile(r"(^|[.!?:;]\s+|\n\s*|[\"“(]\s*)$")
_MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000, "b": 1_000_000_000,
    "bn": 1_000_000_000, "billion": 1_000_000_000, "lakh": 100_000, "crore": 10_000_000,
}


def _norm_word(word: str) -> str:
    w = word.lower().strip(".'’")
    if w.endswith("'s"):
        w = w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


def normalize_org(name: str) -> str:
    n = name.lower()
    n = re.sub(r"[,.]?\s+(inc|ltd|llc|corp|corporation|limited|pvt|gmbh|co)\.?$", "", n)
    n = re.sub(r"[^a-z0-9+#& ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _numbers_in(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).strip()
        num = float(m.group(2).replace(",", ""))
        mult = (m.group(3) or "").lower()
        num *= _MULTIPLIERS.get(mult, 1)
        out.append((raw, num))
    words = re.findall(r"[A-Za-z]+", text)
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in NUMBER_WORDS:
            out.append((w, float(NUMBER_WORDS[lw])))
        elif lw == "one" and i + 1 < len(words) and words[i + 1].lower() in ONE_UNITS:
            out.append((w, 1.0))
    return out


def _is_sentence_initial(text: str, start: int) -> bool:
    return bool(_SENTENCE_START_RE.search(text[:start]))


def build_fact_index(facts: list[Fact]) -> FactIndex:
    parts: list[str] = []
    idx = FactIndex()
    for f in facts:
        parts.append(f.statement)
        attrs = f.attributes.model_dump(exclude_none=True)
        for key, val in attrs.items():
            if key == "parent_fact_id":
                continue
            if isinstance(val, list):
                parts.extend(str(v) for v in val)
            elif isinstance(val, str):
                parts.append(val)
                if key in ("start", "end"):
                    m = re.match(r"(\d{4})-(\d{1,2})", val)
                    if m:
                        idx.months.add(int(m.group(2)))
                        idx.numbers.add(float(m.group(1)))
    text = "\n".join(parts)
    idx.text = text
    for _, num in _numbers_in(text):
        idx.numbers.add(num)
    lowered = text.lower()
    for word in re.findall(r"[a-z]+", lowered):
        if word in MONTHS:
            idx.months.add(MONTHS[word])
    # every tool mentioned in any form, regardless of case
    for tool in _tools_in(text, case_insensitive=True):
        idx.tools.add(tool.norm)
    for w in _WORD_RE.findall(text):
        idx.words.add(_norm_word(w))
        for piece in re.split(r"[./&-]", w):
            if piece:
                idx.words.add(_norm_word(piece))
    return idx


def _tools_in(text: str, *, case_insensitive: bool = False) -> list[Token]:
    found: list[Token] = []
    matches = list(_WORD_RE.finditer(text))
    words = [m.group(0) for m in matches]
    i = 0
    while i < len(words):
        matched = False
        for n in range(min(MAX_TOOL_WORDS, len(words) - i), 0, -1):
            phrase_raw = " ".join(words[i : i + n])
            phrase = phrase_raw.lower().rstrip(".")
            if phrase in TOOLS:
                if n == 1 and phrase in _CASE_ONLY and not case_insensitive:
                    continue
                if (
                    n == 1
                    and phrase in AMBIGUOUS_ALIASES
                    and not case_insensitive
                    and not (phrase_raw[:1].isupper())
                ):
                    continue
                found.append(Token("tool", phrase_raw, TOOLS[phrase]))
                i += n
                matched = True
                break
        if matched:
            continue
        w = words[i]
        if w in CASE_SENSITIVE_TOOLS and (case_insensitive or not _is_sentence_initial(text, matches[i].start())):
            # "Go" mid-sentence is the language; at the start of a sentence it is a verb
            if w not in ("R", "C") or case_insensitive:
                found.append(Token("tool", w, CASE_SENSITIVE_TOOLS[w]))
        elif case_insensitive and w.lower() in {k.lower() for k in CASE_SENSITIVE_TOOLS}:
            found.append(Token("tool", w, w.lower()))
        i += 1
    return found


def extract_tokens(
    sentence: str,
    *,
    known_orgs: list[str] | None = None,
    context_terms: list[str] | None = None,
) -> list[Token]:
    """Pull every checkable token out of a sentence.

    known_orgs: organizations Lintel knows about (from the ledger and a lexicon).
    context_terms: words that may appear without a citation, such as the target company and role.
    """

    tokens: list[Token] = []
    covered: list[tuple[int, int]] = []

    def _cover(start: int, end: int) -> None:
        covered.append((start, end))

    def _is_covered(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in covered)

    context_words = set()
    for term in context_terms or []:
        for w in _WORD_RE.findall(term):
            context_words.add(_norm_word(w))

    # organizations
    for org in sorted(known_orgs or [], key=len, reverse=True):
        norm = normalize_org(org)
        if not norm or len(norm) < 2:
            continue
        pattern = re.compile(r"(?<![\w])" + re.escape(org.strip()) + r"(?![\w])", re.IGNORECASE)
        for m in pattern.finditer(sentence):
            if _is_covered(m.start(), m.end()):
                continue
            if all(_norm_word(w) in context_words for w in _WORD_RE.findall(m.group(0))):
                _cover(m.start(), m.end())
                continue
            tokens.append(Token("org", m.group(0), norm))
            _cover(m.start(), m.end())

    # numbers and quantities
    for raw, num in _numbers_in(sentence):
        tokens.append(Token("number", raw, _fmt_num(num)))
    for m in re.finditer(r"\b(dozens|hundreds|thousands|millions|billions)\b", sentence, re.IGNORECASE):
        tokens.append(Token("magnitude", m.group(0), m.group(1).lower()))

    # months
    for m in re.finditer(r"\b([A-Za-z]+)\.?\s*(\d{4})?\b", sentence):
        word = m.group(1)
        lw = word.lower()
        if lw not in MONTHS:
            continue
        if lw in ("may", "mar", "jan", "dec", "sep", "oct", "nov", "aug", "apr", "jun", "jul", "feb", "sept"):
            # short or ambiguous forms count only next to a year
            if not m.group(2):
                continue
        if not word[0].isupper():
            continue
        tokens.append(Token("month", word, str(MONTHS[lw])))

    # tools
    for t in _tools_in(sentence):
        tokens.append(t)
        for m in re.finditer(re.escape(t.raw), sentence):
            _cover(m.start(), m.end())

    # unrecognized proper names and acronyms
    tool_raw = {t.raw.lower() for t in tokens if t.kind == "tool"}
    for m in _WORD_RE.finditer(sentence):
        w = m.group(0)
        if _is_covered(m.start(), m.end()):
            continue
        if not (w[0].isupper() or (len(w) >= 2 and w.isupper())):
            continue
        if _is_sentence_initial(sentence, m.start()) and not w.isupper():
            continue
        lw = w.lower()
        if lw in COMMON_CAPITALIZED or lw in MONTHS or lw in tool_raw or lw in NUMBER_WORDS:
            continue
        if _norm_word(w) in context_words:
            continue
        tokens.append(Token("name", w, _norm_word(w)))
    return tokens


def _fmt_num(num: float) -> str:
    return str(int(num)) if float(num).is_integer() else f"{num:g}"


def token_supported(token: Token, index: FactIndex) -> bool:
    if token.kind == "number":
        return float(token.norm) in index.numbers
    if token.kind == "magnitude":
        lo, hi = VAGUE_MAGNITUDES[token.norm]
        return any(lo <= n <= hi for n in index.numbers) or token.norm in index.text.lower()
    if token.kind == "month":
        return int(token.norm) in index.months
    if token.kind == "tool":
        return token.norm in index.tools or _norm_word(token.norm) in index.words
    if token.kind == "org":
        return token.norm in normalize_org(index.text) or all(
            _norm_word(w) in index.words for w in token.norm.split()
        )
    if token.kind == "name":
        return token.norm in index.words
    return False


def unsupported_tokens(
    sentence: str,
    facts: list[Fact],
    *,
    known_orgs: list[str] | None = None,
    context_terms: list[str] | None = None,
) -> list[Token]:
    index = build_fact_index(facts)
    return [
        t
        for t in extract_tokens(sentence, known_orgs=known_orgs, context_terms=context_terms)
        if not token_supported(t, index)
    ]
