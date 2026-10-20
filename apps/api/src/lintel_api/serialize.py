"""ORM rows to JSON-safe dicts. Secrets (token hashes, password hashes) never leave."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from .db.models import Base

SECRET_FIELDS = {"token_hash", "password_hash", "storage_key", "signature"}


def plain(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return v


def row(obj: Base | None, *, exclude: set[str] | None = None, **extra: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    skip = SECRET_FIELDS | (exclude or set())
    out = {c.key: plain(getattr(obj, c.key)) for c in obj.__mapper__.column_attrs if c.key not in skip}
    out.update({k: plain(v) for k, v in extra.items()})
    return out


def rows(objs, **kw: Any) -> list[dict[str, Any]]:
    return [row(o, **kw) for o in objs]
