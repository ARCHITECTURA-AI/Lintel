"""Export and deletion stay in the product from the first release.

Deleting an account hard-deletes facts, drafts, documents and step logs. It cannot recall
applications already sent to employers, and the product says so plainly.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import storage
from ..db import models as m
from ..db.models import Base, Document, User

EXPORT_TABLES = [
    m.ProfileFact, m.ProfileVersion, m.FactCandidate, m.WatchlistCompany, m.Job, m.Application, m.ApplicationEvent,
    m.AnswerDraft, m.UserTask, m.ResumeVariant, m.ApplicationRun, m.RunStep, m.ApprovalRecord, m.SubmitIntent, m.Evidence,
    m.OutcomeEvent, m.Contact, m.FollowUp, m.Notification, m.RunnerDevice, m.ModelUsage, m.AuditEvent, m.Document,
]


def _plain(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def _row(obj: Base) -> dict[str, Any]:
    out = {c.key: _plain(getattr(obj, c.key)) for c in obj.__mapper__.column_attrs}
    out.pop("token_hash", None)
    out.pop("password_hash", None)
    return out


def export_zip(db: Session, user: User) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("account.json", json.dumps(_row(user), indent=2))
        for model in EXPORT_TABLES:
            rows = [_row(r) for r in db.scalars(select(model))]
            z.writestr(f"{model.__tablename__}.json", json.dumps(rows, indent=2, ensure_ascii=False))
        for doc in db.scalars(select(Document).where(Document.deleted_at.is_(None))):
            try:
                z.writestr(f"documents/{doc.id}-{doc.filename}", storage.get(user.id, doc.storage_key))
            except FileNotFoundError:
                z.writestr(f"documents/{doc.id}.missing", base64.b64encode(b"").decode())
        z.writestr(
            "README.txt",
            "Your Lintel export. Facts are append-only: superseded and removed facts are included so the history is complete.\n"
            "Run step logs contain hashes and lengths, never the values you typed.\n",
        )
    return buf.getvalue()


def erase(db: Session, user: User) -> None:
    db.execute(text("SELECT erase_user()"))
    storage.delete_user(user.id)
