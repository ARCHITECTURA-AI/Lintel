"""Résumé ingestion. Every extracted fact is a candidate until the user confirms it."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..db.models import Document, FactCandidate, ProfileFact, User
from ..errors import bad_request, conflict, not_found
from ..llm import provider_for
from . import facts as ledger
from .core import audit, now
from .resume_parse import contact_facts, extract_text, parse_structure, redact

MAX_BYTES = 5 * 1024 * 1024
ALLOWED = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           ".txt": "text/plain", ".md": "text/markdown"}


def upload_resume(db: Session, user: User, data: bytes, filename: str, content_type: str) -> tuple[Document, int]:
    if len(data) > MAX_BYTES:
        raise bad_request("too_large", "Keep résumés under 5 MB.")
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise bad_request("bad_type", "Upload a PDF, DOCX or plain-text résumé.")
    try:
        text = extract_text(data, ALLOWED[ext], filename)
    except Exception as exc:  # noqa: BLE001
        raise bad_request("unreadable", "Lintel couldn't read text from that file. Try a text-based PDF or DOCX.") from exc
    if len(text.strip()) < 40:
        raise bad_request("unreadable", "That file has almost no text. Scanned PDFs need a text version.")
    key, digest = storage.put(user.id, data)
    redacted, contacts = redact(text)
    doc = Document(user_id=user.id, kind="resume_base", filename=filename, content_type=ALLOWED[ext], size_bytes=len(data),
                   sha256=digest, storage_key=key, parsed=parse_structure(text))
    db.add(doc)
    db.flush()
    # Replace any older pending candidates; confirmed facts stay in the ledger.
    for old in db.scalars(select(FactCandidate).where(FactCandidate.status == "pending")):
        old.status = "rejected"
        old.decided_at = now()
    existing = {f.statement.lower() for f in ledger.current_facts(db)}
    provider = provider_for(db, user.id)
    candidates = contact_facts(contacts) + provider.extract_resume_facts(redacted)
    n = 0
    for c in candidates:
        if c.statement.lower() in existing:
            continue
        db.add(FactCandidate(user_id=user.id, document_id=doc.id, kind=c.kind, claim_scope=c.claim_scope,
                             statement=c.statement, attributes=c.attributes, source_ref=c.source_ref))
        n += 1
    audit(db, user.id, "user", "resume.uploaded", "document", doc.id, sha256=digest, candidates=n)
    return doc, n


def confirm_candidate(db: Session, user: User, cand_id: uuid.UUID, *, statement: str | None = None,
                      claim_scope: str | None = None, kind: str | None = None, attributes: dict | None = None) -> ProfileFact:
    c = db.get(FactCandidate, cand_id)
    if c is None:
        raise not_found("Candidate not found.")
    if c.status != "pending":
        raise conflict("decided", "That candidate was already decided.")
    edited = statement is not None and statement.strip() != c.statement
    fact = ledger.add_fact(
        db, user.id,
        kind=kind or c.kind,
        claim_scope=claim_scope or c.claim_scope,
        statement=statement if statement is not None else c.statement,
        attributes=attributes if attributes is not None else c.attributes,
        source_type="resume" if not edited else "user_entry",
        source_ref=c.source_ref + (" (edited by you)" if edited else ""),
    )
    c.status = "confirmed"
    c.fact_id = fact.id
    c.decided_at = now()
    return fact


def reject_candidate(db: Session, cand_id: uuid.UUID) -> None:
    c = db.get(FactCandidate, cand_id)
    if c is None:
        raise not_found("Candidate not found.")
    if c.status == "pending":
        c.status = "rejected"
        c.decided_at = now()
