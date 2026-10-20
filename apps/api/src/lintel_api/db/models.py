"""ORM mapping of the schema in sql/0001_initial.sql.

The SQL file is the source of truth (it carries the RLS policies, triggers and functions);
tests/test_migrations.py checks that these classes and the migrated database agree.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def owner() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


def created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, server_default="")
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    weekly_budget: Mapped[int] = mapped_column(Integer, server_default="5")
    no_reply_days: Mapped[int] = mapped_column(Integer, server_default="14")
    hard_filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    targets: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    onboarding: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    model_daily_cap_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default="2.00")
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created()


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    token_hash: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class RunnerDevice(Base):
    __tablename__ = "runner_devices"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    name: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text, server_default="")
    runner_version: Mapped[str] = mapped_column(Text, server_default="")
    token_hash: Mapped[str] = mapped_column(Text)
    paired_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    kind: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created()
    deleted_at: Mapped[datetime | None]


class FactCandidate(Base):
    __tablename__ = "fact_candidates"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    claim_scope: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    source_ref: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    fact_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()
    decided_at: Mapped[datetime | None]


class ProfileFact(Base):
    __tablename__ = "profile_facts"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    kind: Mapped[str] = mapped_column(Text)
    claim_scope: Mapped[str] = mapped_column(Text)
    statement: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    source_type: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text, server_default="")
    supersedes_fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profile_facts.id"))
    retracted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    application_scope_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = created()


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    fact_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    fact_set_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class WatchlistCompany(Base):
    __tablename__ = "watchlist_companies"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    name: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    board_name: Mapped[str] = mapped_column(Text)
    careers_url: Mapped[str] = mapped_column(Text)
    api_base: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text, server_default="global")
    company_size: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_synced_at: Mapped[datetime | None]
    last_sync_status: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    job_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = created()


class Destination(Base):
    __tablename__ = "destinations"
    id: Mapped[uuid.UUID] = pk()
    domain: Mapped[str] = mapped_column(Text)
    permitted_paths: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    platform: Mapped[str] = mapped_column(Text)
    adapter_version: Mapped[str] = mapped_column(Text, server_default="1")
    support_mode: Mapped[str] = mapped_column(Text, server_default="draft_only")
    bot_challenge_seen: Mapped[bool] = mapped_column(Boolean, server_default="false")
    bot_challenge_seen_at: Mapped[datetime | None]
    policy_review_status: Mapped[str] = mapped_column(Text, server_default="pending")
    policy_review_date: Mapped[date | None] = mapped_column(Date)
    known_limitations: Mapped[str] = mapped_column(Text, server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    asset_hosts: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    updated_at: Mapped[datetime] = created()


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    watchlist_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("watchlist_companies.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(Text)
    board_name: Mapped[str] = mapped_column(Text)
    posting_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    company_name: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text, server_default="")
    workplace: Mapped[str] = mapped_column(Text, server_default="")
    department: Mapped[str] = mapped_column(Text, server_default="")
    employment_type: Mapped[str] = mapped_column(Text, server_default="")
    description: Mapped[str] = mapped_column(Text, server_default="")
    apply_url: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    comp_min: Mapped[Decimal | None] = mapped_column(Numeric)
    comp_max: Mapped[Decimal | None] = mapped_column(Numeric)
    comp_currency: Mapped[str | None] = mapped_column(Text)
    comp_interval: Mapped[str | None] = mapped_column(Text)
    questions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    target_match: Mapped[bool] = mapped_column(Boolean, server_default="false")
    match_reason: Mapped[str] = mapped_column(Text, server_default="")
    content_hash: Mapped[str] = mapped_column(Text, server_default="")
    first_seen_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    closed_at: Mapped[datetime | None]


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    destination_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("destinations.id"))
    support_mode: Mapped[str] = mapped_column(Text, server_default="draft_only")
    state: Mapped[str] = mapped_column(Text, server_default="imported")
    fit_label: Mapped[str | None] = mapped_column(Text)
    fit_score: Mapped[float | None] = mapped_column(Float)
    fit_brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fit_generated_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]
    week_budget_slot: Mapped[date | None] = mapped_column(Date)
    profile_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profile_versions.id"))
    resume_variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resume_variants.id"))
    form_model: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    form_source: Mapped[str | None] = mapped_column(Text)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload_hash: Mapped[str | None] = mapped_column(Text)
    fence: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cancel_requested_at: Mapped[datetime | None]
    state_changed_at: Mapped[datetime] = created()
    submitted_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class AnswerDraft(Base):
    __tablename__ = "answer_drafts"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    field_key: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    field_type: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    options: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    max_length: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    category: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(Text)
    value: Mapped[Any | None] = mapped_column(JSONB)
    original_value: Mapped[Any | None] = mapped_column(JSONB)
    sentences: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    fact_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    status_detail: Mapped[str] = mapped_column(Text, server_default="")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    edited_by_user: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class UserTask(Base):
    __tablename__ = "user_tasks"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, server_default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="open")
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ResumeVariant(Base):
    __tablename__ = "resume_variants"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    base_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    diff: Mapped[list[Any]] = mapped_column(JSONB)
    bullets: Mapped[list[Any]] = mapped_column(JSONB)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    document_sha256: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="proposed")
    check_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    approved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class ApplicationRun(Base):
    __tablename__ = "application_runs"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, server_default="queued")
    runner_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runner_devices.id"))
    payload_hash: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    ended_reason: Mapped[str | None] = mapped_column(Text)
    waiting_reason: Mapped[str | None] = mapped_column(Text)
    resumed_from_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("application_runs.id"))
    action_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = created()


class RunStep(Base):
    __tablename__ = "run_steps"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = owner()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    field_key: Mapped[str | None] = mapped_column(Text)
    value_hash: Mapped[str | None] = mapped_column(Text)
    value_len: Mapped[int | None] = mapped_column(Integer)
    verification: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = created()


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    payload_hash: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    runner_device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runner_devices.id"))
    approved_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text)
    key_id: Mapped[str] = mapped_column(Text)


class SubmitIntent(Base):
    __tablename__ = "submit_intents"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    fence: Mapped[int] = mapped_column(BigInteger)
    payload_hash: Mapped[str] = mapped_column(Text)
    runner_device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runner_devices.id"))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_records.id"))
    mode: Mapped[str] = mapped_column(Text, server_default="assisted_fill")
    created_at: Mapped[datetime] = created()


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, server_default="")
    reference_number: Mapped[str | None] = mapped_column(Text)
    page_hash: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    created_at: Mapped[datetime] = created()


class OutcomeEvent(Base):
    __tablename__ = "outcome_events"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence.id"))
    fence: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(Text, server_default="")
    occurred_at: Mapped[datetime] = created()
    created_at: Mapped[datetime] = created()


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    name: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(Text, server_default="acquaintance")
    email: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class FollowUp(Base):
    __tablename__ = "follow_ups"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, server_default="follow_up")
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    due_at: Mapped[datetime]
    draft: Mapped[str] = mapped_column(Text, server_default="")
    draft_sentences: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    status: Mapped[str] = mapped_column(Text, server_default="scheduled")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    sent_at: Mapped[datetime | None]


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, server_default="")
    link: Mapped[str] = mapped_column(Text, server_default="/")
    urgent: Mapped[bool] = mapped_column(Boolean, server_default="false")
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    read_at: Mapped[datetime | None]
    emailed_at: Mapped[datetime | None]
    pushed_at: Mapped[datetime | None]


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = owner()
    to_address: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    sent_at: Mapped[datetime | None]


class WorkItem(Base):
    __tablename__ = "work_queue"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = owner()
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    run_after: Mapped[datetime] = created()
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None]
    failed_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class ModelUsage(Base):
    __tablename__ = "model_usage"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = owner()
    role: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default="0")
    created_at: Mapped[datetime] = created()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = owner()
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str] = mapped_column(Text, server_default="")
    subject_id: Mapped[str] = mapped_column(Text, server_default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = created()
