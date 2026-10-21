"""Stable identifiers shared by the cloud and the Local Runner."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from .enums import FieldType

_TYPE_CLASS = {
    FieldType.text: "text",
    FieldType.textarea: "text",
    FieldType.email: "text",
    FieldType.tel: "text",
    FieldType.url: "text",
    FieldType.number: "text",
    FieldType.date: "text",
    FieldType.select: "choice",
    FieldType.radio: "choice",
    FieldType.multiselect: "multi",
    FieldType.checkbox: "check",
    FieldType.file: "file",
}


def normalize_label(label: str) -> str:
    s = unicodedata.normalize("NFKC", label or "").lower()
    s = re.sub(r"\(\s*(required|optional)\s*\)", " ", s)
    s = s.replace("*", " ")
    s = re.sub(r"[^\w?/&+#' -]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" :")


def type_class(field_type: FieldType | str) -> str:
    return _TYPE_CLASS[FieldType(field_type)]


def make_field_key(section: str, label: str, field_type: FieldType | str) -> str:
    """A field's stable key: a hash of its section, label and type class.

    The type class is coarse (an email input and a text input are both text), so a field keeps its
    key when a site changes an input's type without changing what it asks.
    """

    raw = f"{normalize_label(section)}|{normalize_label(label)}|{type_class(field_type)}"
    return "fk_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def page_version(field_keys: list[str]) -> str:
    return "pv_" + hashlib.sha256("\n".join(field_keys).encode()).hexdigest()[:12]
