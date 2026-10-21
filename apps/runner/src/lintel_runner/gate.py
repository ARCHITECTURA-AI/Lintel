"""The policy gate. Not a model: plain code that runs before every action.

An action runs only if:
  1. the tool is allowed in the current mode and run kind (in assisted fill there is no submit
     tool at all),
  2. the field exists in the current form model and page version,
  3. the value comes from the approved (or pinned) payload,
  4. the target is not a final control,
  5. uploads are on the approved list, matched by hash, and navigation stays on registry hosts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from lintel_schemas import CanonicalPayload, FieldType, FormModel, RunKind, SupportMode
from lintel_trust import normalize_value

ActionKind = Literal["fill", "select", "check", "upload", "next_step", "navigate", "click_submit"]

TOOLS: dict[tuple[RunKind, SupportMode], set[str]] = {
    (RunKind.read_form, SupportMode.assisted_fill): {"navigate"},
    (RunKind.read_form, SupportMode.approved_submission): {"navigate"},
    (RunKind.read_form, SupportMode.draft_only): set(),
    (RunKind.fill, SupportMode.assisted_fill): {"navigate", "fill", "select", "check", "upload", "next_step"},
    (RunKind.fill, SupportMode.approved_submission): {"navigate", "fill", "select", "check", "upload", "next_step"},
    (RunKind.submit, SupportMode.assisted_fill): {"navigate", "fill", "select", "check", "upload", "next_step"},
    (RunKind.submit, SupportMode.approved_submission): {"navigate", "fill", "select", "check", "upload", "next_step",
                                                        "click_submit"},
}


@dataclass
class Action:
    kind: ActionKind
    field_key: str | None = None
    value: Any = None
    target: str | None = None  # url for navigate, sha256 for upload


class Denied(Exception):
    pass


class PolicyGate:
    def __init__(self, *, kind: RunKind, mode: SupportMode, payload: CanonicalPayload | None,
                 allowed_hosts: list[str], permitted_paths: list[str]):
        self.kind = kind
        self.mode = mode
        self.payload = payload
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.permitted_paths = permitted_paths or ["/"]
        self.answers = {a.field_key: a.value for a in payload.answers} if payload else {}
        self.consents = {c.field_key: c.value for c in payload.consents} if payload else {}
        self.documents = {d.sha256: d for d in payload.documents} if payload else {}
        self.guard_passed = False

    def tools(self) -> set[str]:
        return TOOLS.get((self.kind, self.mode), set())

    def check(self, action: Action, form: FormModel | None, planned_version: str | None = None) -> None:
        if action.kind not in self.tools():
            raise Denied(f"{action.kind} is not available in {self.mode.value} for a {self.kind.value} run")
        if action.kind == "navigate":
            p = urlparse(action.target or "")
            if p.netloc.lower() not in self.allowed_hosts:
                raise Denied(f"{p.netloc} is not a registry host")
            if not any((p.path or "/").startswith(pp) for pp in self.permitted_paths):
                raise Denied(f"{p.path} is not a permitted path")
            return
        if action.kind == "click_submit":
            if not self.guard_passed:
                raise Denied("the Guard has not passed for this click")
            return
        if action.kind == "next_step":
            return  # a step control, never the final one; the caller finds it by type=button
        if form is None:
            raise Denied("no form model")
        if planned_version and form.page_version != planned_version:
            raise Denied("the page changed since the plan was made")
        field = next((f for f in form.fields if f.field_key == action.field_key), None)
        if field is None:
            raise Denied("the field is not in the current form model")
        if not field.visible:
            raise Denied("the field is not visible")
        if action.kind == "upload":
            if field.type != FieldType.file:
                raise Denied("upload target is not a file input")
            if action.target not in self.documents:
                raise Denied("the document is not on the approved list")
            return
        if action.field_key in self.answers:
            expected = self.answers[action.field_key]
        elif action.field_key in self.consents:
            expected = self.consents[action.field_key]
        else:
            raise Denied("the value does not come from the payload")
        if normalize_value(field.type, expected) != normalize_value(field.type, action.value):
            raise Denied("the value differs from the payload")
