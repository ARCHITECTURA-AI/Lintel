"""Keyless, read-only ATS feeds and platform detection.

Greenhouse's job-board GET endpoints need no authentication, Lever serves postings from a
public endpoint, and Ashby exposes an unauthenticated job-board endpoint. Discovery needs no
scraping and no login. Feeds are polled gently, with ETags and content hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from lintel_schemas import FieldOption, FieldType, FormField, make_field_key

from ..config import get_settings
from ..llm.heuristics import html_to_text

USER_AGENT = "LintelBot/0.1 (+supervised job-application assistant; polls a few times a day)"

PUBLIC_BASES = {
    "greenhouse": "https://boards-api.greenhouse.io",
    "lever": "https://api.lever.co",
    "lever-eu": "https://api.eu.lever.co",
    "ashby": "https://api.ashbyhq.com",
}


class FeedError(Exception):
    pass


@dataclass
class BoardRef:
    platform: str
    board: str
    api_base: str
    careers_url: str
    region: str = "global"
    name_guess: str = ""
    posting_id: str | None = None


@dataclass
class NormalizedJob:
    posting_id: str
    title: str
    company_name: str
    location: str = ""
    workplace: str = ""
    department: str = ""
    employment_type: str = ""
    description: str = ""
    apply_url: str = ""
    comp_min: float | None = None
    comp_max: float | None = None
    comp_currency: str | None = None
    comp_interval: str | None = None
    questions: list[dict[str, Any]] | None = None

    def content_hash(self) -> str:
        blob = json.dumps(self.__dict__, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class FeedResult:
    jobs: list[NormalizedJob] = field(default_factory=list)
    etag: str | None = None
    not_modified: bool = False
    content_hash: str = ""
    company_name: str | None = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, follow_redirects=True)


def _lab_netloc() -> str:
    return urlparse(get_settings().lab_base_url).netloc


def _title_from_slug(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title()


def detect(url: str, *, fetch: bool = True) -> BoardRef:
    """Work out the platform and board from a careers URL (or a single posting URL)."""

    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    p = urlparse(url)
    host = p.netloc.lower()
    parts = [x for x in p.path.split("/") if x]

    lab = _lab_netloc()
    if host == lab and parts and parts[0] in ("greenhouse", "lever", "ashby"):
        platform = parts[0]
        if len(parts) < 2:
            raise FeedError("That Lab URL is missing the company, e.g. /greenhouse/acme.")
        posting = parts[3] if len(parts) > 3 and parts[2] == "jobs" else None
        base = f"{p.scheme}://{lab}/api/{platform}"
        return BoardRef(platform, parts[1], base, url, name_guess=_title_from_slug(parts[1]), posting_id=posting)

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io") and parts:
        board = parts[0]
        if board == "embed":
            q = dict(x.split("=", 1) for x in p.query.split("&") if "=" in x)
            board = q.get("for", "")
        posting = parts[2] if len(parts) > 2 and parts[1] == "jobs" else None
        return BoardRef("greenhouse", board, PUBLIC_BASES["greenhouse"], url, name_guess=_title_from_slug(board), posting_id=posting)
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and parts:
        eu = host.startswith("jobs.eu.")
        posting = parts[1] if len(parts) > 1 and parts[1] != "apply" else None
        return BoardRef("lever", parts[0], PUBLIC_BASES["lever-eu" if eu else "lever"], url, region="eu" if eu else "global",
                        name_guess=_title_from_slug(parts[0]), posting_id=posting)
    if host == "jobs.ashbyhq.com" and parts:
        posting = parts[1] if len(parts) > 1 else None
        return BoardRef("ashby", parts[0], PUBLIC_BASES["ashby"], url, name_guess=_title_from_slug(parts[0]), posting_id=posting)

    if not fetch:
        raise FeedError("Lintel couldn't tell which applicant tracking system that page uses.")
    # A company's own careers page usually embeds its board. Look for the tell-tale URLs.
    try:
        with _client() as c:
            r = c.get(url, headers={"Accept": "text/html"})
            html = r.text
    except httpx.HTTPError as exc:
        raise FeedError(f"Couldn't open that page ({type(exc).__name__}).") from exc
    patterns = [
        (r"boards(?:-api)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=|v1/boards/)?([A-Za-z0-9_-]+)", "greenhouse"),
        (r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)", "greenhouse"),
        (r"jobs\.lever\.co/([A-Za-z0-9_-]+)", "lever"),
        (r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", "ashby"),
        (r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.-]+)", "ashby"),
    ]
    for pattern, platform in patterns:
        m = re.search(pattern, html)
        if m and m.group(1) not in ("embed", "js", "v1"):
            base = PUBLIC_BASES[platform]
            return BoardRef(platform, m.group(1), base, url, name_guess=_title_from_slug(m.group(1)))
    raise FeedError("Lintel supports Greenhouse, Lever and Ashby boards. This page doesn't link to one of them.")


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _get_json(c: httpx.Client, url: str, etag: str | None = None) -> tuple[Any, str | None, bool]:
    headers = {"If-None-Match": etag} if etag else {}
    r = c.get(url, headers=headers)
    if r.status_code == 304:
        return None, etag, True
    if r.status_code == 404:
        raise FeedError("The board wasn't found. Check the company's careers URL.")
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "json" not in ctype:
        # Lever's feed can return HTML intermittently; treat it as a transient failure, never as data.
        raise FeedError(f"The feed returned {ctype or 'an unknown type'} instead of JSON. Will retry later.")
    return r.json(), r.headers.get("etag"), False


def _gh_field_type(t: str) -> FieldType | None:
    return {
        "input_text": FieldType.text,
        "textarea": FieldType.textarea,
        "input_file": FieldType.file,
        "multi_value_single_select": FieldType.select,
        "multi_value_multi_select": FieldType.multiselect,
        "input_hidden": None,
        "input_checkbox": FieldType.checkbox,
    }.get(t, FieldType.text)


def greenhouse_questions(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Greenhouse's questions=true payload into FormField dicts."""

    fields: list[FormField] = []

    def add(question: dict[str, Any], section: str) -> None:
        label = re.sub(r"\s+", " ", question.get("label") or "").strip()
        subs = question.get("fields") or []
        # A résumé question offers a file and a paste box; keep the file.
        chosen = next((f for f in subs if f.get("type") == "input_file"), subs[0] if subs else None)
        if chosen is None:
            return
        ftype = _gh_field_type(chosen.get("type", "input_text"))
        if ftype is None:
            return
        name = (chosen.get("name") or "").lower()
        if ftype == FieldType.text and ("email" in name or "email" in label.lower()):
            ftype = FieldType.email
        if ftype == FieldType.text and "phone" in name:
            ftype = FieldType.tel
        options = [FieldOption(label=str(v.get("label")), value=str(v.get("value"))) for v in chosen.get("values") or []]
        fields.append(
            FormField(
                field_key=make_field_key(section, label, ftype),
                section=section,
                label=label,
                type=ftype,
                required=bool(question.get("required")),
                options=options,
                is_consent=bool(re.search(r"\b(i (agree|acknowledge|consent)|privacy)\b", label, re.I)),
            )
        )

    for q in job.get("questions") or []:
        add(q, "")
    for q in (job.get("demographic_questions") or {}).get("questions") or []:
        add(
            {"label": q.get("label"), "required": q.get("required"),
             "fields": [{"type": "multi_value_single_select", "name": "demographic",
                         "values": [{"label": a.get("label"), "value": str(a.get("id"))} for a in q.get("answer_options") or []]}]},
            "Voluntary self-identification",
        )
    return [f.model_dump(mode="json") for f in fields]


def _fetch_greenhouse(c: httpx.Client, ref: BoardRef, etag: str | None) -> FeedResult:
    data, new_etag, nm = _get_json(c, f"{ref.api_base}/v1/boards/{ref.board}/jobs?content=true", etag)
    if nm:
        return FeedResult(not_modified=True, etag=etag)
    company = ref.name_guess
    try:
        meta, _, _ = _get_json(c, f"{ref.api_base}/v1/boards/{ref.board}")
        company = (meta or {}).get("name") or company
    except (FeedError, httpx.HTTPError):
        pass
    jobs = []
    for j in data.get("jobs", []):
        desc = html_to_text(j.get("content") or "")
        pay = (j.get("pay_input_ranges") or [{}])[0] if j.get("pay_input_ranges") else {}
        jobs.append(
            NormalizedJob(
                posting_id=str(j["id"]),
                title=j.get("title", "").strip(),
                company_name=j.get("company_name") or company,
                location=(j.get("location") or {}).get("name", ""),
                department=", ".join(d.get("name", "") for d in j.get("departments") or []),
                description=desc,
                apply_url=j.get("absolute_url") or "",
                comp_min=(pay.get("min_cents") or 0) / 100 or None,
                comp_max=(pay.get("max_cents") or 0) / 100 or None,
                comp_currency=pay.get("currency_type"),
                comp_interval="year" if pay else None,
                workplace="remote" if re.search(r"\bremote\b", (j.get("location") or {}).get("name", ""), re.I) else "",
            )
        )
    return FeedResult(jobs=jobs, etag=new_etag, content_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                      company_name=company if company != ref.name_guess else None)


def fetch_greenhouse_questions(ref: BoardRef, posting_id: str) -> list[dict[str, Any]] | None:
    with _client() as c:
        data, _, _ = _get_json(c, f"{ref.api_base}/v1/boards/{ref.board}/jobs/{posting_id}?questions=true")
    return greenhouse_questions(data or {})


def _fetch_lever(c: httpx.Client, ref: BoardRef, etag: str | None) -> FeedResult:
    data, new_etag, nm = _get_json(c, f"{ref.api_base}/v0/postings/{ref.board}?mode=json", etag)
    if nm:
        return FeedResult(not_modified=True, etag=etag)
    jobs = []
    for j in data or []:
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description") or "")]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}:\n" + html_to_text(lst.get("content") or ""))
        parts.append(j.get("additionalPlain") or html_to_text(j.get("additional") or ""))
        sal = j.get("salaryRange") or {}
        jobs.append(
            NormalizedJob(
                posting_id=str(j["id"]),
                title=j.get("text", "").strip(),
                company_name=ref.name_guess,
                location=cats.get("location") or "",
                department=cats.get("team") or cats.get("department") or "",
                employment_type=cats.get("commitment") or "",
                workplace=j.get("workplaceType") or "",
                description="\n\n".join(p for p in parts if p),
                apply_url=j.get("applyUrl") or (j.get("hostedUrl", "") + "/apply"),
                comp_min=sal.get("min"),
                comp_max=sal.get("max"),
                comp_currency=sal.get("currency"),
                comp_interval=(sal.get("interval") or "").replace("per-", "") or None,
            )
        )
    return FeedResult(jobs=jobs, etag=new_etag, content_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest())


def _fetch_ashby(c: httpx.Client, ref: BoardRef, etag: str | None) -> FeedResult:
    data, new_etag, nm = _get_json(c, f"{ref.api_base}/posting-api/job-board/{ref.board}?includeCompensation=true", etag)
    if nm:
        return FeedResult(not_modified=True, etag=etag)
    jobs = []
    for j in (data or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        cmin = cmax = cur = interval = None
        for comp_part in comp.get("summaryComponents") or []:
            if comp_part.get("compensationType") == "Salary":
                cmin, cmax = comp_part.get("minValue"), comp_part.get("maxValue")
                cur, interval = comp_part.get("currencyCode"), (comp_part.get("interval") or "").replace("1 ", "").lower() or None
        jobs.append(
            NormalizedJob(
                posting_id=str(j["id"]),
                title=j.get("title", "").strip(),
                company_name=ref.name_guess,
                location=j.get("location") or "",
                department=j.get("department") or j.get("team") or "",
                employment_type=j.get("employmentType") or "",
                workplace="remote" if j.get("isRemote") else (j.get("workplaceType") or ""),
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
                apply_url=j.get("applyUrl") or j.get("jobUrl") or "",
                comp_min=cmin,
                comp_max=cmax,
                comp_currency=cur,
                comp_interval=interval,
            )
        )
    return FeedResult(jobs=jobs, etag=new_etag, content_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest())


def fetch_board(ref: BoardRef, etag: str | None = None) -> FeedResult:
    try:
        with _client() as c:
            if ref.platform == "greenhouse":
                return _fetch_greenhouse(c, ref, etag)
            if ref.platform == "lever":
                return _fetch_lever(c, ref, etag)
            if ref.platform == "ashby":
                return _fetch_ashby(c, ref, etag)
    except httpx.HTTPError as exc:
        raise FeedError(f"Feed request failed ({type(exc).__name__}). Will retry later.") from exc
    raise FeedError(f"Unsupported platform {ref.platform}.")


# ---------------------------------------------------------------------------
# Standard hosted forms, used until the runner reads the live page.
# ---------------------------------------------------------------------------


def _ff(label: str, ftype: FieldType, required: bool = False, section: str = "") -> dict[str, Any]:
    return FormField(field_key=make_field_key(section, label, ftype), section=section, label=label, type=ftype,
                     required=required).model_dump(mode="json")


DEFAULT_FORMS: dict[str, list[dict[str, Any]]] = {
    "lever": [
        _ff("Resume/CV", FieldType.file, True),
        _ff("Full name", FieldType.text, True),
        _ff("Email", FieldType.email, True),
        _ff("Phone", FieldType.tel),
        _ff("Current company", FieldType.text),
        _ff("LinkedIn URL", FieldType.url),
        _ff("GitHub URL", FieldType.url),
        _ff("Portfolio URL", FieldType.url),
        _ff("Additional information", FieldType.textarea),
    ],
    "ashby": [
        _ff("Name", FieldType.text, True),
        _ff("Email", FieldType.email, True),
        _ff("Phone", FieldType.tel),
        _ff("Resume", FieldType.file, True),
        _ff("LinkedIn", FieldType.url),
        _ff("Website", FieldType.url),
    ],
    "greenhouse": [
        _ff("First Name", FieldType.text, True),
        _ff("Last Name", FieldType.text, True),
        _ff("Email", FieldType.email, True),
        _ff("Phone", FieldType.tel),
        _ff("Resume/CV", FieldType.file, True),
        _ff("LinkedIn Profile", FieldType.url),
    ],
}
