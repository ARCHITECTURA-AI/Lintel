"""Value normalization used by the Submit Guard and by verify-after-every-action.

The Guard compares live form values to the approved payload. Both sides pass through the same
normalization, so a trailing space or a CRLF typed by the browser does not count as a change,
while any real change to wording, a choice, a checkbox or a file does.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from lintel_schemas import FieldType

_WS = re.compile(r"[ \t ]+")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "on", "yes", "1", "checked"}
    return bool(value)


def normalize_value(field_type: FieldType | str, value: Any) -> Any:
    ft = FieldType(field_type)
    if ft == FieldType.checkbox:
        return normalize_bool(value)
    if ft == FieldType.multiselect:
        if value is None:
            return []
        items = value if isinstance(value, list | tuple) else [value]
        return sorted(normalize_text(v) for v in items if normalize_text(v))
    if ft in (FieldType.email, FieldType.url):
        return normalize_text(value).lower()
    if ft == FieldType.tel:
        return re.sub(r"[^\d+]", "", normalize_text(value))
    if ft == FieldType.number:
        text = normalize_text(value).replace(",", "")
        return text
    return normalize_text(value)


def values_equal(field_type: FieldType | str, approved: Any, live: Any) -> bool:
    return normalize_value(field_type, approved) == normalize_value(field_type, live)
