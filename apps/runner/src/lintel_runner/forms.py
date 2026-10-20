"""Deterministic form model. No model is involved: labels, roles, types, options, required flags,
character limits and visibility come from the DOM and ARIA attributes. Each field gets a stable
field_key, a hash of its section, label and type."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lintel_schemas import FieldOption, FieldType, FormField, FormModel, Locator, make_field_key, page_version
from playwright.sync_api import Page

READER = (Path(__file__).parent / "js" / "formmodel.js").read_text()


@dataclass
class LiveField:
    field: FormField
    value: Any
    invalid: bool = False


@dataclass
class PageRead:
    model: FormModel
    live: dict[str, LiveField]
    has_next: bool
    dialog: str | None
    captcha: bool
    login_wall: bool
    session_expired: bool
    validation_errors: list[str]

    @property
    def visible_fields(self) -> list[FormField]:
        return [f for f in self.model.fields if f.visible]


# Installed in every page so the Submit Guard can read the form without a round trip.
INIT_SCRIPT = f"window.__lintelReadForm = () => {READER.strip().rstrip(';')};"


def read_page(page: Page) -> PageRead:
    return parse_read(page.evaluate(READER))


def parse_read(raw: dict[str, Any]) -> PageRead:
    fields: list[FormField] = []
    live: dict[str, LiveField] = {}
    seen: dict[str, int] = {}
    for f in raw["fields"]:
        ftype = FieldType(f["type"])
        section = f.get("section") or ""
        label = f.get("label") or ""
        key = make_field_key(section, label, ftype)
        if key in seen:  # two controls with the same label: disambiguate deterministically
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 0
        is_consent = ftype == FieldType.checkbox and any(
            w in label.lower() for w in ("agree", "acknowledge", "consent", "privacy")
        )
        ff = FormField(
            field_key=key,
            section=section,
            label=label,
            type=ftype,
            required=bool(f.get("required")),
            options=[FieldOption(label=o["label"], value=o["value"]) for o in f.get("options") or []],
            max_length=f.get("max_length"),
            visible=bool(f.get("visible")),
            is_consent=is_consent,
            accept=f.get("accept"),
            locator=Locator(css=f["locator"]["css"]),
        )
        fields.append(ff)
        live[key] = LiveField(ff, f.get("value"), bool(f.get("invalid")))
    model = FormModel(
        url=raw["url"],
        host=raw["host"],
        page_version=page_version([f.field_key for f in fields]),
        fields=fields,
        has_submit=bool(raw["has_submit"]),
        bot_challenge=bool(raw["captcha"]),
        login_wall=bool(raw["login_wall"]),
        source="runner",
    )
    return PageRead(model=model, live=live, has_next=bool(raw["has_next"]), dialog=raw.get("dialog"),
                    captcha=bool(raw["captcha"]), login_wall=bool(raw["login_wall"]),
                    session_expired=bool(raw["session_expired"]), validation_errors=raw.get("validation_errors") or [])


def file_hashes(page: Page) -> dict[str, str]:
    return page.evaluate("() => window.__lintelFileHashes ? window.__lintelFileHashes() : {}") or {}
