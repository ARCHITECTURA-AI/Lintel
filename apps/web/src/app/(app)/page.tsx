"use client";

import {
  ArrowRight,
  BookUser,
  CircleHelp,
  Compass,
  FileWarning,
  Hand,
  Laptop,
  MailCheck,
  MessageSquareQuote,
  ShieldAlert,
  Sparkles,
  UserPlus,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Ago, CompanyAvatar, FitBadge, StatePill } from "@/components/domain";
import { ButtonLink, Card, CardHeader, EmptyState, Meter, PageHeader, Skeleton, Stat, cx } from "@/components/ui";
import { pct } from "@/lib/format";
import { useDashboard, useMe } from "@/lib/queries";
import type { ApplicationState, TaskRow } from "@/lib/types";

const TASK_META: Record<string, { icon: ReactNode; cta: string; tone: string; rank: number }> = {
  waiting_user: { icon: <Hand className="size-4" />, cta: "Open the runner window", tone: "text-warn bg-warn-soft", rank: 0 },
  guard_mismatch: { icon: <ShieldAlert className="size-4" />, cta: "Re-approve", tone: "text-bad bg-bad-soft", rank: 1 },
  confirm_submission: { icon: <MailCheck className="size-4" />, cta: "Record the outcome", tone: "text-warn bg-warn-soft", rank: 2 },
  unknown_answer: { icon: <CircleHelp className="size-4" />, cta: "Answer", tone: "text-accent bg-accent-soft", rank: 3 },
  fact_interview: { icon: <MessageSquareQuote className="size-4" />, cta: "Answer", tone: "text-accent bg-accent-soft", rank: 4 },
  claim_review: { icon: <FileWarning className="size-4" />, cta: "Review", tone: "text-bad bg-bad-soft", rank: 5 },
  follow_up: { icon: <MailCheck className="size-4" />, cta: "Send it", tone: "text-ok bg-ok-soft", rank: 6 },
  referral: { icon: <UserPlus className="size-4" />, cta: "Ask someone", tone: "text-ink-2 bg-muted", rank: 7 },
};

const NEXT_STEP: Partial<Record<ApplicationState, string>> = {
  fit_review: "Decide go or skip",
  grounding: "Confirm the facts",
  drafted: "Review drafts, then fill",
  filling: "Filling in your browser",
  in_review: "Approve the exact payload",
  approved: "Click Submit in the Lintel window",
  submitting: "Confirming…",
};

function greeting(name: string) {
  const h = new Date().getHours();
  const part = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}${name ? `, ${name.split(" ")[0]}` : ""}`;
}

function TaskItem({ t }: { t: TaskRow }) {
  const meta = TASK_META[t.type] ?? TASK_META.referral;
  const href = t.application_id ? `/applications/${t.application_id}` : "/inbox";
  return (
    <li>
      <Link href={href} className="group flex items-start gap-3 rounded-xl px-3 py-3 transition hover:bg-surface-2">
        <span className={cx("mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg", meta.tone)}>{meta.icon}</span>
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 text-[13.5px] font-medium text-ink">{t.title}</span>
          <span className="mt-0.5 block truncate text-[12.5px] text-ink-3">
            {t.job ? `${t.job.title} · ${t.job.company_name}` : t.body}
          </span>
        </span>
        <span className="mt-1 hidden shrink-0 items-center gap-1 text-[12.5px] font-medium text-accent sm:flex">
          {meta.cta}
          <ArrowRight className="size-3.5 transition group-hover:translate-x-0.5" />
        </span>
      </Link>
    </li>
  );
}

export default function TodayPage() {
  const { data: me } = useMe();
  const { data, isLoading } = useDashboard();

  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-14 w-80" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32" />)}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  const tasks = [...data.tasks].sort((a, b) => (TASK_META[a.type]?.rank ?? 9) - (TASK_META[b.type]?.rank ?? 9));
  const b = data.budget;
  const o = data.outcomes;
  const weekLabel = new Date(b.week_start + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const summary = [
    tasks.length ? `${tasks.length} thing${tasks.length === 1 ? "" : "s"} need${tasks.length === 1 ? "s" : ""} you` : "Nothing needs you right now",
    data.active.length ? `${data.active.length} application${data.active.length === 1 ? "" : "s"} in flight` : null,
  ].filter(Boolean).join(". ") + ".";

  return (
    <div className="animate-rise">
      <PageHeader
        eyebrow={new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        title={greeting(me?.full_name ?? "")}
        description={summary}
        actions={<ButtonLink href="/queue" variant="primary" icon={<Sparkles className="size-4" />}>Open the fit queue</ButtonLink>}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <Stat label={`Budget, week of ${weekLabel}`} value={<>{b.used}<span className="text-ink-3"> / {b.budget}</span></>}
            sub={b.waiting_next_week ? `${b.waiting_next_week} waiting for next week` : `${b.remaining} left this week`} />
          <Meter className="mt-3" value={b.used} max={b.budget} tone={b.remaining === 0 ? "warn" : "accent"} label="Weekly application budget" />
        </Card>
        <Card className="p-5">
          <Stat label="Needs you" value={tasks.length} sub={tasks.length ? "Questions, approvals and clicks" : "All caught up"} />
        </Card>
        <Card className="p-5">
          <Stat label="In flight" value={data.active.length} sub={`${data.counts.fit_review ?? 0} waiting for a fit decision`} />
        </Card>
        <Card className="p-5">
          <Stat label="Last 8 weeks" value={<>{o.sent}<span className="text-[15px] text-ink-3"> sent</span></>}
            sub={o.sent ? `${o.replies} replies · ${o.interviews} interviews (${pct(o.ci[0])}–${pct(o.ci[1])} rate)` : "Outcomes appear once you send"} />
        </Card>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          <Card>
            <CardHeader title="Needs you" description="Ordered by what blocks progress first." />
            {tasks.length ? (
              <ul className="px-2 pb-2">{tasks.slice(0, 12).map((t) => <TaskItem key={t.id} t={t} />)}</ul>
            ) : (
              <EmptyState icon={<Sparkles className="size-5" />} title="You're clear">
                When Lintel needs a fact, an approval or your click, it shows up here.
              </EmptyState>
            )}
          </Card>

          <Card>
            <CardHeader title="In flight" description="Applications between a go decision and a send." actions={<ButtonLink href="/applications" size="sm" variant="ghost">All applications</ButtonLink>} />
            {data.active.length ? (
              <ul className="divide-y divide-line border-t border-line">
                {data.active.map((a) => (
                  <li key={a.id}>
                    <Link href={`/applications/${a.id}`} className="flex items-center gap-3 px-5 py-3.5 transition hover:bg-surface-2">
                      <CompanyAvatar name={a.company_name} size="sm" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13.5px] font-medium text-ink">{a.title}</div>
                        <div className="truncate text-[12.5px] text-ink-3">{a.company_name} · {NEXT_STEP[a.state] ?? ""}</div>
                      </div>
                      <div className="hidden sm:block"><FitBadge label={a.fit_label} score={a.fit_score} /></div>
                      <StatePill state={a.state} />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={<Compass className="size-5" />} title="Nothing in flight"
                action={<ButtonLink href="/queue" variant="secondary">Review the fit queue</ButtonLink>}>
                Go on a role from the fit queue and it moves here.
              </EmptyState>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="p-5">
            <div className="flex items-center gap-3">
              <span className={cx("grid size-10 place-items-center rounded-xl", data.runner.online ? "bg-ok-soft text-ok" : "bg-muted text-ink-3")}>
                <Laptop className="size-5" />
              </span>
              <div className="flex-1">
                <div className="text-[14px] font-semibold text-ink">Local Runner</div>
                <div className="text-[12.5px] text-ink-2">
                  {!data.runner.paired ? "Not paired yet" : data.runner.online ? "Online and ready to fill" : "Paired, currently offline"}
                </div>
              </div>
            </div>
            <p className="mt-3 text-[13px] text-ink-2">
              The runner fills forms in a visible browser on your machine. Logins and cookies never leave it.
            </p>
            <ButtonLink href="/devices" size="sm" variant={data.runner.paired ? "secondary" : "gate"} className="mt-3 w-full">
              {data.runner.paired ? "Manage devices" : "Pair your runner"}
            </ButtonLink>
          </Card>

          <Card className="p-5">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-accent-soft text-accent"><BookUser className="size-5" /></span>
              <div className="flex-1">
                <div className="text-[14px] font-semibold text-ink">{data.facts} confirmed facts</div>
                <div className="text-[12.5px] text-ink-2">{data.watchlist} companies watched · {data.matched_open_jobs} matching roles open</div>
              </div>
            </div>
            <ButtonLink href="/ledger" size="sm" variant="secondary" className="mt-3 w-full">Open the ledger</ButtonLink>
          </Card>

          <Card>
            <CardHeader title="Recent activity" />
            {data.activity.length ? (
              <ol className="relative mx-5 mb-4 border-l border-line">
                {data.activity.map((e) => (
                  <li key={e.id} className="relative pb-3.5 pl-4 last:pb-0">
                    <span className="absolute -left-[4.5px] top-1.5 size-2 rounded-full border border-surface bg-ink-3" />
                    <Link href={`/applications/${e.application_id}`} className="block text-[13px] text-ink hover:underline">
                      {e.title} <span className="text-ink-3">· {e.company_name}</span>
                    </Link>
                    <div className="text-[12px] text-ink-3">
                      <span className="capitalize">{e.to_state.replaceAll("_", " ")}</span> · {e.reason} · <Ago iso={e.created_at} />
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="px-5 pb-5 text-[13px] text-ink-3">Activity appears as applications move.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
