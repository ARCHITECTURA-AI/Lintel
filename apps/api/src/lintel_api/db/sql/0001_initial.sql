-- Lintel initial schema.
--
-- Every user table carries user_id and row-level security keyed on app.user_id, which the API
-- sets per transaction. The rules that protect the product's promise are enforced here, by the
-- database, not by code review:
--   * one active run per application (partial unique index)
--   * submit_intents unique on (application_id, fence)
--   * consuming an approval and recording the submit intent happen in one transaction
--   * outcome_events and profile_facts reject updates and deletes (erasure has its own path)
--   * terminal lifecycle states are never overwritten; every transition names an actor

CREATE EXTENSION IF NOT EXISTS citext;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lintel_app') THEN
    CREATE ROLE lintel_app NOLOGIN;
  END IF;
END
$$;

-- Don't rely on the default grant on the public schema: a recreated schema has none.
GRANT USAGE ON SCHEMA public TO lintel_app;

-- The current user for row-level security. NULL when unset, which matches no rows.
CREATE FUNCTION app_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

-- ---------------------------------------------------------------------------
-- Accounts, sessions, devices
-- ---------------------------------------------------------------------------

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext NOT NULL UNIQUE,
  password_hash text NOT NULL,
  full_name text NOT NULL DEFAULT '',
  timezone text NOT NULL DEFAULT 'UTC',
  weekly_budget integer NOT NULL DEFAULT 5 CHECK (weekly_budget BETWEEN 0 AND 50),
  no_reply_days integer NOT NULL DEFAULT 14 CHECK (no_reply_days BETWEEN 3 AND 90),
  hard_filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  targets jsonb NOT NULL DEFAULT '{}'::jsonb,
  notification_prefs jsonb NOT NULL DEFAULT '{"email": true, "push": false, "digest": "daily"}'::jsonb,
  onboarding jsonb NOT NULL DEFAULT '{}'::jsonb,
  model_daily_cap_usd numeric(8, 2) NOT NULL DEFAULT 2.00,
  is_admin boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE,
  user_agent text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);
CREATE INDEX sessions_user ON sessions (user_id);

CREATE TABLE runner_devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name text NOT NULL,
  platform text NOT NULL DEFAULT '',
  runner_version text NOT NULL DEFAULT '',
  token_hash text NOT NULL UNIQUE,
  paired_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz,
  revoked_at timestamptz
);
CREATE INDEX runner_devices_user ON runner_devices (user_id);

-- Pairing happens before the runner knows its user, so this table is reachable only through
-- the SECURITY DEFINER functions below. It has no user_id until a signed-in user approves it.
CREATE TABLE device_pairings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_code_hash text NOT NULL UNIQUE,
  user_code text NOT NULL UNIQUE,
  device_name text NOT NULL,
  platform text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  approved_by uuid REFERENCES users (id) ON DELETE CASCADE,
  approved_at timestamptz,
  device_id uuid REFERENCES runner_devices (id) ON DELETE CASCADE,
  delivered_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Documents and the fact ledger
-- ---------------------------------------------------------------------------

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('resume_base', 'resume_variant', 'attachment', 'evidence')),
  filename text NOT NULL,
  content_type text NOT NULL,
  size_bytes integer NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  storage_key text NOT NULL,
  parsed jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE INDEX documents_user ON documents (user_id, kind);

CREATE TABLE fact_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  document_id uuid REFERENCES documents (id) ON DELETE CASCADE,
  kind text NOT NULL,
  claim_scope text NOT NULL,
  statement text NOT NULL,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_ref text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'rejected')),
  fact_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz
);
CREATE INDEX fact_candidates_user ON fact_candidates (user_id, status);

CREATE TABLE profile_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('contact', 'link', 'role', 'achievement', 'skill', 'education',
                                     'certification', 'eligibility', 'preference', 'demographic')),
  claim_scope text NOT NULL CHECK (claim_scope IN ('employment', 'project', 'coursework', 'education',
                                                   'certification', 'personal')),
  statement text NOT NULL CHECK (length(statement) BETWEEN 1 AND 2000),
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_type text NOT NULL CHECK (source_type IN ('resume', 'user_entry', 'user_interview')),
  source_ref text NOT NULL DEFAULT '',
  supersedes_fact_id uuid REFERENCES profile_facts (id),
  retracted boolean NOT NULL DEFAULT false,
  application_scope_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX profile_facts_user ON profile_facts (user_id);
-- History is a chain, never a fork: a fact is superseded at most once.
CREATE UNIQUE INDEX profile_facts_single_successor ON profile_facts (supersedes_fact_id)
  WHERE supersedes_fact_id IS NOT NULL;

CREATE VIEW current_facts WITH (security_invoker = true) AS
  SELECT f.*
  FROM profile_facts f
  WHERE NOT f.retracted
    AND NOT EXISTS (SELECT 1 FROM profile_facts s WHERE s.supersedes_fact_id = f.id);

CREATE TABLE profile_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  fact_ids uuid[] NOT NULL,
  fact_set_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, fact_set_hash)
);

-- ---------------------------------------------------------------------------
-- Discovery: watchlist, destination registry, jobs
-- ---------------------------------------------------------------------------

CREATE TABLE watchlist_companies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name text NOT NULL,
  platform text NOT NULL CHECK (platform IN ('greenhouse', 'lever', 'ashby')),
  board_name text NOT NULL,
  careers_url text NOT NULL,
  api_base text,
  region text NOT NULL DEFAULT 'global',
  company_size text CHECK (company_size IN ('1-50', '51-200', '201-1000', '1000+')),
  active boolean NOT NULL DEFAULT true,
  last_synced_at timestamptz,
  last_sync_status text,
  last_error text,
  etag text,
  content_hash text,
  job_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, platform, board_name)
);

-- The destination registry decides the support mode, never a model. It is shared reference
-- data rather than user data, so it is the one table without user_id: everyone may read it and
-- only administrators may change it.
CREATE TABLE destinations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  domain text NOT NULL UNIQUE,
  permitted_paths text[] NOT NULL DEFAULT '{}',
  platform text NOT NULL,
  adapter_version text NOT NULL DEFAULT '1',
  support_mode text NOT NULL DEFAULT 'draft_only'
    CHECK (support_mode IN ('draft_only', 'assisted_fill', 'approved_submission')),
  bot_challenge_seen boolean NOT NULL DEFAULT false,
  bot_challenge_seen_at timestamptz,
  policy_review_status text NOT NULL DEFAULT 'pending'
    CHECK (policy_review_status IN ('pending', 'approved', 'rejected')),
  policy_review_date date,
  known_limitations text NOT NULL DEFAULT '',
  enabled boolean NOT NULL DEFAULT false,
  disabled_reason text,
  asset_hosts text[] NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- Agent-clicked submit only on reviewed destinations with no bot challenge.
  CONSTRAINT approved_submission_needs_review CHECK (
    support_mode <> 'approved_submission'
    OR (policy_review_status = 'approved' AND NOT bot_challenge_seen AND enabled)
  ),
  CONSTRAINT fill_needs_review CHECK (
    support_mode = 'draft_only' OR (policy_review_status = 'approved' AND enabled)
  )
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  watchlist_company_id uuid REFERENCES watchlist_companies (id) ON DELETE SET NULL,
  platform text NOT NULL,
  board_name text NOT NULL,
  posting_id text NOT NULL,
  title text NOT NULL,
  company_name text NOT NULL,
  location text NOT NULL DEFAULT '',
  workplace text NOT NULL DEFAULT '',
  department text NOT NULL DEFAULT '',
  employment_type text NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  apply_url text NOT NULL,
  host text NOT NULL,
  comp_min numeric,
  comp_max numeric,
  comp_currency text,
  comp_interval text,
  questions jsonb,
  target_match boolean NOT NULL DEFAULT false,
  match_reason text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz,
  UNIQUE (user_id, platform, board_name, posting_id)
);
CREATE INDEX jobs_user_open ON jobs (user_id) WHERE closed_at IS NULL;

-- ---------------------------------------------------------------------------
-- Applications (lifecycle only) and their transitions
-- ---------------------------------------------------------------------------

CREATE TABLE lifecycle_transitions (
  from_state text NOT NULL,
  to_state text NOT NULL,
  PRIMARY KEY (from_state, to_state)
);
CREATE TABLE lifecycle_terminal_states (state text PRIMARY KEY);
CREATE TABLE run_transitions (
  from_state text NOT NULL,
  to_state text NOT NULL,
  PRIMARY KEY (from_state, to_state)
);

CREATE TABLE applications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
  destination_id uuid REFERENCES destinations (id),
  support_mode text NOT NULL DEFAULT 'draft_only'
    CHECK (support_mode IN ('draft_only', 'assisted_fill', 'approved_submission')),
  state text NOT NULL DEFAULT 'imported',
  fit_label text CHECK (fit_label IN ('strong', 'possible', 'stretch', 'conflict')),
  fit_score real,
  fit_brief jsonb,
  fit_generated_at timestamptz,
  decided_at timestamptz,
  week_budget_slot date,
  profile_version_id uuid REFERENCES profile_versions (id),
  resume_variant_id uuid,
  form_model jsonb,
  form_source text CHECK (form_source IN ('feed', 'runner')),
  mapping jsonb,
  payload jsonb,
  payload_hash text,
  fence bigint NOT NULL DEFAULT 0,
  cancel_requested_at timestamptz,
  state_changed_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, job_id)
);
CREATE INDEX applications_user_state ON applications (user_id, state);
CREATE INDEX applications_budget ON applications (user_id, week_budget_slot);

ALTER TABLE profile_facts
  ADD CONSTRAINT profile_facts_application_scope_fk
  FOREIGN KEY (application_scope_id) REFERENCES applications (id) ON DELETE CASCADE;

CREATE TABLE application_events (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  from_state text,
  to_state text NOT NULL,
  actor text NOT NULL CHECK (actor IN ('user', 'system', 'worker', 'runner')),
  reason text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX application_events_app ON application_events (application_id, id);

-- ---------------------------------------------------------------------------
-- Drafting, tasks, résumé variants
-- ---------------------------------------------------------------------------

CREATE TABLE answer_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  field_key text NOT NULL,
  label text NOT NULL,
  field_type text NOT NULL,
  required boolean NOT NULL DEFAULT false,
  options jsonb NOT NULL DEFAULT '[]'::jsonb,
  max_length integer,
  position integer NOT NULL DEFAULT 0,
  category text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('handle', 'draft_needed', 'ask_user', 'skip')),
  handle text,
  value jsonb,
  original_value jsonb,
  sentences jsonb NOT NULL DEFAULT '[]'::jsonb,
  fact_ids uuid[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'ready', 'needs_user', 'blocked', 'skipped')),
  status_detail text NOT NULL DEFAULT '',
  attempts integer NOT NULL DEFAULT 0,
  edited_by_user boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (application_id, field_key)
);

CREATE TABLE user_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid REFERENCES applications (id) ON DELETE CASCADE,
  type text NOT NULL CHECK (type IN ('fact_interview', 'unknown_answer', 'claim_review', 'waiting_user',
                                     'guard_mismatch', 'confirm_submission', 'follow_up', 'referral')),
  title text NOT NULL,
  body text NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed')),
  dedupe_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  resolution jsonb
);
CREATE INDEX user_tasks_open ON user_tasks (user_id) WHERE status = 'open';
CREATE UNIQUE INDEX user_tasks_dedupe ON user_tasks (user_id, dedupe_key)
  WHERE status = 'open' AND dedupe_key IS NOT NULL;

CREATE TABLE resume_variants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid REFERENCES applications (id) ON DELETE CASCADE,
  base_document_id uuid NOT NULL REFERENCES documents (id),
  diff jsonb NOT NULL,
  bullets jsonb NOT NULL,
  document_id uuid REFERENCES documents (id),
  document_sha256 text,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'rejected')),
  check_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT approved_variant_has_document CHECK (
    status <> 'approved' OR (document_sha256 IS NOT NULL AND approved_at IS NOT NULL)
  )
);
ALTER TABLE applications
  ADD CONSTRAINT applications_resume_variant_fk
  FOREIGN KEY (resume_variant_id) REFERENCES resume_variants (id);

-- ---------------------------------------------------------------------------
-- Execution: runs, steps, approvals, intents, outcomes
-- ---------------------------------------------------------------------------

CREATE TABLE application_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('read_form', 'fill', 'submit')),
  state text NOT NULL DEFAULT 'queued',
  runner_device_id uuid REFERENCES runner_devices (id),
  payload_hash text,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  ended_reason text,
  waiting_reason text,
  resumed_from_run_id uuid REFERENCES application_runs (id),
  action_count integer NOT NULL DEFAULT 0 CHECK (action_count <= 50),
  created_at timestamptz NOT NULL DEFAULT now()
);
-- One active run per application.
CREATE UNIQUE INDEX one_active_run_per_application ON application_runs (application_id)
  WHERE state IN ('queued', 'running', 'waiting_user');
-- One running run per user.
CREATE UNIQUE INDEX one_running_run_per_user ON application_runs (user_id) WHERE state = 'running';

CREATE TABLE run_steps (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES application_runs (id) ON DELETE CASCADE,
  seq integer NOT NULL,
  action text NOT NULL,
  field_key text,
  value_hash text,
  value_len integer,
  verification text NOT NULL CHECK (verification IN ('ok', 'mismatch', 'error', 'skipped', 'blocked')),
  detail text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, seq)
);

CREATE TABLE approval_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  payload jsonb NOT NULL,
  runner_device_id uuid NOT NULL REFERENCES runner_devices (id),
  approved_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  revoked_at timestamptz,
  revoked_reason text,
  signature text NOT NULL,
  key_id text NOT NULL,
  CHECK (expires_at > approved_at),
  CHECK (consumed_at IS NULL OR revoked_at IS NULL)
);
-- At most one live approval per application.
CREATE UNIQUE INDEX one_live_approval ON approval_records (application_id)
  WHERE consumed_at IS NULL AND revoked_at IS NULL;

CREATE TABLE submit_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  fence bigint NOT NULL CHECK (fence > 0),
  payload_hash text NOT NULL,
  runner_device_id uuid REFERENCES runner_devices (id),
  approval_id uuid REFERENCES approval_records (id),
  mode text NOT NULL DEFAULT 'assisted_fill',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (application_id, fence)
);

CREATE TABLE evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('confirmation_text', 'screenshot', 'email', 'note')),
  text text NOT NULL DEFAULT '',
  reference_number text,
  page_hash text,
  document_id uuid REFERENCES documents (id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outcome_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  stage text NOT NULL CHECK (stage IN ('prepared', 'submitted', 'user_reported_submitted',
    'submission_uncertain', 'acknowledged', 'no_reply', 'rejected', 'recruiter_screen', 'interview',
    'final_round', 'offer', 'accepted', 'declined', 'withdrawn')),
  source text NOT NULL CHECK (source IN ('adapter', 'user', 'email', 'system')),
  evidence_id uuid REFERENCES evidence (id),
  fence bigint,
  note text NOT NULL DEFAULT '',
  occurred_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outcome_events_app ON outcome_events (application_id, occurred_at);
-- A repeat outcome write for the same fencing token is a no-op.
CREATE UNIQUE INDEX outcome_once_per_fence ON outcome_events (application_id, fence)
  WHERE fence IS NOT NULL;

-- ---------------------------------------------------------------------------
-- People, follow-ups, notifications
-- ---------------------------------------------------------------------------

CREATE TABLE contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name text NOT NULL,
  company text NOT NULL,
  relationship text NOT NULL DEFAULT 'acquaintance'
    CHECK (relationship IN ('former_colleague', 'friend', 'alum', 'recruiter', 'acquaintance', 'other')),
  email text,
  notes text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE follow_ups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  application_id uuid NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
  kind text NOT NULL DEFAULT 'follow_up' CHECK (kind IN ('follow_up', 'referral_ask')),
  contact_id uuid REFERENCES contacts (id) ON DELETE SET NULL,
  due_at timestamptz NOT NULL,
  draft text NOT NULL DEFAULT '',
  draft_sentences jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'ready', 'sent', 'dismissed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);
CREATE UNIQUE INDEX one_open_follow_up ON follow_ups (application_id, kind, coalesce(contact_id, '00000000-0000-0000-0000-000000000000'::uuid))
  WHERE status IN ('scheduled', 'ready');

CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind text NOT NULL,
  title text NOT NULL,
  body text NOT NULL DEFAULT '',
  link text NOT NULL DEFAULT '/',
  urgent boolean NOT NULL DEFAULT false,
  dedupe_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  emailed_at timestamptz,
  pushed_at timestamptz
);
CREATE INDEX notifications_user ON notifications (user_id, created_at DESC);
CREATE UNIQUE INDEX notifications_dedupe ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE TABLE push_subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  endpoint text NOT NULL UNIQUE,
  p256dh text NOT NULL,
  auth text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE email_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  to_address text NOT NULL,
  subject text NOT NULL,
  body_text text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'logged')),
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Queue, model spend, audit
-- ---------------------------------------------------------------------------

-- Durable and transactional with state changes. Claimed with FOR UPDATE SKIP LOCKED.
CREATE TABLE work_queue (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  run_after timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0,
  max_attempts integer NOT NULL DEFAULT 3,
  locked_at timestamptz,
  locked_by text,
  done_at timestamptz,
  failed_at timestamptz,
  last_error text,
  dedupe_key text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX work_queue_ready ON work_queue (run_after) WHERE done_at IS NULL AND failed_at IS NULL;
CREATE UNIQUE INDEX work_queue_dedupe ON work_queue (dedupe_key)
  WHERE done_at IS NULL AND failed_at IS NULL AND dedupe_key IS NOT NULL;

CREATE TABLE model_usage (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  role text NOT NULL,
  provider text NOT NULL,
  model text NOT NULL,
  input_tokens integer NOT NULL DEFAULT 0,
  output_tokens integer NOT NULL DEFAULT 0,
  cost_usd numeric(10, 6) NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_usage_user_day ON model_usage (user_id, created_at);

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  actor text NOT NULL,
  action text NOT NULL,
  subject_type text NOT NULL DEFAULT '',
  subject_id text NOT NULL DEFAULT '',
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_user ON audit_events (user_id, id DESC);

-- ---------------------------------------------------------------------------
-- Append-only tables
-- ---------------------------------------------------------------------------

CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- The documented erasure and retention paths set lintel.erasure inside their own transaction.
  IF TG_OP = 'DELETE' AND current_setting('lintel.erasure', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'LN001', HINT = 'Write a new row instead. A correction is a new event.';
END;
$$;

CREATE TRIGGER profile_facts_append_only BEFORE UPDATE OR DELETE ON profile_facts
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER profile_versions_append_only BEFORE UPDATE OR DELETE ON profile_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER outcome_events_append_only BEFORE UPDATE OR DELETE ON outcome_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER application_events_append_only BEFORE UPDATE OR DELETE ON application_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER submit_intents_append_only BEFORE UPDATE OR DELETE ON submit_intents
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER run_steps_append_only BEFORE UPDATE OR DELETE ON run_steps
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- A fact can only be superseded by a fact of the same user.
CREATE FUNCTION check_fact_supersession() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.supersedes_fact_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM profile_facts WHERE id = NEW.supersedes_fact_id AND user_id = NEW.user_id
  ) THEN
    RAISE EXCEPTION 'a fact can only supersede a fact of the same user' USING ERRCODE = 'LN006';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER profile_facts_supersession BEFORE INSERT ON profile_facts
  FOR EACH ROW EXECUTE FUNCTION check_fact_supersession();

-- ---------------------------------------------------------------------------
-- Lifecycle guard: legal transitions only, terminal states never overwritten, and every
-- transition records its actor and reason.
-- ---------------------------------------------------------------------------

CREATE FUNCTION applications_lifecycle_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_actor text := nullif(current_setting('lintel.actor', true), '');
  v_reason text := nullif(current_setting('lintel.reason', true), '');
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.state NOT IN ('imported') THEN
      RAISE EXCEPTION 'applications start as imported, not %', NEW.state USING ERRCODE = 'LN002';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.fence < OLD.fence THEN
    RAISE EXCEPTION 'fencing token can only increase' USING ERRCODE = 'LN004';
  END IF;
  IF NEW.state IS DISTINCT FROM OLD.state THEN
    IF EXISTS (SELECT 1 FROM lifecycle_terminal_states WHERE state = OLD.state) THEN
      RAISE EXCEPTION 'application is % which is terminal; a correction is a new event', OLD.state
        USING ERRCODE = 'LN005';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM lifecycle_transitions WHERE from_state = OLD.state AND to_state = NEW.state
    ) THEN
      RAISE EXCEPTION 'illegal lifecycle transition % -> %', OLD.state, NEW.state USING ERRCODE = 'LN002';
    END IF;
    IF v_actor IS NULL OR v_reason IS NULL THEN
      RAISE EXCEPTION 'every lifecycle transition must record an actor and a reason' USING ERRCODE = 'LN002';
    END IF;
    NEW.state_changed_at := now();
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER applications_lifecycle BEFORE INSERT OR UPDATE ON applications
  FOR EACH ROW EXECUTE FUNCTION applications_lifecycle_guard();

CREATE FUNCTION applications_record_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO application_events (user_id, application_id, from_state, to_state, actor, reason)
    VALUES (NEW.user_id, NEW.id, NULL, NEW.state,
            coalesce(nullif(current_setting('lintel.actor', true), ''), 'system'),
            coalesce(nullif(current_setting('lintel.reason', true), ''), 'imported'));
  ELSIF NEW.state IS DISTINCT FROM OLD.state THEN
    INSERT INTO application_events (user_id, application_id, from_state, to_state, actor, reason)
    VALUES (NEW.user_id, NEW.id, OLD.state, NEW.state,
            current_setting('lintel.actor', true), current_setting('lintel.reason', true));
  END IF;
  RETURN NULL;
END;
$$;
CREATE TRIGGER applications_transition_log AFTER INSERT OR UPDATE ON applications
  FOR EACH ROW EXECUTE FUNCTION applications_record_transition();

CREATE FUNCTION runs_state_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state AND NOT EXISTS (
    SELECT 1 FROM run_transitions WHERE from_state = OLD.state AND to_state = NEW.state
  ) THEN
    RAISE EXCEPTION 'illegal run transition % -> %', OLD.state, NEW.state USING ERRCODE = 'LN002';
  END IF;
  IF NEW.state IN ('completed', 'failed', 'cancelled') AND NEW.ended_at IS NULL THEN
    NEW.ended_at := now();
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER runs_state BEFORE UPDATE ON application_runs
  FOR EACH ROW EXECUTE FUNCTION runs_state_guard();

-- ---------------------------------------------------------------------------
-- Exactly-once as far as it can be known
-- ---------------------------------------------------------------------------

-- A submit intent must be written in the same transaction that consumed its approval, for the
-- application's current fencing token.
CREATE FUNCTION submit_intent_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM applications
    WHERE id = NEW.application_id AND fence = NEW.fence AND state = 'submitting'
      AND payload_hash = NEW.payload_hash
  ) THEN
    RAISE EXCEPTION 'submit intent does not match the application''s fencing token and payload'
      USING ERRCODE = 'LN004';
  END IF;
  IF NEW.approval_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM approval_records
    WHERE id = NEW.approval_id AND consumed_at = now() AND payload_hash = NEW.payload_hash
  ) THEN
    RAISE EXCEPTION 'the approval must be consumed in the same transaction as the submit intent'
      USING ERRCODE = 'LN003';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER submit_intents_guard BEFORE INSERT ON submit_intents
  FOR EACH ROW EXECUTE FUNCTION submit_intent_guard();

-- Compare-and-set approved -> submitting, consume the approval and write the intent, atomically.
-- Returns the new fencing token. Runs as the caller, under row-level security.
CREATE FUNCTION begin_submit(
  p_application_id uuid,
  p_approval_id uuid,
  p_payload_hash text,
  p_device_id uuid,
  p_mode text DEFAULT 'assisted_fill'
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
  app applications%ROWTYPE;
  n integer;
  v_fence bigint;
BEGIN
  SELECT * INTO app FROM applications WHERE id = p_application_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'application not found' USING ERRCODE = 'LN003';
  END IF;
  IF app.cancel_requested_at IS NOT NULL THEN
    RAISE EXCEPTION 'application was cancelled' USING ERRCODE = 'LN003';
  END IF;
  IF app.state <> 'approved' THEN
    RAISE EXCEPTION 'application is %, not awaiting the click', app.state USING ERRCODE = 'LN003';
  END IF;
  IF app.payload_hash IS DISTINCT FROM p_payload_hash THEN
    RAISE EXCEPTION 'payload changed since approval' USING ERRCODE = 'LN003';
  END IF;
  IF EXISTS (SELECT 1 FROM jobs WHERE id = app.job_id AND closed_at IS NOT NULL) THEN
    RAISE EXCEPTION 'the job is no longer open' USING ERRCODE = 'LN003';
  END IF;

  UPDATE approval_records
     SET consumed_at = now()
   WHERE id = p_approval_id
     AND application_id = p_application_id
     AND payload_hash = p_payload_hash
     AND runner_device_id = p_device_id
     AND consumed_at IS NULL
     AND revoked_at IS NULL
     AND expires_at > now();
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN
    RAISE EXCEPTION 'approval is expired, consumed, revoked, or for another payload or device'
      USING ERRCODE = 'LN003';
  END IF;

  v_fence := app.fence + 1;
  PERFORM set_config('lintel.actor', 'runner', true);
  PERFORM set_config('lintel.reason', 'submit intent written before the click', true);
  UPDATE applications SET state = 'submitting', fence = v_fence, submitted_at = now()
   WHERE id = p_application_id;
  INSERT INTO submit_intents (user_id, application_id, fence, payload_hash, runner_device_id, approval_id, mode)
  VALUES (app.user_id, p_application_id, v_fence, p_payload_hash, p_device_id, p_approval_id, p_mode);
  RETURN v_fence;
END;
$$;

-- Write the outcome keyed by application and fencing token. A repeat write is a no-op; a stale
-- token is rejected.
CREATE FUNCTION record_submit_outcome(
  p_application_id uuid,
  p_fence bigint,
  p_evidence_id uuid,
  p_note text DEFAULT ''
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  app applications%ROWTYPE;
BEGIN
  SELECT * INTO app FROM applications WHERE id = p_application_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'application not found' USING ERRCODE = 'LN004';
  END IF;
  IF EXISTS (SELECT 1 FROM outcome_events WHERE application_id = p_application_id AND fence = p_fence) THEN
    RETURN 'duplicate';
  END IF;
  IF app.fence <> p_fence OR app.state <> 'submitting' THEN
    RAISE EXCEPTION 'stale fencing token % (current %, state %)', p_fence, app.fence, app.state
      USING ERRCODE = 'LN004';
  END IF;
  INSERT INTO outcome_events (user_id, application_id, stage, source, evidence_id, fence, note)
  VALUES (app.user_id, p_application_id, 'submitted', 'adapter', p_evidence_id, p_fence, p_note);
  PERFORM set_config('lintel.actor', 'runner', true);
  PERFORM set_config('lintel.reason', 'confirmation observed by the adapter', true);
  UPDATE applications SET state = 'confirmed', confirmed_at = now() WHERE id = p_application_id;
  RETURN 'recorded';
END;
$$;

-- Recovery: a submit intent with no outcome becomes uncertain and is never retried.
CREATE FUNCTION mark_submission_uncertain(p_application_id uuid, p_reason text) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
  app applications%ROWTYPE;
BEGIN
  SELECT * INTO app FROM applications WHERE id = p_application_id FOR UPDATE;
  IF NOT FOUND OR app.state <> 'submitting' THEN
    RETURN false;
  END IF;
  PERFORM set_config('lintel.actor', 'worker', true);
  PERFORM set_config('lintel.reason', p_reason, true);
  UPDATE applications SET state = 'submission_uncertain' WHERE id = p_application_id;
  INSERT INTO outcome_events (user_id, application_id, stage, source, note)
  VALUES (app.user_id, p_application_id, 'submission_uncertain', 'system', p_reason);
  RETURN true;
END;
$$;

-- ---------------------------------------------------------------------------
-- SECURITY DEFINER entry points for work that happens before a user is known, or across users.
-- Each one does exactly one narrow thing.
-- ---------------------------------------------------------------------------

CREATE FUNCTION auth_register(p_email text, p_password_hash text, p_full_name text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid;
BEGIN
  INSERT INTO users (email, password_hash, full_name) VALUES (p_email, p_password_hash, p_full_name)
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

CREATE FUNCTION auth_lookup(p_email text) RETURNS TABLE (id uuid, password_hash text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT u.id, u.password_hash FROM users u WHERE u.email = p_email::citext
$$;

CREATE FUNCTION auth_create_session(p_user_id uuid, p_token_hash text, p_expires_at timestamptz, p_user_agent text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid;
BEGIN
  INSERT INTO sessions (user_id, token_hash, expires_at, user_agent)
  VALUES (p_user_id, p_token_hash, p_expires_at, p_user_agent) RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

CREATE FUNCTION auth_session_user(p_token_hash text) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT s.user_id FROM sessions s
  WHERE s.token_hash = p_token_hash AND s.revoked_at IS NULL AND s.expires_at > now()
$$;

CREATE FUNCTION auth_device(p_token_hash text) RETURNS TABLE (device_id uuid, user_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  RETURN QUERY
  UPDATE runner_devices d SET last_seen_at = now()
  WHERE d.token_hash = p_token_hash AND d.revoked_at IS NULL
  RETURNING d.id, d.user_id;
END;
$$;

CREATE FUNCTION pairing_start(p_device_code_hash text, p_user_code text, p_device_name text,
                              p_platform text, p_ttl interval) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid;
BEGIN
  DELETE FROM device_pairings WHERE expires_at < now() - interval '1 day';
  INSERT INTO device_pairings (device_code_hash, user_code, device_name, platform, expires_at)
  VALUES (p_device_code_hash, p_user_code, p_device_name, p_platform, now() + p_ttl)
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

-- Called by a signed-in user. Binds a pending pairing to that user.
CREATE FUNCTION pairing_approve(p_user_code text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_name text; v_uid uuid := app_user_id();
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'sign in to pair a runner' USING ERRCODE = 'LN007';
  END IF;
  UPDATE device_pairings SET approved_by = v_uid, approved_at = now()
  WHERE user_code = upper(p_user_code) AND approved_by IS NULL AND expires_at > now()
  RETURNING device_name INTO v_name;
  IF v_name IS NULL THEN
    RAISE EXCEPTION 'that code is unknown, already used or expired' USING ERRCODE = 'LN007';
  END IF;
  RETURN v_name;
END;
$$;

-- Polled by the runner. Creates the device once, after approval, and hands back its id.
CREATE FUNCTION pairing_complete(p_device_code_hash text, p_token_hash text, p_runner_version text)
RETURNS TABLE (status text, device_id uuid, user_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE p device_pairings%ROWTYPE; v_device uuid;
BEGIN
  SELECT * INTO p FROM device_pairings WHERE device_code_hash = p_device_code_hash FOR UPDATE;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'unknown'::text, NULL::uuid, NULL::uuid; RETURN;
  END IF;
  IF p.delivered_at IS NOT NULL THEN
    RETURN QUERY SELECT 'consumed'::text, NULL::uuid, NULL::uuid; RETURN;
  END IF;
  IF p.approved_by IS NULL THEN
    IF p.expires_at < now() THEN
      RETURN QUERY SELECT 'expired'::text, NULL::uuid, NULL::uuid; RETURN;
    END IF;
    RETURN QUERY SELECT 'pending'::text, NULL::uuid, NULL::uuid; RETURN;
  END IF;
  INSERT INTO runner_devices (user_id, name, platform, runner_version, token_hash, last_seen_at)
  VALUES (p.approved_by, p.device_name, p.platform, p_runner_version, p_token_hash, now())
  RETURNING id INTO v_device;
  UPDATE device_pairings SET device_id = v_device, delivered_at = now() WHERE id = p.id;
  INSERT INTO audit_events (user_id, actor, action, subject_type, subject_id, detail)
  VALUES (p.approved_by, 'runner', 'device.paired', 'runner_device', v_device::text,
          jsonb_build_object('name', p.device_name, 'platform', p.platform));
  RETURN QUERY SELECT 'approved'::text, v_device, p.approved_by;
END;
$$;

-- The worker claims queue rows across users, then processes each under that user's context.
CREATE FUNCTION claim_work(p_worker text, p_kinds text[], p_limit integer)
RETURNS SETOF work_queue
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE work_queue q
     SET locked_at = now(), locked_by = p_worker, attempts = q.attempts + 1
   WHERE q.id IN (
     SELECT id FROM work_queue
      WHERE done_at IS NULL AND failed_at IS NULL AND run_after <= now()
        AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
        AND kind = ANY (p_kinds)
      ORDER BY run_after, id
      LIMIT p_limit
      FOR UPDATE SKIP LOCKED
   )
  RETURNING q.*
$$;

CREATE FUNCTION scheduler_user_ids() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT id FROM users ORDER BY created_at
$$;

-- Registry: a bot challenge drops the destination to assisted fill automatically. Lintel never
-- tries to solve or evade one.
CREATE FUNCTION report_bot_challenge(p_host text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_mode text;
BEGIN
  IF app_user_id() IS NULL THEN
    RAISE EXCEPTION 'unauthenticated' USING ERRCODE = 'LN007';
  END IF;
  UPDATE destinations
     SET bot_challenge_seen = true,
         bot_challenge_seen_at = now(),
         support_mode = CASE WHEN support_mode = 'approved_submission' THEN 'assisted_fill' ELSE support_mode END,
         updated_at = now()
   WHERE domain = lower(p_host)
  RETURNING support_mode INTO v_mode;
  RETURN v_mode;
END;
$$;

-- Retention: step logs are kept 90 days with the application drafts.
CREATE FUNCTION retention_purge(p_step_days integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n integer;
BEGIN
  PERFORM set_config('lintel.erasure', 'on', true);
  DELETE FROM run_steps WHERE created_at < now() - make_interval(days => p_step_days);
  GET DIAGNOSTICS n = ROW_COUNT;
  DELETE FROM sessions WHERE expires_at < now() - interval '7 days';
  DELETE FROM device_pairings WHERE expires_at < now() - interval '1 day' AND delivered_at IS NULL;
  RETURN n;
END;
$$;

-- Account deletion: the documented erasure path. Hard-deletes facts, drafts, documents and step
-- logs for the signed-in user. It cannot recall applications already sent to employers.
CREATE FUNCTION erase_user() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_uid uuid := app_user_id();
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'unauthenticated' USING ERRCODE = 'LN007';
  END IF;
  PERFORM set_config('lintel.erasure', 'on', true);
  DELETE FROM run_steps WHERE user_id = v_uid;
  DELETE FROM outcome_events WHERE user_id = v_uid;
  DELETE FROM submit_intents WHERE user_id = v_uid;
  DELETE FROM application_events WHERE user_id = v_uid;
  DELETE FROM audit_events WHERE user_id = v_uid;
  UPDATE applications SET profile_version_id = NULL, resume_variant_id = NULL WHERE user_id = v_uid;
  DELETE FROM profile_versions WHERE user_id = v_uid;
  -- supersession references are checked at the end of the statement, so one DELETE removes the chain
  DELETE FROM profile_facts WHERE user_id = v_uid;
  DELETE FROM users WHERE id = v_uid;
END;
$$;

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'sessions', 'runner_devices', 'documents', 'fact_candidates', 'profile_facts', 'profile_versions',
    'watchlist_companies', 'jobs', 'applications', 'application_events', 'answer_drafts', 'user_tasks',
    'resume_variants', 'application_runs', 'run_steps', 'approval_records', 'submit_intents', 'evidence',
    'outcome_events', 'contacts', 'follow_ups', 'notifications', 'push_subscriptions', 'email_outbox',
    'work_queue', 'model_usage', 'audit_events'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY %I ON %I USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())',
      t || '_owner', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO lintel_app', t);
  END LOOP;
END
$$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_self ON users USING (id = app_user_id()) WITH CHECK (id = app_user_id());
GRANT SELECT, DELETE ON users TO lintel_app;
GRANT UPDATE (full_name, timezone, weekly_budget, no_reply_days, hard_filters, targets,
              notification_prefs, onboarding, password_hash) ON users TO lintel_app;

ALTER TABLE destinations ENABLE ROW LEVEL SECURITY;
CREATE POLICY destinations_read ON destinations FOR SELECT USING (true);
CREATE POLICY destinations_admin ON destinations FOR ALL
  USING (EXISTS (SELECT 1 FROM users WHERE id = app_user_id() AND is_admin))
  WITH CHECK (EXISTS (SELECT 1 FROM users WHERE id = app_user_id() AND is_admin));
GRANT SELECT, INSERT, UPDATE ON destinations TO lintel_app;

GRANT SELECT ON current_facts TO lintel_app;
GRANT SELECT ON lifecycle_transitions, lifecycle_terminal_states, run_transitions TO lintel_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO lintel_app;

-- Append-only tables: no UPDATE or DELETE for the application role at all.
REVOKE UPDATE, DELETE ON profile_facts, profile_versions, outcome_events, application_events,
  submit_intents, audit_events, run_steps FROM lintel_app;

REVOKE ALL ON device_pairings FROM lintel_app;
REVOKE ALL ON FUNCTION auth_register, auth_lookup, auth_create_session, auth_session_user, auth_device,
  pairing_start, pairing_approve, pairing_complete, claim_work, scheduler_user_ids, report_bot_challenge,
  retention_purge, erase_user FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_register, auth_lookup, auth_create_session, auth_session_user, auth_device,
  pairing_start, pairing_approve, pairing_complete, claim_work, scheduler_user_ids, report_bot_challenge,
  retention_purge, erase_user, begin_submit, record_submit_outcome, mark_submission_uncertain, app_user_id
  TO lintel_app;
