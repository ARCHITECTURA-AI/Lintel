"""Initial schema: ledger, lifecycle, runs, approvals, intents, outcomes, RLS.

Revision ID: 0001
"""

from pathlib import Path

from alembic import op
from lintel_schemas import RUN_TRANSITIONS, TERMINAL_STATES, TRANSITIONS

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[2] / "sql" / "0001_initial.sql"

TABLES = [
    "audit_events", "model_usage", "work_queue", "email_outbox", "push_subscriptions", "notifications",
    "follow_ups", "contacts", "outcome_events", "evidence", "submit_intents", "approval_records",
    "run_steps", "application_runs", "resume_variants", "user_tasks", "answer_drafts",
    "application_events", "applications", "run_transitions", "lifecycle_terminal_states",
    "lifecycle_transitions", "jobs", "destinations", "watchlist_companies", "profile_versions",
    "profile_facts", "fact_candidates", "documents", "device_pairings", "runner_devices", "sessions", "users",
]


def upgrade() -> None:
    op.execute(SQL.read_text())
    # The state machines live in lintel_schemas; the database enforces the same tables.
    rows = ",".join(f"('{src.value}', '{dst.value}')" for src, dsts in TRANSITIONS.items() for dst in dsts)
    op.execute(f"INSERT INTO lifecycle_transitions (from_state, to_state) VALUES {rows}")
    rows = ",".join(f"('{s.value}')" for s in TERMINAL_STATES)
    op.execute(f"INSERT INTO lifecycle_terminal_states (state) VALUES {rows}")
    rows = ",".join(f"('{src.value}', '{dst.value}')" for src, dsts in RUN_TRANSITIONS.items() for dst in dsts)
    op.execute(f"INSERT INTO run_transitions (from_state, to_state) VALUES {rows}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS current_facts")
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for fn in [
        "app_user_id", "forbid_mutation", "check_fact_supersession", "applications_lifecycle_guard",
        "applications_record_transition", "runs_state_guard", "submit_intent_guard", "begin_submit",
        "record_submit_outcome", "mark_submission_uncertain", "auth_register", "auth_lookup",
        "auth_create_session", "auth_session_user", "auth_device", "pairing_start", "pairing_approve",
        "pairing_complete", "claim_work", "scheduler_user_ids", "report_bot_challenge", "retention_purge",
        "erase_user",
    ]:
        op.execute(f"DROP FUNCTION IF EXISTS {fn} CASCADE")
