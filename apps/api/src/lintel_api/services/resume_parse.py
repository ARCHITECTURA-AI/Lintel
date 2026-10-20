"""Résumé ingestion: text extraction, contact redaction and a structural parse.

Contact details are pulled out locally with patterns and become contact facts directly; the
text a model may see has them replaced with placeholders.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import ResumeFactOut

SECTION_ALIASES = {
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history",
                   "work history", "internships", "internship experience", "relevant experience"],
    "projects": ["projects", "personal projects", "selected projects", "side projects", "academic projects",
                 "open source", "open-source"],
    "education": ["education", "academics", "academic background"],
    "skills": ["skills", "technical skills", "technologies", "tech stack", "tools", "core skills"],
    "certifications": ["certifications", "certificates", "licenses", "licenses & certifications"],
    "summary": ["summary", "profile", "about", "about me", "objective"],
    "awards": ["awards", "achievements", "honors", "honours", "awards & achievements"],
}
_HEADING_LOOKUP = {alias: key for key, aliases in SECTION_ALIASES.items() for alias in aliases}

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE = rf"(?:{MONTH}\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
RANGE = re.compile(rf"({DATE})\s*(?:–|—|-|to)\s*({DATE}|Present|Current|Now|Ongoing)", re.IGNORECASE)
SINGLE_DATE = re.compile(rf"\b({DATE})\b", re.IGNORECASE)
BULLET = re.compile(r"^\s*([-•*·▪●◦‣➢>]|\d+[.)])\s+")
TITLE_WORDS = re.compile(
    r"\b(engineer|developer|intern|analyst|scientist|manager|lead|designer|researcher|consultant|associate|"
    r"architect|sre|devops|founder|co-founder|assistant|fellow|programmer|specialist|administrator|director|"
    r"head|officer|technician|trainee|apprentice|contributor|member|volunteer|tutor|teaching)\b",
    re.IGNORECASE,
)
DEGREE_WORDS = re.compile(
    r"\b(b\.?\s?tech|m\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc|m\.?\s?sc|bachelor|master|ph\.?\s?d|mba|b\.?\s?a\.?|m\.?\s?s\.?|"
    r"b\.?\s?s\.?|diploma|associate degree|high school|secondary|bca|mca)\b",
    re.IGNORECASE,
)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL = re.compile(r"(?:https?://)?(?:www\.)?(linkedin\.com/in/[\w-]+|github\.com/[\w-]+|[\w-]+\.(?:dev|io|me|com|net|org)(?:/[\w./-]*)?)", re.I)

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def extract_text(data: bytes, content_type: str, filename: str) -> str:
    name = filename.lower()
    if content_type == "application/pdf" or name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n".join(pages)
    if name.endswith(".docx") or "wordprocessingml" in content_type:
        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    return data.decode("utf-8", errors="replace")


@dataclass
class Contacts:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    location: str | None = None


def redact(text: str) -> tuple[str, Contacts]:
    """Remove contact details. Returns the redacted text and what was found."""

    c = Contacts()
    lines = [ln.strip() for ln in text.splitlines()]
    for ln in lines[:4]:
        if ln and not EMAIL.search(ln) and not PHONE.search(ln) and 1 < len(ln.split()) <= 5 and not _heading(ln):
            if re.match(r"^[A-Za-z][A-Za-z .'-]+$", ln):
                c.full_name = ln.title() if ln.isupper() else ln
                break
    for ln in lines[1:4]:
        first = ln.split("|")[0].strip()
        if first and "," in first and not EMAIL.search(first) and not re.search(r"\d", first) and len(first) < 60:
            c.location = first
            break
    m = EMAIL.search(text)
    if m:
        c.email = m.group(0)
    for m in PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if 9 <= len(digits) <= 15 and not re.fullmatch(r"(19|20)\d{2}(19|20)\d{2}", digits):
            c.phone = m.group(1).strip()
            break
    for m in URL.finditer(text):
        u = m.group(1)
        if "linkedin.com" in u.lower():
            c.links["linkedin"] = "https://www." + u if not u.startswith("http") else u
        elif "github.com" in u.lower():
            c.links["github"] = "https://" + u if not u.startswith("http") else u
        elif "@" not in u and not EMAIL.search(u) and "portfolio" not in c.links and "." in u and "/" in u:
            c.links["portfolio"] = "https://" + u if not u.startswith("http") else u
    red = text
    if c.full_name:
        red = red.replace(c.full_name, "[NAME]")
    red = EMAIL.sub("[EMAIL]", red)
    if c.phone:
        red = red.replace(c.phone, "[PHONE]")
    for u in c.links.values():
        red = red.replace(u.replace("https://www.", "").replace("https://", ""), "[LINK]")
    return red, c


def _heading(line: str) -> str | None:
    bare = re.sub(r"[:\-–—_=*#|]+$", "", line.strip()).strip().lower()
    bare = re.sub(r"\s+", " ", bare)
    return _HEADING_LOOKUP.get(bare)


def _norm_date(d: str | None) -> str | None:
    if not d:
        return None
    s = d.strip().lower()
    if s in ("present", "current", "now", "ongoing"):
        return "present"
    m = re.match(r"([a-z]+)\.?\s+(\d{4})", s)
    if m and m.group(1)[:3] in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1)[:3]]:02d}"
    m = re.match(r"(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})", s)
    return m.group(1) if m else None


@dataclass
class Entry:
    header: str
    header_line: int
    bullets: list[tuple[int, str]] = field(default_factory=list)
    extra_header: list[str] = field(default_factory=list)


def parse_structure(text: str) -> dict[str, Any]:
    """Sections, entries and bullets with stable ids, for facts and résumé variants."""

    sections: dict[str, list[Entry]] = {}
    section_order: list[str] = []
    current: str | None = None
    entry: Entry | None = None
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        h = _heading(line)
        if h:
            current = h
            if h not in sections:
                sections[h] = []
                section_order.append(h)
            entry = None
            continue
        if current is None:
            continue
        if BULLET.match(line):
            if entry is None:
                entry = Entry(header="", header_line=i)
                sections[current].append(entry)
            entry.bullets.append((i, BULLET.sub("", line).strip()))
        elif entry is not None and entry.bullets and raw.startswith(("  ", "\t")) and not RANGE.search(line):
            # wrapped bullet continuation
            ln, prev = entry.bullets[-1]
            entry.bullets[-1] = (ln, prev + " " + line)
        elif entry is not None and not entry.bullets and current in ("experience", "projects", "education"):
            entry.extra_header.append(line)
        else:
            entry = Entry(header=line, header_line=i)
            sections[current].append(entry)

    out_sections = []
    for name in section_order:
        entries = []
        for e_idx, e in enumerate(sections[name]):
            entries.append(
                {
                    "header": e.header,
                    "extra": e.extra_header,
                    "line": e.header_line,
                    "bullets": [
                        {"id": f"{name[:3]}-{e_idx}-{b_idx}", "text": t, "line": ln}
                        for b_idx, (ln, t) in enumerate(e.bullets)
                    ],
                }
            )
        out_sections.append({"name": name, "entries": entries})
    return {"sections": out_sections}


def _split_header(header: str, extra: list[str]) -> dict[str, str | None]:
    full = " ".join([header, *extra])
    rng = RANGE.search(full)
    start = end = None
    if rng:
        start, end = _norm_date(rng.group(1)), _norm_date(rng.group(2))
        full = (full[: rng.start()] + full[rng.end():]).strip()
    else:
        sd = SINGLE_DATE.search(full)
        if sd:
            start = end = _norm_date(sd.group(1))
            full = (full[: sd.start()] + full[sd.end():]).strip()
    full = re.sub(r"[()]", " ", full)
    parts = [p.strip(" ,|-–—") for p in re.split(r"\s+[|–—@]\s+|\s+-\s+|\s{2,}|,\s+|\s+at\s+", full) if p.strip(" ,|-–—")]
    title = next((p for p in parts if TITLE_WORDS.search(p)), None)
    others = [p for p in parts if p != title]
    org = others[0] if others else None
    location = others[1] if len(others) > 1 else None
    return {"title": title, "org": org, "location": location, "start": start, "end": end}


def _readable_range(start: str | None, end: str | None) -> str:
    def fmt(d: str | None) -> str:
        if not d:
            return ""
        if d == "present":
            return "present"
        m = re.match(r"(\d{4})-(\d{2})", d)
        if m:
            name = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                    "October", "November", "December"][int(m.group(2)) - 1]
            return f"{name} {m.group(1)}"
        return d

    if start and end and start != end:
        return f"{fmt(start)} to {fmt(end)}"
    return fmt(start or end)


def heuristic_facts(text: str) -> list[ResumeFactOut]:
    structure = parse_structure(text)
    facts: list[ResumeFactOut] = []
    for section in structure["sections"]:
        name = section["name"]
        for entry in section["entries"]:
            hdr = _split_header(entry["header"], entry["extra"]) if entry["header"] else {}
            ref = f"résumé line {entry['line']}"
            if name == "experience" and entry["header"]:
                title, org = hdr.get("title"), hdr.get("org")
                if title or org:
                    when = _readable_range(hdr.get("start"), hdr.get("end"))
                    statement = f"{title or 'Role'} at {org or 'unknown employer'}" + (f", {when}" if when else "")
                    facts.append(
                        ResumeFactOut(
                            kind="role",
                            claim_scope="employment",
                            statement=statement,
                            attributes={k: v for k, v in {
                                "employer": org, "title": title, "start": hdr.get("start"), "end": hdr.get("end"),
                                "location": hdr.get("location"),
                            }.items() if v},
                            source_ref=ref,
                        )
                    )
                for b in entry["bullets"]:
                    facts.append(
                        ResumeFactOut(
                            kind="achievement",
                            claim_scope="employment",
                            statement=b["text"].rstrip(".") + (f" (at {org})" if org and org.lower() not in b["text"].lower() else "") + ".",
                            attributes={"employer": org, "bullet_id": b["id"]} if org else {"bullet_id": b["id"]},
                            source_ref=f"résumé line {b['line']}",
                        )
                    )
            elif name == "projects":
                pname = (hdr.get("org") or hdr.get("title") or entry["header"] or "").strip()
                if entry["header"] and not entry["bullets"]:
                    facts.append(ResumeFactOut("achievement", "project", f"Personal project: {entry['header'].rstrip('.')}.",
                                               {"project": pname}, ref))
                for b in entry["bullets"]:
                    prefix = f"Personal project ({pname})" if pname else "Personal project"
                    facts.append(
                        ResumeFactOut("achievement", "project", f"{prefix}: {b['text'].rstrip('.')}.",
                                      {"project": pname, "bullet_id": b["id"]}, f"résumé line {b['line']}")
                    )
            elif name == "education":
                line = " ".join([entry["header"], *entry["extra"]]).strip()
                if not line:
                    continue
                degree = DEGREE_WORDS.search(line)
                school = None
                for part in re.split(r"\s+[|–—]\s+|,\s+|\s{2,}", RANGE.sub("", line)):
                    if re.search(r"\b(university|college|institute|school|iit|bits|nit|academy)\b", part, re.I):
                        school = part.strip()
                        break
                facts.append(
                    ResumeFactOut(
                        "education", "education", line.rstrip(".") + ".",
                        {k: v for k, v in {"school": school, "degree": degree.group(0) if degree else None,
                                            "start": hdr.get("start"), "end": hdr.get("end")}.items() if v},
                        ref,
                    )
                )
                for b in entry["bullets"]:
                    facts.append(ResumeFactOut("achievement", "coursework", b["text"].rstrip(".") + ".",
                                               {"school": school, "bullet_id": b["id"]} if school else {"bullet_id": b["id"]},
                                               f"résumé line {b['line']}"))
            elif name == "skills":
                lines = [entry["header"], *[b["text"] for b in entry["bullets"]], *entry["extra"]]
                for ln in lines:
                    if not ln:
                        continue
                    label, _, items = ln.partition(":")
                    items = items if items else label
                    skills = [s.strip(" .") for s in re.split(r",|;|\|", items) if s.strip(" .")]
                    if not skills:
                        continue
                    group = label.strip() if items is not label else "Skills"
                    attrs: dict[str, Any] = {"skills": skills}
                    if re.search(r"\b(familiar|exposure|basic|learning|beginner)\b", group, re.I):
                        attrs["proficiency"] = "familiar"
                    facts.append(ResumeFactOut("skill", "personal", f"{group}: {', '.join(skills)}.", attrs, ref))
            elif name == "certifications":
                for ln in [entry["header"], *[b["text"] for b in entry["bullets"]]]:
                    if ln:
                        facts.append(ResumeFactOut("certification", "certification", ln.rstrip(".") + ".", {}, ref))
            elif name == "awards":
                for ln in [entry["header"], *[b["text"] for b in entry["bullets"]]]:
                    if ln:
                        facts.append(ResumeFactOut("achievement", "personal", ln.rstrip(".") + ".", {}, ref))
    return facts


def contact_facts(c: Contacts) -> list[ResumeFactOut]:
    out = []
    if c.full_name:
        out.append(ResumeFactOut("contact", "personal", f"My name is {c.full_name}.", {"field": "full_name", "value": c.full_name}, "résumé header"))
    if c.email:
        out.append(ResumeFactOut("contact", "personal", f"My email is {c.email}.", {"field": "email", "value": c.email}, "résumé header"))
    if c.phone:
        out.append(ResumeFactOut("contact", "personal", f"My phone number is {c.phone}.", {"field": "phone", "value": c.phone}, "résumé header"))
    if c.location:
        out.append(ResumeFactOut("contact", "personal", f"I'm based in {c.location}.", {"field": "location", "value": c.location}, "résumé header"))
    for k, v in c.links.items():
        out.append(ResumeFactOut("link", "personal", f"My {k} is {v}.", {"field": k, "value": v}, "résumé header"))
    return out
