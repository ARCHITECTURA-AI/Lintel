"""Canonical payload encoding and hashing.

The approval covers a payload, not a page. Keys are sorted, the encoding is UTF-8 and the hash
is SHA-256. Lists whose order carries no meaning (answers, documents, consents) are sorted by
their key so two equal payloads always hash the same, and any change to any field changes it.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from pydantic import BaseModel

_UNORDERED_LISTS = {"answers": "field_key", "consents": "field_key", "documents": ("role", "sha256")}


def _normalize_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, dict):
        return {unicodedata.normalize("NFC", str(k)): _normalize_strings(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_normalize_strings(v) for v in obj]
    return obj


def canonical_form(payload: BaseModel | dict[str, Any]) -> dict[str, Any]:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else json.loads(json.dumps(payload))
    data = _normalize_strings(data)
    for key, sort_key in _UNORDERED_LISTS.items():
        items = data.get(key)
        if isinstance(items, list):
            if isinstance(sort_key, tuple):
                data[key] = sorted(items, key=lambda i: tuple(str(i.get(k) or "") for k in sort_key))
            else:
                data[key] = sorted(items, key=lambda i: str(i.get(sort_key) or ""))
    for answer in data.get("answers", []) or []:
        if isinstance(answer.get("fact_ids"), list):
            answer["fact_ids"] = sorted(answer["fact_ids"])
        if isinstance(answer.get("value"), list):
            answer["value"] = sorted(str(v) for v in answer["value"])
    return data


def canonical_json(payload: BaseModel | dict[str, Any]) -> bytes:
    return json.dumps(
        canonical_form(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def payload_hash(payload: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def value_hash(value: Any) -> tuple[str, int]:
    """Hash and length for step logs. The value itself is never logged."""

    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], len(text)
