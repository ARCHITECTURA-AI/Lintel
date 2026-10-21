"""Typed models for facts, forms, payloads, approvals, runs, fit briefs and claim checks."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    AnswerCategory,
    CheckOutcome,
    ClaimScope,
    FactKind,
    FieldType,
    FitLabel,
    MappingDecisionKind,
    Platform,
    Recommendation,
    RequirementStatus,
    RunKind,
    SourceType,
    SupportMode,
    VerifierVerdict,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class FactAttributes(BaseModel):
    """Structured parts of a fact. All optional; the statement is what the user confirmed."""

    model_config = ConfigDict(extra="allow")

    field: str | None = None  # contact / link / eligibility / preference key, e.g. "email"
    value: str | None = None
    employer: str | None = None
    title: str | None = None
    school: str | None = None
    degree: str | None = None
    issuer: str | None = None
    start: str | None = None  # "2023-06"
    end: str | None = None  # "2024-08" or "present"
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    proficiency: Literal["familiar", "working", "expert"] | None = None
    country: str | None = None  # eligibility facts are per country
    parent_fact_id: str | None = None  # an achievement belongs to a role or project


class Fact(BaseModel):
    id: str
    kind: FactKind
    claim_scope: ClaimScope
    statement: str
    attributes: FactAttributes = Field(default_factory=FactAttributes)
    source_type: SourceType
    source_ref: str = ""
    supersedes_fact_id: str | None = None
    retracted: bool = False
    application_scope_id: str | None = None  # None means reusable across applications
    created_at: datetime | None = None


class FactHandle(BaseModel):
    """A name the field mapper may use. The mapper never sees the value."""

    handle: str  # e.g. "contact.email", "work[0].employer", "eligibility.sponsorship.US"
    description: str
    category: AnswerCategory
    fact_id: str


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------


class FieldOption(Strict):
    label: str
    value: str


class Locator(Strict):
    """How the runner finds a field again. Never shown to a model."""

    css: str | None = None
    role: str | None = None
    name: str | None = None


class FormField(Strict):
    field_key: str  # hash of section, label and type
    section: str = ""
    label: str
    type: FieldType
    required: bool = False
    options: list[FieldOption] = Field(default_factory=list)
    max_length: int | None = None
    visible: bool = True
    step: int = 0
    is_consent: bool = False
    accept: str | None = None  # file input accept attribute
    locator: Locator | None = None


class FormModel(Strict):
    url: str
    host: str
    page_version: str  # hash of the ordered field keys
    fields: list[FormField]
    steps: int = 1
    has_submit: bool = True
    bot_challenge: bool = False
    login_wall: bool = False
    source: Literal["feed", "runner"] = "runner"


class MappingDecision(Strict):
    field_key: str
    decision: MappingDecisionKind
    handle: str | None = None
    category: AnswerCategory = AnswerCategory.unknown
    reason: str = ""


# ---------------------------------------------------------------------------
# Canonical payload and approvals
# ---------------------------------------------------------------------------


class Destination(Strict):
    platform: Platform
    job_identity: str  # "gh:acme:4412"
    host: str


class PayloadAnswer(Strict):
    field_key: str
    value: Any  # str, bool or list[str]
    fact_ids: list[str] = Field(default_factory=list)


class PayloadDocument(Strict):
    role: str  # "resume", "cover_letter"
    sha256: str
    field_key: str | None = None


class PayloadConsent(Strict):
    field_key: str
    value: bool


class CanonicalPayload(Strict):
    """What an approval covers. Page structure is deliberately not part of it."""

    application_id: str
    destination: Destination
    profile_version_id: str
    answers: list[PayloadAnswer]
    documents: list[PayloadDocument] = Field(default_factory=list)
    consents: list[PayloadConsent] = Field(default_factory=list)
    action: Literal["submit"] = "submit"


class SignedApproval(Strict):
    approval_id: str
    application_id: str
    payload_hash: str
    runner_device_id: str
    expires_at: datetime
    signature: str  # base64url Ed25519 over the canonical claims
    key_id: str = "lintel-1"


class SignedFillGrant(Strict):
    """Pins the payload a fill run may type. The runner refuses values from anywhere else."""

    run_id: str
    application_id: str
    payload_hash: str
    runner_device_id: str
    expires_at: datetime
    signature: str
    key_id: str = "lintel-1"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunStepRecord(Strict):
    seq: int
    action: str  # read_form, fill, select, check, upload, verify, pause, guard_check, ...
    field_key: str | None = None
    value_hash: str | None = None
    value_len: int | None = None
    verification: Literal["ok", "mismatch", "error", "skipped", "blocked"] = "ok"
    detail: str = ""


class RunAssignment(BaseModel):
    """Everything a runner needs for one run. Values arrive only with a signed grant."""

    run_id: str
    kind: RunKind
    application_id: str
    apply_url: str
    support_mode: SupportMode
    allowed_hosts: list[str]
    permitted_paths: list[str] = Field(default_factory=list)
    payload: CanonicalPayload | None = None
    payload_hash: str | None = None
    fill_grant: SignedFillGrant | None = None
    approval: SignedApproval | None = None
    field_labels: dict[str, str] = Field(default_factory=dict)
    handles: dict[str, str] = Field(default_factory=dict)  # field_key -> handle, for the step log only
    documents: list[dict[str, Any]] = Field(default_factory=list)  # role, sha256, filename, download path
    limits: dict[str, int] = Field(default_factory=dict)


class GuardFieldDiff(BaseModel):
    field_key: str
    label: str
    approved: Any
    live: Any


class GuardCheckResult(BaseModel):
    ok: bool
    reasons: list[str] = Field(default_factory=list)
    diffs: list[GuardFieldDiff] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fit brief
# ---------------------------------------------------------------------------


class Requirement(BaseModel):
    text: str
    importance: Literal["must", "nice"] = "must"
    status: RequirementStatus
    evidence_fact_ids: list[str] = Field(default_factory=list)
    note: str = ""
    interview_question: str | None = None


class FilterConflict(BaseModel):
    filter: str
    detail: str
    severity: Literal["hard", "soft"] = "hard"


class FitBrief(BaseModel):
    summary: str
    label: FitLabel
    score: float
    recommendation: Recommendation
    recommendation_reason: str
    requirements: list[Requirement]
    conflicts: list[FilterConflict] = Field(default_factory=list)
    compensation: str | None = None
    location: str | None = None


# ---------------------------------------------------------------------------
# Claim check
# ---------------------------------------------------------------------------


class CheckResult(BaseModel):
    name: Literal["token", "scope", "verifier"]
    outcome: CheckOutcome
    detail: str = ""
    offending: list[str] = Field(default_factory=list)
    verdict: VerifierVerdict | None = None


class SentenceCheck(BaseModel):
    passed: bool
    checks: list[CheckResult]

    @property
    def first_failure(self) -> CheckResult | None:
        return next((c for c in self.checks if c.outcome == CheckOutcome.failed), None)


class DraftSentence(BaseModel):
    text: str
    supporting_fact_ids: list[str] = Field(default_factory=list)
    check: SentenceCheck | None = None


class GroundedDraft(BaseModel):
    field_key: str
    sentences: list[DraftSentence]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.sentences if s.text.strip())


# ---------------------------------------------------------------------------
# Résumé variants
# ---------------------------------------------------------------------------


class ResumeBullet(BaseModel):
    id: str
    section: str
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class VariantChange(BaseModel):
    bullet_id: str
    kind: Literal["moved", "reworded", "unchanged"]
    before: str
    after: str
    from_index: int
    to_index: int
    reason: str = ""
    check: SentenceCheck | None = None
