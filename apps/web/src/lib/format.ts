import type { ApplicationState, ClaimScope, FactKind, OutcomeStage, SupportMode } from "./schemas.gen";

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.round(ms / 1000);
  if (s < 0) return inFuture(iso);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 14) return `${d} day${d === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function inFuture(iso: string): string {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (s <= 0) return "now";
  if (s < 90) return `in ${s}s`;
  const m = Math.round(s / 60);
  if (m < 90) return `in ${m} min`;
  const d = Math.round(m / 1440);
  if (d >= 1) return `in ${d} day${d === 1 ? "" : "s"}`;
  return `in ${Math.round(m / 60)} h`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function money(min?: number | null, max?: number | null, currency?: string | null): string | null {
  if (!min && !max) return null;
  const f = (n: number) =>
    n >= 100000 && currency === "INR"
      ? `${(n / 100000).toFixed(n % 100000 === 0 ? 0 : 1)}L`
      : n >= 1000
        ? `${Math.round(n / 1000)}k`
        : String(n);
  return `${currency ?? ""} ${min ? f(min) : "?"}–${max ? f(max) : "?"}`.trim();
}

export const SCOPE_LABEL: Record<ClaimScope, string> = {
  employment: "Job",
  project: "Project",
  coursework: "Coursework",
  education: "Education",
  certification: "Certification",
  personal: "About you",
};

export const KIND_LABEL: Record<FactKind, string> = {
  contact: "Contact",
  link: "Links",
  role: "Roles",
  achievement: "Achievements",
  skill: "Skills",
  education: "Education",
  certification: "Certifications",
  eligibility: "Eligibility",
  preference: "Preferences",
  demographic: "Self-identification",
};

export const MODE_LABEL: Record<SupportMode, string> = {
  draft_only: "Draft-only",
  assisted_fill: "Assisted fill",
  approved_submission: "Approved submission",
};

export const MODE_HELP: Record<SupportMode, string> = {
  draft_only: "Lintel prepares a packet you copy. Nobody clicks for you.",
  assisted_fill: "Lintel fills the form in your browser. You click the site's own Submit, after the Guard checks it.",
  approved_submission: "Lintel clicks Submit once, after your exact approval. Only on reviewed sites with no bot challenge.",
};

export const STAGE_LABEL: Record<OutcomeStage, string> = {
  prepared: "Prepared",
  submitted: "Sent (confirmed)",
  user_reported_submitted: "Sent by you",
  submission_uncertain: "Uncertain",
  acknowledged: "Acknowledged",
  no_reply: "No reply",
  rejected: "Rejected",
  recruiter_screen: "Recruiter screen",
  interview: "Interview",
  final_round: "Final round",
  offer: "Offer",
  accepted: "Accepted",
  declined: "Declined",
  withdrawn: "Withdrawn",
};

export const USER_STAGES: OutcomeStage[] = [
  "acknowledged",
  "recruiter_screen",
  "interview",
  "final_round",
  "offer",
  "accepted",
  "rejected",
  "declined",
  "withdrawn",
];

export const STATE_TONE: Record<ApplicationState, "neutral" | "gate" | "ok" | "warn" | "bad" | "muted" | "progress"> = {
  imported: "muted",
  fit_review: "gate",
  grounding: "gate",
  drafted: "progress",
  filling: "progress",
  in_review: "gate",
  approved: "ok",
  submitting: "progress",
  confirmed: "ok",
  draft_only: "muted",
  skipped: "muted",
  submission_uncertain: "warn",
  user_reported_submitted: "ok",
  cancelled: "muted",
  expired: "muted",
};

export function shortHash(h: string | null | undefined, n = 10): string {
  return h ? h.slice(0, n) : "—";
}

export function displayValue(value: unknown, options?: { label: string; value: string }[]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes, ticked" : "Not ticked";
  if (Array.isArray(value)) return value.map((v) => displayValue(v, options)).join(", ");
  if (options && options.length) {
    const hit = options.find((o) => o.value === String(value));
    if (hit) return hit.label;
  }
  return String(value);
}

export function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?"
  );
}
