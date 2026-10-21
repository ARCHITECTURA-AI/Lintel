"""Model provider interface.

Two roles from the PRD, extractor and drafter, plus the verifier. What each one sees is fixed
here, in code:

  field mapper   sees field labels, types, options and fact-handle names; never values or page prose
  drafter        sees the job description and the cited facts for one question; never contact details
  verifier       sees one sentence and its cited facts; never the job description
  policy gate    is not a model
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lintel_schemas import VerifierVerdict


@dataclass
class FactSummary:
    """What a model may know about a fact. No contact details ever reach this type."""

    id: str
    kind: str
    claim_scope: str
    statement: str
    skills: list[str] = field(default_factory=list)
    employer: str | None = None
    proficiency: str | None = None
    start: str | None = None  # "2023-06"
    end: str | None = None  # "2024-08" or "present"


@dataclass
class RequirementOut:
    text: str
    importance: str  # must | nice


@dataclass
class AssessmentOut:
    status: str  # met | gap | uncertain
    evidence_fact_ids: list[str]
    note: str
    interview_question: str | None = None


@dataclass
class FieldSpec:
    field_key: str
    label: str
    type: str
    options: list[str]
    required: bool


@dataclass
class HandleSpec:
    handle: str
    description: str


@dataclass
class MappingOut:
    field_key: str
    decision: str  # handle | draft_needed | ask_user | skip
    handle: str | None
    category: str
    reason: str


@dataclass
class SentenceOut:
    text: str
    fact_ids: list[str]


@dataclass
class VariantBulletOut:
    bullet_id: str
    text: str  # reworded text, or the original
    reason: str


@dataclass
class ResumeFactOut:
    kind: str
    claim_scope: str
    statement: str
    attributes: dict[str, Any]
    source_ref: str


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class Provider(Protocol):
    name: str

    def extract_requirements(self, title: str, description: str) -> list[RequirementOut]: ...

    def assess_requirements(
        self, requirements: list[RequirementOut], facts: list[FactSummary]
    ) -> list[AssessmentOut]: ...

    def map_fields(self, fields: list[FieldSpec], handles: list[HandleSpec]) -> list[MappingOut]: ...

    def draft_answer(
        self,
        *,
        question: str,
        company: str,
        title: str,
        description: str,
        facts: list[FactSummary],
        max_chars: int | None,
        feedback: list[str] | None = None,
    ) -> list[SentenceOut]: ...

    def verify(self, sentence: str, facts: list[FactSummary]) -> tuple[VerifierVerdict, str]: ...

    def propose_variant(
        self, bullets: list[dict[str, Any]], requirements: list[str], facts: list[FactSummary]
    ) -> list[VariantBulletOut]: ...

    def interview_question(self, requirement: str, facts: list[FactSummary]) -> str: ...

    def extract_resume_facts(self, redacted_text: str) -> list[ResumeFactOut]: ...

    def last_usage(self) -> list[Usage]: ...
