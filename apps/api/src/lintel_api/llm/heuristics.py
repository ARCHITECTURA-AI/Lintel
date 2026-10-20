"""Deterministic text helpers shared by the offline provider and the services."""

from __future__ import annotations

import re
from collections.abc import Iterable

from lintel_trust.claimcheck.lexicon import GENERIC_WORDS, STOPWORDS, TOOLS
from lintel_trust.claimcheck.tokens import _tools_in

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")

REQUIREMENT_HEADINGS = re.compile(
    r"^\s*(requirements|qualifications|what you('|’)ll need|what we('|’)re looking for|you have|you will have|"
    r"must[- ]haves?|minimum qualifications|basic qualifications|about you|who you are|skills|"
    r"what you bring|you might be a fit if)\b",
    re.IGNORECASE,
)
NICE_HEADINGS = re.compile(
    r"^\s*(nice[- ]to[- ]haves?|bonus( points)?|preferred( qualifications)?|plus(es)?|"
    r"it('|’)s a plus|extra credit|good to have)\b",
    re.IGNORECASE,
)
OTHER_HEADINGS = re.compile(
    r"^\s*(about (us|the role|the team)|responsibilities|what you('|’)ll do|benefits|perks|"
    r"compensation|our values|why join|the role|how to apply|equal opportunity|location)\b",
    re.IGNORECASE,
)
BULLET = re.compile(r"^\s*([-•*·▪●◦]|\d+[.)])\s+")


def html_to_text(html: str) -> str:
    import html as htmllib

    text = htmllib.unescape(html or "")
    text = htmllib.unescape(text)  # Greenhouse double-escapes content
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = re.sub(r"(?i)</\s*(p|div|h[1-6]|ul|ol|li|section)\s*>", "\n", text)
    text = re.sub(r"(?i)<\s*h[1-6][^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def words(text: str) -> list[str]:
    return [w.lower().rstrip(".") for w in _WORD.findall(text or "")]


def stem(w: str) -> str:
    w = w.lower()
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def content_set(text: str) -> set[str]:
    return {
        stem(w)
        for w in words(text)
        if len(w) > 2 and w not in STOPWORDS and w not in GENERIC_WORDS and w not in {"year", "years", "plus"}
    }


def tools_in(text: str) -> set[str]:
    return {t.norm for t in _tools_in(text or "", case_insensitive=True)}


def relevance(query: str, doc: str) -> float:
    """Overlap score in [0, 1] weighting named tools above ordinary words."""

    qt, dt = tools_in(query), tools_in(doc)
    qc, dc = content_set(query), content_set(doc)
    tool_score = len(qt & dt) / len(qt) if qt else 0.0
    word_score = len(qc & dc) / max(4, len(qc)) if qc else 0.0
    if qt:
        return 0.7 * tool_score + 0.3 * min(1.0, word_score)
    return min(1.0, word_score)


def top_k(query: str, items: Iterable[tuple[str, str]], k: int, floor: float = 0.05) -> list[tuple[str, float]]:
    scored = [(item_id, relevance(query, text)) for item_id, text in items]
    scored = [s for s in scored if s[1] >= floor]
    scored.sort(key=lambda s: s[1], reverse=True)
    return scored[:k]


def requirement_lines(description: str) -> list[tuple[str, str]]:
    """Pull (text, importance) requirement lines out of a job description."""

    text = description if "<" not in description else html_to_text(description)
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[tuple[str, str]] = []
    mode: str | None = None
    for ln in lines:
        if not ln:
            continue
        bare = BULLET.sub("", ln).strip().rstrip(":")
        is_heading = len(bare) < 70 and not BULLET.match(ln) and (ln.endswith(":") or len(bare.split()) <= 6)
        if is_heading and NICE_HEADINGS.match(bare):
            mode = "nice"
            continue
        if is_heading and REQUIREMENT_HEADINGS.match(bare):
            mode = "must"
            continue
        if is_heading and OTHER_HEADINGS.match(bare):
            mode = None
            continue
        if mode and 12 <= len(bare) <= 240:
            out.append((bare, mode))
    if not out:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            s = BULLET.sub("", sentence).strip()
            if re.search(r"\b(experience|years|proficien|familiar|knowledge of|degree|ability to)\b", s, re.I) and 15 <= len(s) <= 240:
                out.append((s, "nice" if re.search(r"\b(plus|bonus|nice|preferred)\b", s, re.I) else "must"))
    seen: set[str] = set()
    unique = []
    for t, imp in out:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append((t, imp))
    return unique[:14]


def years_required(text: str) -> int | None:
    m = re.search(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?", text, re.I)
    return int(m.group(1)) if m else None


def known_tool(name: str) -> str | None:
    return TOOLS.get(name.lower())


_PAST = {"Built", "Led", "Wrote", "Ran", "Made", "Taught", "Won", "Shipped", "Held", "Grew", "Drove", "Took", "Set", "Cut", "Put"}


def _verb_first(text: str) -> str | None:
    first = text.split()[0] if text.split() else ""
    if re.match(r"^[A-Z][a-z]+ed$", first) or first in _PAST:
        return "I " + text[0].lower() + text[1:]
    return None


def first_person(statement: str) -> str:
    """Turn a confirmed fact statement into a first-person sentence without adding anything."""

    s = statement.strip().rstrip(".")
    if not s:
        return s
    s = re.sub(r"\s*\(at ([^)]+)\)$", r" at \1", s)
    if re.match(r"^(I|I'm|I've|My)\b", s):
        return s + "."
    m = re.match(r"^(Personal project|Course project|Side project|Coursework|Project)(?:\s*\(([^)]+)\))?\s*:\s*(.+)$", s, re.I)
    if m:
        kind, name, rest = m.group(1).lower(), m.group(2), m.group(3)
        where = f"In a {kind}" + (f" ({name})" if name else "")
        verbed = _verb_first(rest)
        if verbed:
            return f"{where}, {verbed}."
        return f"One {kind} of mine" + (f" ({name})" if name else "") + f": {rest}."
    verbed = _verb_first(s)
    if verbed:
        return verbed + "."
    if re.match(r"^(Familiar|Experienced|Proficient|Comfortable|Skilled) (with|in)\b", s):
        return "I am " + s[0].lower() + s[1:].replace(":", "") + "."
    return s + "."
