"use client";

import * as Popover from "@radix-ui/react-popover";
import * as Tooltip from "@radix-ui/react-tooltip";
import { AlertTriangle, Check, CircleDashed, FileText, Lock, ShieldAlert, ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import { MODE_HELP, MODE_LABEL, SCOPE_LABEL, STATE_TONE, ago, day } from "@/lib/format";
import type { ApplicationState, CheckResult, FactRow, FitLabel, SentenceRow, SupportMode } from "@/lib/types";
import { STATE_LABELS } from "@/lib/schemas.gen";
import { Badge, cx } from "./ui";

export function StatePill({ state, className }: { state: ApplicationState; className?: string }) {
  const tone = STATE_TONE[state];
  return (
    <Badge tone={tone === "progress" ? "progress" : tone} dot className={className}>
      {STATE_LABELS[state]}
    </Badge>
  );
}

export function FitBadge({ label, score }: { label: FitLabel | null; score?: number | null }) {
  if (!label) return <Badge tone="muted">Fit pending</Badge>;
  const tone = { strong: "ok", possible: "accent", stretch: "neutral", conflict: "bad" } as const;
  const text = { strong: "Strong fit", possible: "Possible fit", stretch: "Stretch", conflict: "Conflicts" }[label];
  return (
    <Badge tone={tone[label]}>
      {text}
      {score !== undefined && score !== null && label !== "conflict" && <span className="border-l border-current/25 pl-1.5 tabular-nums">{Math.round(score * 100)}</span>}
    </Badge>
  );
}

export function ModeBadge({ mode }: { mode: SupportMode }) {
  const icon = mode === "draft_only" ? <FileText className="size-3" /> : mode === "approved_submission" ? <Lock className="size-3" /> : <ShieldCheck className="size-3" />;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span>
          <Badge tone={mode === "draft_only" ? "neutral" : "gate"}>
            {icon}
            {MODE_LABEL[mode]}
          </Badge>
        </span>
      </Tooltip.Trigger>
      <TipContent>{MODE_HELP[mode]}</TipContent>
    </Tooltip.Root>
  );
}

export function TipContent({ children }: { children: ReactNode }) {
  return (
    <Tooltip.Portal>
      <Tooltip.Content sideOffset={6} className="z-50 max-w-xs rounded-lg bg-ink px-2.5 py-1.5 text-[12.5px] leading-snug text-bg shadow-lg">
        {children}
      </Tooltip.Content>
    </Tooltip.Portal>
  );
}

// ---------------------------------------------------------------------------
// The Lintel loop: eight steps, three human gates.
// ---------------------------------------------------------------------------

const STEPS = [
  { key: "find", label: "Find", gate: false },
  { key: "fit", label: "Fit brief", gate: true },
  { key: "ground", label: "Ground", gate: true },
  { key: "draft", label: "Draft", gate: false },
  { key: "fill", label: "Fill", gate: false },
  { key: "review", label: "Review", gate: true },
  { key: "send", label: "Send", gate: false },
  { key: "learn", label: "Learn", gate: false },
];

const STATE_STEP: Record<ApplicationState, number> = {
  imported: 0,
  fit_review: 1,
  grounding: 2,
  drafted: 3,
  filling: 4,
  in_review: 5,
  approved: 6,
  submitting: 6,
  confirmed: 7,
  user_reported_submitted: 7,
  submission_uncertain: 6,
  draft_only: 3,
  skipped: 1,
  cancelled: -1,
  expired: -1,
};

export function LoopStepper({ state, compact }: { state: ApplicationState; compact?: boolean }) {
  const current = STATE_STEP[state];
  const closed = ["skipped", "cancelled", "expired", "draft_only"].includes(state);
  const done = ["confirmed", "user_reported_submitted"].includes(state);
  return (
    <ol className={cx("grid grid-cols-4 gap-1.5 sm:grid-cols-8", compact && "sm:gap-1")} aria-label="Application progress">
      {STEPS.map((s, i) => {
        const isDone = done ? i <= 7 : i < current;
        const isCurrent = !done && i === current && !closed;
        const isUncertain = state === "submission_uncertain" && i === 6;
        return (
          <li key={s.key} aria-current={isCurrent ? "step" : undefined}
            className={cx(
              "relative flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-[12px] font-medium transition",
              isUncertain ? "border-warn-line bg-warn-soft text-warn" :
              isCurrent && s.gate ? "gate-ring border-accent bg-accent-soft text-accent-ink" :
              isCurrent ? "border-ink bg-surface text-ink" :
              isDone ? "border-line bg-surface text-ink-2" :
              s.gate ? "border-dashed border-accent-line bg-transparent text-ink-3" : "border-line bg-transparent text-ink-3",
            )}>
            <span className={cx("grid size-4 shrink-0 place-items-center rounded-full text-[10px]",
              isDone ? "bg-ok text-white dark:text-[#06180e]" : isCurrent ? (s.gate ? "bg-accent text-white dark:text-[#0d1630]" : "bg-ink text-bg") : "bg-muted text-ink-3")}>
              {isDone ? <Check className="size-2.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className="truncate">{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Facts and claim checks
// ---------------------------------------------------------------------------

export function ScopeBadge({ scope }: { scope: FactRow["claim_scope"] }) {
  const tone = scope === "employment" ? "accent" : scope === "project" || scope === "coursework" ? "neutral" : "muted";
  return <Badge tone={tone}>{SCOPE_LABEL[scope]}</Badge>;
}

const SOURCE_LABEL = { resume: "Résumé", user_entry: "You added it", user_interview: "Fact Interview" } as const;

export function FactCard({ fact, compact }: { fact: FactRow; compact?: boolean }) {
  return (
    <div className={cx("text-[13px]", !compact && "space-y-2")}>
      <p className="leading-snug text-ink">{fact.statement}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <ScopeBadge scope={fact.claim_scope} />
        <Badge tone="muted">{SOURCE_LABEL[fact.source_type]}</Badge>
        {fact.application_scope_id && <Badge tone="muted">This application only</Badge>}
      </div>
      {!compact && (
        <p className="text-[12px] text-ink-3">
          {fact.source_ref || "No source line"} · confirmed {day(fact.created_at)}
        </p>
      )}
    </div>
  );
}

export function FactChip({ id, facts, index }: { id: string; facts: Record<string, FactRow>; index?: number }) {
  const fact = facts[id];
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button"
          className="inline-flex h-5 items-center gap-1 rounded-md border border-accent-line bg-accent-soft px-1.5 align-middle font-mono text-[10.5px] font-medium text-accent-ink hover:border-accent"
          aria-label={fact ? `Cited fact: ${fact.statement}` : "Cited fact"}>
          {index !== undefined ? `f${index + 1}` : "fact"}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} className="z-50 w-80 rounded-xl border border-line bg-surface p-3.5 shadow-[var(--shadow-lg)]">
          {fact ? <FactCard fact={fact} /> : <p className="text-[13px] text-ink-3">This fact is no longer current.</p>}
          <Popover.Arrow className="fill-[var(--surface)]" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

const CHECK_NAME = { token: "Token check", scope: "Scope check", verifier: "Verifier" } as const;

export function CheckList({ checks }: { checks: CheckResult[] }) {
  return (
    <ul className="space-y-1.5">
      {checks.map((c) => (
        <li key={c.name} className="flex gap-2 text-[12.5px]">
          <span className={cx("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full",
            c.outcome === "pass" ? "bg-ok-soft text-ok" : c.outcome === "fail" ? "bg-bad-soft text-bad" : "bg-muted text-ink-3")}>
            {c.outcome === "pass" ? <Check className="size-2.5" strokeWidth={3} /> : c.outcome === "fail" ? <X className="size-2.5" strokeWidth={3} /> : <CircleDashed className="size-2.5" />}
          </span>
          <span>
            <span className="font-medium text-ink">{CHECK_NAME[c.name]}</span>
            {c.verdict && <span className="text-ink-3"> · {c.verdict}</span>}
            {c.detail && <span className="block text-ink-2">{c.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** One drafted sentence, with its citations and the result of the three checks. */
export function SentenceLine({ s, facts, factIndex }: { s: SentenceRow; facts: Record<string, FactRow>; factIndex: Map<string, number> }) {
  const passed = s.check?.passed;
  return (
    <span className={cx("group rounded-[4px] decoration-2 underline-offset-4", passed === false && "bg-bad-soft text-bad underline decoration-bad/40")}>
      {s.text}{" "}
      {s.fact_ids.map((id) => <FactChip key={id} id={id} facts={facts} index={factIndex.get(id)} />)}{" "}
      <Popover.Root>
        <Popover.Trigger asChild>
          <button type="button" aria-label={passed ? "Claim check passed" : "Claim check failed"}
            className={cx("inline-grid size-[18px] place-items-center rounded-full align-middle", passed ? "text-ok hover:bg-ok-soft" : "text-bad hover:bg-bad-soft")}>
            {passed ? <ShieldCheck className="size-3.5" /> : <ShieldAlert className="size-3.5" />}
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content sideOffset={6} className="z-50 w-80 rounded-xl border border-line bg-surface p-3.5 shadow-[var(--shadow-lg)]">
            <div className="eyebrow mb-2">Claim check</div>
            <CheckList checks={s.check?.checks ?? []} />
            {s.fact_ids.length === 0 && <p className="mt-2 text-[12px] text-ink-3">Cites no facts: allowed only for sentences that make no claim about you.</p>}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>{" "}
    </span>
  );
}

export function RequirementIcon({ status }: { status: "met" | "gap" | "uncertain" }) {
  if (status === "met") return <span className="grid size-5 place-items-center rounded-full bg-ok-soft text-ok"><Check className="size-3" strokeWidth={3} /></span>;
  if (status === "uncertain") return <span className="grid size-5 place-items-center rounded-full bg-warn-soft text-warn"><AlertTriangle className="size-3" /></span>;
  return <span className="grid size-5 place-items-center rounded-full bg-bad-soft text-bad"><X className="size-3" strokeWidth={3} /></span>;
}

export function Ago({ iso, prefix }: { iso: string | null | undefined; prefix?: string }) {
  return (
    <time dateTime={iso ?? undefined} title={iso ? new Date(iso).toLocaleString() : undefined} className="tabular-nums">
      {prefix}
      {ago(iso)}
    </time>
  );
}

export function CompanyAvatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  const dims = { sm: "size-8 rounded-lg text-[13px]", md: "size-10 rounded-xl text-[15px]", lg: "size-12 rounded-2xl text-[18px]" }[size];
  return (
    <span className={cx("grid shrink-0 place-items-center font-semibold text-white", dims)} style={{ background: `oklch(0.5 0.08 ${hue})` }} aria-hidden>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

export function PlatformBadge({ platform }: { platform: string }) {
  const label = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" }[platform] ?? platform;
  return <Badge tone="muted">{label}</Badge>;
}
