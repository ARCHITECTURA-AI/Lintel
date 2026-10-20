"""Read adapters: observe the outcome of a click. Evidence by default is text, not pictures.

On a confirmation page the runner keeps the matched text, the reference number and a page hash.
Screenshots are off.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

from playwright.sync_api import Page

CONFIRM = re.compile(
    r"(application (has been )?(submitted|received)|thank(s| you) for (applying|your application|your interest)|"
    r"we('|’)ve received your application|your application (was|has been) sent)",
    re.IGNORECASE,
)
REFERENCE = re.compile(r"\b(?:reference|confirmation|application id|ref)\s*(?:number|no\.?|#|id)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})",
                       re.IGNORECASE)
ERRORS = re.compile(r"(please fix|is required|invalid|error)", re.IGNORECASE)


@dataclass
class Outcome:
    status: str  # confirmed | errors | unknown
    text: str = ""
    reference: str | None = None
    page_hash: str | None = None


def _body(page: Page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception:  # noqa: BLE001 - navigation in progress
        return ""


def observe(page: Page, timeout_s: float = 30.0) -> Outcome:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        text = _body(page)
        m = CONFIRM.search(text)
        if m:
            ref = None
            try:
                el = page.query_selector("#reference, [data-reference], .reference")
                ref = el.inner_text().strip() if el else None
            except Exception:  # noqa: BLE001
                ref = None
            if not ref:
                rm = REFERENCE.search(text)
                ref = rm.group(1) if rm else None
            start = max(0, m.start() - 80)
            snippet = re.sub(r"\s+", " ", text[start : m.end() + 160]).strip()
            digest = hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()
            return Outcome("confirmed", snippet, ref, digest)
        try:
            page.wait_for_timeout(400)
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    text = _body(page)
    if ERRORS.search(text):
        return Outcome("errors", re.sub(r"\s+", " ", text[:300]))
    return Outcome("unknown")
