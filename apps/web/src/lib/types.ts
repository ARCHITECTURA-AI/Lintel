// Response shapes from the Lintel API. Domain enums and payload types come from the generated
// schemas so the web, the API and the runner agree.
import type {
  ApplicationState,
  CanonicalPayload,
  CheckResult,
  ClaimScope,
  FactKind,
  FitBrief,
  FitLabel,
  FormModel,
  OutcomeStage,
  Recommendation,
  RunKind,
  RunState,
  SupportMode,
} from "./schemas.gen";

export type * from "./schemas.gen";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  timezone: string;
  weekly_budget: number;
  no_reply_days: number;
  hard_filters: HardFilters;
  targets: Targets;
  notification_prefs: { email?: boolean; push?: boolean; digest?: "daily" | "off" };
  onboarding: { done?: boolean; steps?: string[] };
  is_admin: boolean;
  onboarded: boolean;
  created_at: string;
}

export interface Targets {
  titles?: string[];
  exclude_titles?: string[];
  locations?: string[];
  remote_ok?: boolean;
}

export interface HardFilters {
  locations?: string[];
  remote_only?: boolean;
  exclude_seniority?: string[];
  needs_sponsorship?: Record<string, boolean>;
  min_salary?: { amount?: number; currency?: string };
  employment_types?: string[];
  exclude_companies?: string[];
  default_country?: string;
}

export interface FactRow {
  id: string;
  kind: FactKind;
  claim_scope: ClaimScope;
  statement: string;
  attributes: Record<string, unknown> & { skills?: string[]; employer?: string; field?: string; value?: string; proficiency?: string };
  source_type: "resume" | "user_entry" | "user_interview";
  source_ref: string;
  supersedes_fact_id: string | null;
  retracted: boolean;
  application_scope_id: string | null;
  created_at: string;
  current?: boolean;
}

export interface Candidate {
  id: string;
  kind: FactKind;
  claim_scope: ClaimScope;
  statement: string;
  attributes: Record<string, unknown>;
  source_ref: string;
  status: string;
}

export interface Budget {
  week_start: string;
  budget: number;
  used: number;
  remaining: number;
  waiting_next_week: number;
}

export interface JobSummary {
  id: string;
  title: string;
  company_name: string;
  location: string;
  workplace: string;
  platform: string;
  apply_url: string;
  closed_at: string | null;
  comp?: string | null;
}

export interface AppSummary {
  id: string;
  state: ApplicationState;
  state_label: string;
  support_mode: SupportMode;
  fit_label: FitLabel | null;
  fit_score: number | null;
  recommendation: Recommendation | null;
  fit_summary: string | null;
  state_changed_at: string;
  created_at: string;
  week_budget_slot: string | null;
  job: JobSummary;
}

export interface SentenceRow {
  text: string;
  fact_ids: string[];
  edited?: boolean;
  check: { passed: boolean; checks: CheckResult[] };
}

export interface DraftRow {
  id: string;
  field_key: string;
  label: string;
  field_type: string;
  required: boolean;
  options: { label: string; value: string }[];
  max_length: number | null;
  position: number;
  category: string;
  decision: "handle" | "draft_needed" | "ask_user" | "skip";
  handle: string | null;
  value: unknown;
  original_value: unknown;
  sentences: SentenceRow[];
  fact_ids: string[];
  status: "pending" | "ready" | "needs_user" | "blocked" | "skipped";
  status_detail: string;
  edited_by_user: boolean;
}

export interface TaskRow {
  id: string;
  application_id: string | null;
  type: string;
  title: string;
  body: string;
  data: Record<string, unknown> & {
    field_key?: string;
    category?: string;
    options?: { label: string; value: string }[];
    field_type?: string;
    required?: boolean;
    question?: string;
    requirement?: string;
    reason?: string;
    run_id?: string;
    diffs?: { field_key: string; label: string }[];
    sentences?: { text: string; reason: string }[];
    kind?: string;
    company?: string;
    contact_id?: string;
  };
  status: "open" | "done" | "dismissed";
  created_at: string;
  job?: { title: string; company_name: string; state?: string } | null;
  application_state?: string | null;
}

export interface RunRow {
  id: string;
  kind: RunKind;
  state: RunState;
  runner_device_id: string | null;
  payload_hash: string | null;
  started_at: string | null;
  ended_at: string | null;
  ended_reason: string | null;
  waiting_reason: string | null;
  action_count: number;
  created_at: string;
}

export interface StepRow {
  id: number;
  run_id: string;
  seq: number;
  action: string;
  field_key: string | null;
  value_hash: string | null;
  value_len: number | null;
  verification: "ok" | "mismatch" | "error" | "skipped" | "blocked";
  detail: string;
  created_at: string;
}

export interface ApprovalRow {
  id: string;
  payload_hash: string;
  payload: CanonicalPayload;
  runner_device_id: string;
  approved_at: string;
  expires_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  key_id: string;
}

export interface EventRow {
  id: number;
  from_state: string | null;
  to_state: string;
  actor: string;
  reason: string;
  created_at: string;
}

export interface OutcomeRow {
  id: string;
  stage: OutcomeStage;
  source: string;
  fence: number | null;
  note: string;
  occurred_at: string;
}

export interface VariantChange {
  bullet_id: string;
  kind: "moved" | "reworded" | "unchanged";
  before: string;
  after: string;
  from_index: number;
  to_index: number;
  reason: string;
  group: string;
  entry: string;
  check: { passed: boolean; checks: CheckResult[] } | null;
}

export interface VariantRow {
  id: string;
  status: "proposed" | "approved" | "rejected";
  diff: VariantChange[];
  document_sha256: string | null;
  document_id: string | null;
  check_summary: { moved?: number; reworded?: number; reverted?: number };
  approved_at: string | null;
  created_at: string;
}

export interface DocumentRow {
  id: string;
  kind: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
}

export interface ContactRow {
  id: string;
  name: string;
  company: string;
  relationship: string;
  email: string | null;
  notes: string;
}

export interface FollowUpRow {
  id: string;
  application_id: string;
  kind: "follow_up" | "referral_ask";
  due_at: string;
  draft: string;
  draft_sentences: SentenceRow[];
  status: "scheduled" | "ready" | "sent" | "dismissed";
  sent_at: string | null;
  job?: { title: string; company_name: string };
  contact?: { name: string; relationship: string; email: string | null } | null;
  application_state?: string;
}

export interface ApplicationDetail {
  application: AppSummary & {
    fit_brief: FitBrief | null;
    payload: CanonicalPayload | null;
    payload_hash: string | null;
    fence: number;
    decided_at: string | null;
    profile_version_id: string | null;
    resume_variant_id: string | null;
    form_source: string | null;
    submitted_at: string | null;
    confirmed_at: string | null;
  };
  job: JobSummary & { description: string; department: string; employment_type: string; board_name: string; posting_id: string; host: string };
  destination: { domain: string; support_mode: SupportMode; known_limitations: string; policy_review_status: string; bot_challenge_seen: boolean } | null;
  max_mode: SupportMode;
  drafts: DraftRow[];
  tasks: TaskRow[];
  runs: RunRow[];
  steps: StepRow[];
  approvals: ApprovalRow[];
  live_approval: ApprovalRow | null;
  intents: { id: string; fence: number; payload_hash: string; mode: string; created_at: string }[];
  events: EventRow[];
  outcomes: OutcomeRow[];
  evidence: { id: string; kind: string; text: string; reference_number: string | null; page_hash: string | null; created_at: string }[];
  variants: VariantRow[];
  follow_ups: FollowUpRow[];
  facts: Record<string, FactRow>;
  grounding: { plan: { field_key: string; label: string; fact_ids: string[] }[]; open_tasks: string[]; blocking: string[] } | null;
  readiness: { ready: boolean; issues: { field_key: string | null; label: string; status: string; detail: string }[] };
  resume: DocumentRow | null;
  fill: { run: RunRow | null; verified: Record<string, string>; current: boolean };
  budget: Budget;
  contacts: ContactRow[];
  form_model: FormModel | null;
  sent: boolean;
}

export interface Dashboard {
  budget: Budget;
  counts: Record<string, number>;
  tasks: TaskRow[];
  active: { id: string; state: ApplicationState; fit_label: FitLabel | null; fit_score: number | null; title: string; company_name: string; state_changed_at: string; support_mode: SupportMode }[];
  runner: { paired: boolean; online: boolean; devices: number };
  activity: { id: number; application_id: string; from_state: string | null; to_state: string; actor: string; reason: string; created_at: string; title: string; company_name: string }[];
  follow_ups_ready: number;
  facts: number;
  watchlist: number;
  matched_open_jobs: number;
  outcomes: { sent: number; replies: number; interviews: number; ci: [number, number]; by_week: { week_start: string; sent: number; replies: number; interviews: number }[] };
}

export interface WatchCompany {
  id: string;
  name: string;
  platform: "greenhouse" | "lever" | "ashby";
  board_name: string;
  careers_url: string;
  company_size: string | null;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_error: string | null;
  job_count: number;
  matched: number;
}

export interface JobRow {
  id: string;
  title: string;
  company_name: string;
  location: string;
  workplace: string;
  department: string;
  platform: string;
  apply_url: string;
  comp_min: number | null;
  comp_max: number | null;
  comp_currency: string | null;
  target_match: boolean;
  match_reason: string;
  first_seen_at: string;
  closed_at: string | null;
  application_id: string | null;
  application_state: ApplicationState | null;
  fit_label: FitLabel | null;
  support_mode: SupportMode;
}

export interface DeviceRow {
  id: string;
  name: string;
  platform: string;
  runner_version: string;
  paired_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  online: boolean;
}

export interface NotificationRow {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  urgent: boolean;
  created_at: string;
  read_at: string | null;
}

export interface Destination {
  id: string;
  domain: string;
  platform: string;
  permitted_paths: string[];
  adapter_version: string;
  support_mode: SupportMode;
  bot_challenge_seen: boolean;
  bot_challenge_seen_at: string | null;
  policy_review_status: "pending" | "approved" | "rejected";
  policy_review_date: string | null;
  known_limitations: string;
  enabled: boolean;
  disabled_reason: string | null;
  asset_hosts: string[];
  updated_at: string;
}

export interface ReviewBucket {
  key: string;
  sent: number;
  replies: number;
  interviews: number;
  interview_rate: number;
  ci: [number, number];
}

export interface WeeklyReview {
  weeks: number;
  sent: number;
  replies: number;
  interviews: number;
  interviews_per_sent: number | null;
  ci: [number, number];
  note: string;
  by_variant: ReviewBucket[];
  by_source: ReviewBucket[];
  by_company_size: ReviewBucket[];
  by_week: { week_start: string; sent: number; replies: number; interviews: number }[];
}

export type Metric = { value: number | null; target?: number | null; detail?: string; ci?: [number, number]; n?: number };
export type TrustMetrics = Record<string, Metric>;
