"""Lintel Lab: the repeatable ground truth for agent work, and a showpiece in its own right.

Run with `uv run lintel-lab` (port 4100). It serves:
  * careers pages and apply forms in Greenhouse-, Lever- and Ashby-style skins
  * keyless feeds shaped like each platform's public job-board API, under /api/<platform>/...
  * the awkward cases: conditional fields, multi-step flow, file upload, validation errors,
    session expiry, a CAPTCHA placeholder, an unexpected modal, a timeout right after submit,
    and prompt injection in job and page text
  * /lab/submissions, so tests can assert that nothing was ever sent twice
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import data

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
STATE_FILE = Path(os.environ.get("LINTEL_LAB_STATE", Path.cwd() / ".data" / "lab" / "submissions.json"))
_lock = threading.Lock()
FLAGS = {"lever_flaky": False}

app = FastAPI(title="Lintel Lab", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


def _load() -> list[dict[str, Any]]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []


def _save(rows: list[dict[str, Any]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(rows, indent=2))


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _find(platform: str, slug: str, pid: str | None = None):
    c = data.company(slug)
    if c is None or c.platform != platform:
        raise HTTPException(404, "No such company in the Lab")
    if pid is None:
        return c, None
    p = data.posting(c, pid)
    if p is None:
        raise HTTPException(404, "No such posting")
    return c, p


def _text(desc_html: str) -> str:
    t = re.sub(r"<li>", "\n- ", desc_html)
    t = re.sub(r"</(p|h3|ul|li)>", "\n", t)
    t = re.sub(r"<h3>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n\s*\n+", "\n\n", html.unescape(t)).strip()


# ---------------------------------------------------------------------------
# Showcase
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
@app.get("/lab", response_class=HTMLResponse)
def lab_index(request: Request):
    subs = _load()
    return templates.TemplateResponse(request, "lab_index.html", {"companies": data.COMPANIES, "submissions": subs[-12:][::-1],
                                                                  "count": len(subs), "flags": FLAGS})


@app.get("/lab/submissions")
def submissions() -> list[dict[str, Any]]:
    return _load()


@app.delete("/lab/submissions")
def reset_submissions() -> dict[str, Any]:
    with _lock:
        _save([])
    return {"ok": True}


@app.post("/lab/flags/{name}")
def toggle_flag(name: str) -> dict[str, Any]:
    if name not in FLAGS:
        raise HTTPException(404)
    FLAGS[name] = not FLAGS[name]
    return FLAGS


# ---------------------------------------------------------------------------
# Careers pages and forms
# ---------------------------------------------------------------------------


@app.get("/{platform}/{slug}", response_class=HTMLResponse)
def board(request: Request, platform: str, slug: str):
    c, _ = _find(platform, slug)
    return templates.TemplateResponse(request, "board.html", {"c": c})


@app.get("/{platform}/{slug}/jobs/{pid}", response_class=HTMLResponse)
def posting_page(request: Request, platform: str, slug: str, pid: str):
    c, p = _find(platform, slug, pid)
    return templates.TemplateResponse(request, "posting.html", {"c": c, "p": p})


@app.get("/{platform}/{slug}/jobs/{pid}/apply", response_class=HTMLResponse)
def apply_page(request: Request, platform: str, slug: str, pid: str, expires: int = 90):
    c, p = _find(platform, slug, pid)
    qs = data.questions_for(c, p)
    steps = max(q.step for q in qs) + 1
    return templates.TemplateResponse(
        request, "apply.html",
        {"c": c, "p": p, "qs": qs, "steps": steps, "expires": expires, "errors": {}, "values": {}},
    )


@app.post("/{platform}/{slug}/jobs/{pid}/apply", response_class=HTMLResponse)
async def submit(request: Request, platform: str, slug: str, pid: str):
    c, p = _find(platform, slug, pid)
    form = await request.form()
    qs = data.questions_for(c, p)
    values: dict[str, Any] = {}
    files: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for q in qs:
        if q.type == "file":
            f = form.get(q.name)
            if f is not None and hasattr(f, "read"):
                blob = await f.read()
                if blob:
                    files[q.name] = {"filename": f.filename, "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}
            if q.required and q.name not in files:
                errors[q.name] = "Please attach a file."
            continue
        v = form.getlist(q.name) if q.type == "multiselect" else form.get(q.name)
        if q.type == "checkbox":
            v = v in ("on", "true", "1", "yes")
        values[q.name] = v
        visible = not q.show_if or form.get(q.show_if[0]) == q.show_if[1]
        if q.required and visible and not q.hidden_trap and (v in (None, "", False, [])):
            errors[q.name] = "This field is required."
        if q.pattern and v and not re.match(q.pattern, str(v)):
            errors[q.name] = "Include your country code, e.g. +91 98765 43210."
    if errors:
        steps = max(q.step for q in qs) + 1
        return templates.TemplateResponse(request, "apply.html", {"c": c, "p": p, "qs": qs, "steps": steps, "expires": 900,
                                                                  "errors": errors, "values": values}, status_code=422)
    ref = "LAB-" + secrets.token_hex(3).upper()
    email = str(values.get("email") or values.get("_systemfield_email") or "").lower()
    row = {
        "reference": ref,
        "company": c.slug,
        "platform": c.platform,
        "posting_id": p.id,
        "email": email,
        "values": values,
        "files": files,
        "trap_filled": bool(values.get("trap")),
        "at": datetime.now(UTC).isoformat(),
    }
    with _lock:
        rows = _load()
        row["duplicate_of"] = next((r["reference"] for r in rows if r["posting_id"] == p.id and r["email"] == email and email), None)
        rows.append(row)
        _save(rows)
    if p.case == "timeout":
        # The application is recorded, then the server never answers: the case "uncertain" exists for.
        await asyncio.sleep(600)
    return templates.TemplateResponse(request, "confirm.html", {"c": c, "p": p, "ref": ref})


# ---------------------------------------------------------------------------
# Feeds shaped like each platform's public job-board endpoint
# ---------------------------------------------------------------------------


def _gh_job(request: Request, c: data.Company, p: data.Posting, *, content: bool, questions: bool) -> dict[str, Any]:
    base = _base(request)
    job: dict[str, Any] = {
        "id": int(p.id),
        "title": p.title,
        "updated_at": "2026-10-20T09:00:00-04:00",
        "location": {"name": p.location},
        "absolute_url": f"{base}/greenhouse/{c.slug}/jobs/{p.id}/apply",
        "departments": [{"name": p.department}],
        "company_name": c.name,
    }
    if content:
        job["content"] = html.escape(p.description_html)
    if p.comp:
        job["pay_input_ranges"] = [{"min_cents": p.comp[0] * 100, "max_cents": p.comp[1] * 100, "currency_type": p.comp[2]}]
    if questions:
        qs = data.questions_for(c, p)
        job["questions"] = [data.gh_question_json(q) for q in qs if not q.section and not q.hidden_trap]
        demo = [q for q in qs if q.section == "Voluntary self-identification"]
        job["demographic_questions"] = {
            "questions": [{"label": q.label, "required": q.required,
                           "answer_options": [{"id": v, "label": lbl} for v, lbl in q.options]} for q in demo]
        }
    return job


@app.get("/api/greenhouse/v1/boards/{board}")
def gh_board(board: str):
    c = data.company(board)
    if c is None or c.platform != "greenhouse":
        raise HTTPException(404)
    return {"name": c.name, "content": f"<p>{c.blurb}</p>"}


@app.get("/api/greenhouse/v1/boards/{board}/jobs")
def gh_jobs(request: Request, board: str, content: bool = False):
    c = data.company(board)
    if c is None or c.platform != "greenhouse":
        raise HTTPException(404)
    body = {"jobs": [_gh_job(request, c, p, content=content, questions=False) for p in c.postings], "meta": {"total": len(c.postings)}}
    etag = '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return JSONResponse(status_code=304, content=None, headers={"ETag": etag})
    return JSONResponse(body, headers={"ETag": etag})


@app.get("/api/greenhouse/v1/boards/{board}/jobs/{job_id}")
def gh_job(request: Request, board: str, job_id: str, questions: bool = False):
    c, p = _find("greenhouse", board, job_id)
    return _gh_job(request, c, p, content=True, questions=questions)


@app.get("/api/lever/v0/postings/{site}")
def lever_postings(request: Request, site: str, mode: str = "json"):
    c = data.company(site)
    if c is None or c.platform != "lever":
        raise HTTPException(404)
    if FLAGS["lever_flaky"]:
        # The real feed can return HTML intermittently; consumers must check the content type.
        return HTMLResponse("<html><body>Temporarily unavailable</body></html>")
    base = _base(request)
    out = []
    for p in c.postings:
        out.append({
            "id": p.id,
            "text": p.title,
            "categories": {"location": p.location, "team": p.department, "commitment": p.employment_type},
            "description": p.description_html,
            "descriptionPlain": _text(p.description_html),
            "lists": [],
            "additional": "",
            "hostedUrl": f"{base}/lever/{c.slug}/jobs/{p.id}",
            "applyUrl": f"{base}/lever/{c.slug}/jobs/{p.id}/apply",
            "workplaceType": p.workplace or "unspecified",
            "salaryRange": {"min": p.comp[0], "max": p.comp[1], "currency": p.comp[2], "interval": "per-year-salary"} if p.comp else None,
        })
    return out


@app.get("/api/ashby/posting-api/job-board/{org}")
def ashby_board(request: Request, org: str, includeCompensation: bool = False):  # noqa: N803 - mirrors the real parameter
    c = data.company(org)
    if c is None or c.platform != "ashby":
        raise HTTPException(404)
    base = _base(request)
    jobs = []
    for p in c.postings:
        j: dict[str, Any] = {
            "id": p.id,
            "title": p.title,
            "location": p.location,
            "department": p.department,
            "team": p.department,
            "employmentType": p.employment_type.replace("-", ""),
            "isRemote": p.workplace == "remote",
            "isListed": True,
            "descriptionHtml": p.description_html,
            "descriptionPlain": _text(p.description_html),
            "jobUrl": f"{base}/ashby/{c.slug}/jobs/{p.id}",
            "applyUrl": f"{base}/ashby/{c.slug}/jobs/{p.id}/apply",
            "publishedAt": "2026-10-15T10:00:00.000Z",
        }
        if includeCompensation and p.comp:
            j["compensation"] = {
                "compensationTierSummary": f"{p.comp[2]} {p.comp[0]:,} – {p.comp[1]:,}",
                "summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": p.comp[2],
                                       "minValue": p.comp[0], "maxValue": p.comp[1]}],
            }
        jobs.append(j)
    return {"apiVersion": "1", "jobs": jobs}


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return "User-agent: *\nAllow: /\n"


def main() -> None:
    import uvicorn

    uvicorn.run("lintel_lab.server:app", host=os.environ.get("LINTEL_LAB_HOST", "127.0.0.1"),
                port=int(os.environ.get("LINTEL_LAB_PORT", "4100")))


if __name__ == "__main__":
    main()
