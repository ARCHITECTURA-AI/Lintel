"""Grounded résumé variants.

Per role, Lintel proposes a reorder and rewording of existing bullets, shown as a diff against
the base résumé. It never adds a claim: every reworded bullet is claim checked against the
original bullet. The approved variant is stored with its document hash.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

from lintel_schemas import ApplicationState, ClaimScope, Fact, FactAttributes, FactKind, SourceType
from lintel_trust.claimcheck import check_sentence
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..db.models import Application, Document, Job, ResumeVariant, User
from ..errors import conflict, not_found
from ..llm import provider_for
from . import facts as ledger
from .core import audit, now


def base_resume(db: Session) -> Document | None:
    return db.scalar(
        select(Document).where(Document.kind == "resume_base", Document.deleted_at.is_(None)).order_by(Document.created_at.desc())
    )


def _bullets(doc: Document) -> list[dict[str, Any]]:
    out = []
    for section in (doc.parsed or {}).get("sections", []):
        if section["name"] not in ("experience", "projects"):
            continue
        for e_idx, entry in enumerate(section["entries"]):
            group = f"{section['name']}:{e_idx}"
            for b in entry["bullets"]:
                out.append({"id": b["id"], "text": b["text"], "group": group, "section": section["name"],
                            "entry": entry["header"]})
    return out


def propose_variant(db: Session, user: User, app: Application) -> ResumeVariant | None:
    doc = base_resume(db)
    if doc is None:
        return None
    bullets = _bullets(doc)
    if len(bullets) < 2:
        return None
    from .drafting import fit_requirements

    reqs = fit_requirements(app)
    provider = provider_for(db, user.id)
    facts_now = ledger.current_facts(db, app.id)
    proposal = provider.propose_variant(bullets, reqs, ledger.model_summaries(facts_now))
    by_id = {b["id"]: b for b in bullets}
    original_index = {b["id"]: i for i, b in enumerate(bullets)}
    job = db.get(Job, app.job_id)

    changes = []
    ordered = []
    for new_index, p in enumerate(proposal):
        orig = by_id[p.bullet_id]
        text = p.text.strip()
        check = None
        kind = "unchanged"
        if text != orig["text"].strip():
            # The original bullet is the only evidence a rewording may use.
            pseudo = Fact(id=f"bullet:{orig['id']}", kind=FactKind.achievement, claim_scope=ClaimScope.employment
                          if orig["section"] == "experience" else ClaimScope.project,
                          statement=orig["text"], attributes=FactAttributes(employer=None), source_type=SourceType.resume)
            res = check_sentence(text, [pseudo], all_facts=[ledger.to_schema(f) for f in facts_now],
                                 context_terms=[orig["entry"] or "", job.company_name])
            check = res.model_dump(mode="json")
            if res.passed:
                kind = "reworded"
            else:
                text = orig["text"]
                kind = "unchanged"
        if kind == "unchanged" and new_index != original_index[p.bullet_id]:
            kind = "moved"
        changes.append({
            "bullet_id": p.bullet_id, "kind": kind, "before": orig["text"], "after": text,
            "from_index": original_index[p.bullet_id], "to_index": new_index,
            "reason": p.reason if kind != "unchanged" or check is None else "Rewording failed the claim check; kept the original.",
            "check": check, "group": orig["group"], "entry": orig["entry"],
        })
        ordered.append({**orig, "text": text})
    if not any(c["kind"] != "unchanged" for c in changes):
        return None
    for old in db.scalars(select(ResumeVariant).where(ResumeVariant.application_id == app.id, ResumeVariant.status == "proposed")):
        old.status = "rejected"
    variant = ResumeVariant(
        user_id=user.id, application_id=app.id, base_document_id=doc.id, diff=changes, bullets=ordered,
        check_summary={"reworded": sum(c["kind"] == "reworded" for c in changes), "moved": sum(c["kind"] == "moved" for c in changes),
                       "reverted": sum(1 for c in changes if c["check"] and not c["check"]["passed"])},
    )
    db.add(variant)
    db.flush()
    return variant


def approve_variant(db: Session, user: User, app: Application, variant_id: uuid.UUID) -> ResumeVariant:
    v = db.get(ResumeVariant, variant_id)
    if v is None or v.application_id != app.id:
        raise not_found("Variant not found.")
    if v.status != "proposed":
        raise conflict("variant_decided", "That variant was already decided.")
    base = db.get(Document, v.base_document_id)
    pdf = render_pdf(db, base, v.bullets)
    key, digest = storage.put(user.id, pdf)
    doc = Document(user_id=user.id, kind="resume_variant", filename=f"resume-{app.id.hex[:8]}.pdf",
                   content_type="application/pdf", size_bytes=len(pdf), sha256=digest, storage_key=key)
    db.add(doc)
    db.flush()
    v.document_id = doc.id
    v.document_sha256 = digest
    v.status = "approved"
    v.approved_at = now()
    app.resume_variant_id = v.id
    audit(db, user.id, "user", "variant.approved", "resume_variant", v.id, sha256=digest)
    from .drafting import refresh_payload

    if app.state not in (ApplicationState.confirmed.value,):
        refresh_payload(db, app)
    return v


def reject_variant(db: Session, user: User, app: Application, variant_id: uuid.UUID) -> ResumeVariant:
    v = db.get(ResumeVariant, variant_id)
    if v is None or v.application_id != app.id:
        raise not_found("Variant not found.")
    v.status = "rejected"
    if app.resume_variant_id == v.id:
        app.resume_variant_id = None
    from .drafting import refresh_payload

    refresh_payload(db, app)
    return v


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/Library/Fonts", "C:/Windows/Fonts"]


def _font_path(name: str) -> str | None:
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def render_pdf(db: Session, base: Document, ordered_bullets: list[dict[str, Any]]) -> bytes:
    from fpdf import FPDF

    facts_now = ledger.current_facts(db)
    hv = ledger.handle_values(facts_now)
    name = hv.get("contact.full_name", ("", "", None, ""))[0]
    contact_bits = [hv[h][0] for h in ("contact.email", "contact.phone", "contact.location", "links.linkedin", "links.github") if h in hv]

    pdf = FPDF(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, 16)
    regular, bold = _font_path("DejaVuSans.ttf"), _font_path("DejaVuSans-Bold.ttf")
    if regular and bold:
        pdf.add_font("Body", "", regular)
        pdf.add_font("Body", "B", bold)
        family = "Body"

        def clean(t: str) -> str:
            return t
    else:
        family = "Helvetica"

        def clean(t: str) -> str:
            t = t.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u2022", "-")
            return t.encode("latin-1", "replace").decode("latin-1")
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font(family, "B", 18)
    pdf.cell(width, 9, clean(name or "Résumé"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, "", 9)
    if contact_bits:
        pdf.multi_cell(width, 5, clean("  ·  ".join(contact_bits) if regular else "  |  ".join(contact_bits)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    by_group: dict[str, list[dict[str, Any]]] = {}
    for b in ordered_bullets:
        by_group.setdefault(b["group"], []).append(b)
    for section in (base.parsed or {}).get("sections", []):
        title = {"experience": "Experience", "projects": "Projects", "education": "Education", "skills": "Skills",
                 "certifications": "Certifications", "summary": "Summary", "awards": "Awards"}.get(section["name"], section["name"].title())
        pdf.set_font(family, "B", 11)
        pdf.cell(width, 7, clean(title.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(180, 180, 180)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
        pdf.ln(1.5)
        for e_idx, entry in enumerate(section["entries"]):
            header = " ".join([entry["header"], *entry.get("extra", [])]).strip()
            if header:
                pdf.set_font(family, "B", 10)
                pdf.multi_cell(width, 5.2, clean(header), new_x="LMARGIN", new_y="NEXT")
            group = f"{section['name']}:{e_idx}"
            bullets = by_group.get(group) or [{"text": b["text"]} for b in entry["bullets"]]
            pdf.set_font(family, "", 9.5)
            for b in bullets:
                pdf.set_x(pdf.l_margin + 3)
                pdf.multi_cell(width - 3, 4.8, clean(("• " if regular else "- ") + b["text"]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.2)
    return bytes(pdf.output())


def plain_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
