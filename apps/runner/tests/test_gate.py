"""The policy gate is plain code between the planner and the page. These are its rules."""

from __future__ import annotations

import pytest
from lintel_runner.gate import Action, Denied, PolicyGate
from lintel_schemas import (
    CanonicalPayload,
    Destination,
    FieldType,
    FormField,
    FormModel,
    PayloadAnswer,
    PayloadConsent,
    PayloadDocument,
    Platform,
    RunKind,
    SupportMode,
)

DOC = "d" * 64
PAYLOAD = CanonicalPayload(
    application_id="app",
    destination=Destination(platform=Platform.greenhouse, job_identity="gh:acme:4412", host="lab.test"),
    profile_version_id="pv",
    answers=[PayloadAnswer(field_key="fk_name", value="Riya Sharma"), PayloadAnswer(field_key="fk_auth", value="1")],
    documents=[PayloadDocument(role="resume", sha256=DOC, field_key="fk_resume")],
    consents=[PayloadConsent(field_key="fk_privacy", value=True)],
)
FORM = FormModel(
    url="http://lab.test/apply", host="lab.test", page_version="v1",
    fields=[
        FormField(field_key="fk_name", label="Full name", type=FieldType.text),
        FormField(field_key="fk_auth", label="Authorized?", type=FieldType.select),
        FormField(field_key="fk_resume", label="Resume", type=FieldType.file),
        FormField(field_key="fk_privacy", label="Privacy", type=FieldType.checkbox, is_consent=True),
        FormField(field_key="fk_note", label="Anything else?", type=FieldType.textarea),
        FormField(field_key="fk_hidden", label="Hidden", type=FieldType.text, visible=False),
    ],
)


def gate(kind=RunKind.fill, mode=SupportMode.assisted_fill) -> PolicyGate:
    return PolicyGate(kind=kind, mode=mode, payload=PAYLOAD, allowed_hosts=["lab.test"], permitted_paths=["/"])


def test_values_must_come_from_the_payload():
    g = gate()
    g.check(Action("fill", "fk_name", "Riya Sharma"), FORM)
    with pytest.raises(Denied, match="differs"):
        g.check(Action("fill", "fk_name", "Someone Else"), FORM)
    with pytest.raises(Denied, match="payload"):
        g.check(Action("fill", "fk_note", "anything"), FORM)


def test_assisted_fill_has_no_submit_tool():
    g = gate(RunKind.submit, SupportMode.assisted_fill)
    g.guard_passed = True
    with pytest.raises(Denied, match="not available"):
        g.check(Action("click_submit"), FORM)


def test_approved_submission_clicks_only_after_the_guard():
    g = gate(RunKind.submit, SupportMode.approved_submission)
    with pytest.raises(Denied, match="Guard"):
        g.check(Action("click_submit"), FORM)
    g.guard_passed = True
    g.check(Action("click_submit"), FORM)


def test_a_fill_run_never_clicks_submit():
    g = gate(RunKind.fill, SupportMode.approved_submission)
    g.guard_passed = True
    with pytest.raises(Denied):
        g.check(Action("click_submit"), FORM)


def test_uploads_are_matched_by_hash():
    g = gate()
    g.check(Action("upload", "fk_resume", target=DOC), FORM)
    with pytest.raises(Denied, match="approved list"):
        g.check(Action("upload", "fk_resume", target="e" * 64), FORM)
    with pytest.raises(Denied, match="file input"):
        g.check(Action("upload", "fk_name", target=DOC), FORM)


def test_navigation_stays_on_registry_hosts():
    g = gate()
    g.check(Action("navigate", target="http://lab.test/apply"), FORM)
    with pytest.raises(Denied, match="registry"):
        g.check(Action("navigate", target="http://evil.example/collect"), FORM)


def test_hidden_fields_and_stale_plans_are_refused():
    g = gate()
    with pytest.raises(Denied, match="visible"):
        PolicyGate(kind=RunKind.fill, mode=SupportMode.assisted_fill,
                   payload=PAYLOAD.model_copy(update={"answers": [*PAYLOAD.answers, PayloadAnswer(field_key="fk_hidden", value="x")]}),
                   allowed_hosts=["lab.test"], permitted_paths=["/"]).check(Action("fill", "fk_hidden", "x"), FORM)
    with pytest.raises(Denied, match="page changed"):
        g.check(Action("fill", "fk_name", "Riya Sharma"), FORM, planned_version="v0")


def test_draft_only_has_no_tools():
    g = gate(RunKind.read_form, SupportMode.draft_only)
    assert g.tools() == set()
