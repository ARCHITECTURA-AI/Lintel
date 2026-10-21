"use client";

import { ChartNoAxesColumn, Send } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, CardHeader, CopyButton, EmptyState, PageHeader, Skeleton, Stat, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { day, pct } from "@/lib/format";
import { useAction, useFollowUps, useMetrics, useReview } from "@/lib/queries";
import type { Metric, ReviewBucket, WeeklyReview } from "@/lib/types";

function CiBar({ rate, ci }: { rate: number; ci: [number, number] }) {
  return (
    <div className="relative h-2 w-full rounded-full bg-muted" title={`${pct(rate)} (95% interval ${pct(ci[0])}–${pct(ci[1])})`}>
      <div className="absolute inset-y-0 rounded-full bg-accent/25" style={{ left: `${ci[0] * 100}%`, width: `${Math.max(1, (ci[1] - ci[0]) * 100)}%` }} />
      <div className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-surface" style={{ left: `${rate * 100}%` }} />
    </div>
  );
}

function Buckets({ title, rows }: { title: string; rows: ReviewBucket[] }) {
  return (
    <Card>
      <CardHeader title={title} />
      {rows.length ? (
        <div className="overflow-x-auto">
        <table className="w-full min-w-[460px] text-[13px]">
          <thead className="text-left text-[12px] text-ink-3"><tr><th className="px-5 py-1.5 font-medium">Group</th><th className="px-2 py-1.5 text-right font-medium">Sent</th><th className="px-2 py-1.5 text-right font-medium">Replies</th><th className="px-2 py-1.5 text-right font-medium">Interviews</th><th className="w-[34%] px-5 py-1.5 font-medium">Interview rate, 95% interval</th></tr></thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="px-5 py-2.5 text-ink">{r.key}</td>
                <td className="px-2 py-2.5 text-right tabular-nums">{r.sent}</td>
                <td className="px-2 py-2.5 text-right tabular-nums">{r.replies}</td>
                <td className="px-2 py-2.5 text-right tabular-nums">{r.interviews}</td>
                <td className="px-5 py-2.5"><CiBar rate={r.interview_rate} ci={r.ci} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      ) : <p className="px-5 pb-5 text-[13px] text-ink-3">Nothing sent yet.</p>}
    </Card>
  );
}

function WeekChart({ r }: { r: WeeklyReview }) {
  const max = Math.max(1, ...r.by_week.map((w) => w.sent));
  return (
    <div className="flex h-36 items-end gap-1.5" role="img" aria-label="Applications sent per week, with replies and interviews">
      {r.by_week.map((w) => (
        <div key={w.week_start} className="group relative flex flex-1 flex-col items-center justify-end gap-0.5" title={`Week of ${day(w.week_start)}: ${w.sent} sent, ${w.replies} replies, ${w.interviews} interviews`}>
          <div className="w-full rounded-t-[4px] bg-line-strong" style={{ height: `${(w.sent / max) * 100}%`, minHeight: w.sent ? 4 : 2 }}>
            <div className="h-full w-full rounded-t-[4px] bg-accent/70" style={{ height: `${w.sent ? (w.replies / w.sent) * 100 : 0}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

const METRIC_LABEL: Record<string, string> = {
  unsupported_claims: "Unsupported claims in sent applications",
  unapproved_submissions: "Unapproved submissions",
  duplicate_sends: "Duplicate sends",
  audit_coverage: "Audit coverage",
  user_minutes_per_application: "Your minutes per application",
  draft_correction_rate: "Draft correction rate",
  fit_brief_acceptance: "Fit-brief acceptance",
  uncertain_outcome_rate: "Uncertain outcome rate",
};

function MetricRow({ k, m }: { k: string; m: Metric }) {
  const isRate = ["audit_coverage", "draft_correction_rate", "fit_brief_acceptance", "uncertain_outcome_rate"].includes(k);
  const v = m.value === null ? "—" : isRate ? pct(m.value) : k === "user_minutes_per_application" ? `${m.value.toFixed(1)} min` : String(m.value);
  const good = m.target === 0 ? m.value === 0 : m.target === 1 ? m.value === 1 || m.value === null : null;
  return (
    <li className="flex items-center gap-3 px-5 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] text-ink">{METRIC_LABEL[k]}</div>
        {m.detail && <div className="text-[12px] text-ink-3">{m.detail}</div>}
      </div>
      <div className="font-display text-[20px] tabular-nums text-ink">{v}</div>
      {m.target !== undefined && m.target !== null && (
        <Badge tone={good === null ? "muted" : good ? "ok" : "bad"}>target {isRate ? pct(m.target) : k === "user_minutes_per_application" ? `< ${m.target} min` : m.target}</Badge>
      )}
    </li>
  );
}

export default function OutcomesPage() {
  const [weeks, setWeeks] = useState(12);
  const { data: r, isLoading } = useReview(weeks);
  const { data: m } = useMetrics();
  const { data: fus } = useFollowUps();
  const mark = useAction((v: { id: string; status: string }) => api.post(`/follow-ups/${v.id}/mark`, { status: v.status }), { invalidate: [["follow-ups"]] });
  const ready = fus?.filter((f) => f.status === "ready") ?? [];
  return (
    <div className="animate-rise">
      <PageHeader eyebrow="Step 8 · Learn" title="Outcomes" description="What's working for you, from your own data. A single person's sample is small, so every rate comes with its interval."
        actions={<div className="flex gap-1 rounded-xl bg-muted p-1">{[4, 12, 26].map((w) => <button key={w} onClick={() => setWeeks(w)} className={cx("rounded-lg px-3 py-1.5 text-[13px]", weeks === w ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-3")}>{w} weeks</button>)}</div>} />
      {isLoading || !r ? <Skeleton className="h-60" /> : r.sent === 0 ? (
        <Card><EmptyState icon={<ChartNoAxesColumn className="size-5" />} title="No outcomes yet" action={<Link href="/queue" className="text-accent hover:underline">Open the fit queue</Link>}>Once applications go out, record replies and interviews on each one. This page turns them into your weekly review.</EmptyState></Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-[1.2fr_1fr]">
            <Card className="p-5">
              <div className="grid grid-cols-3 gap-4">
                <Stat label="Sent" value={r.sent} />
                <Stat label="Replies" value={r.replies} />
                <Stat label="Interviews" value={r.interviews} />
              </div>
              <div className="mt-5">
                <div className="mb-1.5 flex justify-between text-[12.5px]"><span className="text-ink-2">Interviews per sent application</span><span className="tabular-nums text-ink">{pct(r.interviews_per_sent)} <span className="text-ink-3">({pct(r.ci[0])}–{pct(r.ci[1])})</span></span></div>
                <CiBar rate={r.interviews_per_sent ?? 0} ci={r.ci} />
                <p className="mt-2 text-[12px] text-ink-3">{r.note}</p>
              </div>
            </Card>
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between text-[12.5px]"><span className="font-medium text-ink">Per week</span><span className="flex items-center gap-3 text-ink-3"><span className="flex items-center gap-1"><span className="size-2 rounded-sm bg-line-strong" />sent</span><span className="flex items-center gap-1"><span className="size-2 rounded-sm bg-accent/70" />replied</span></span></div>
              <WeekChart r={r} />
            </Card>
          </div>
          <div className="mt-6 space-y-6">
            <Buckets title="By résumé" rows={r.by_variant} />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <Buckets title="By source" rows={r.by_source} />
              <Buckets title="By company size" rows={r.by_company_size} />
            </div>
          </div>
        </>
      )}
      {ready.length > 0 && (
        <Card className="mt-6">
          <CardHeader title="Follow-ups ready to send" description="Short and grounded. Lintel never messages anyone; you send these yourself." />
          <ul className="divide-y divide-line border-t border-line">
            {ready.map((f) => (
              <li key={f.id} className="px-5 py-4">
                <div className="text-[13.5px] font-medium text-ink">{f.kind === "referral_ask" ? `Referral ask to ${f.contact?.name}` : `Follow up with ${f.job?.company_name}`} <span className="font-normal text-ink-3">· {f.job?.title}</span></div>
                <p className="mt-2 whitespace-pre-wrap rounded-lg bg-surface-2 p-3 text-[13.5px] text-ink">{f.draft}</p>
                <div className="mt-2 flex gap-2"><CopyButton text={f.draft} /><Button size="sm" variant="secondary" icon={<Send className="size-3.5" />} onClick={() => mark.mutate({ id: f.id, status: "sent" })}>I sent it</Button><Button size="sm" variant="ghost" onClick={() => mark.mutate({ id: f.id, status: "dismissed" })}>Dismiss</Button></div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {m && (
        <Card className="mt-6">
          <CardHeader eyebrow="Held to a hard line" title="Trust metrics" description="The numbers Lintel can promise are about trust. Targets are proposed in the PRD." />
          <ul className="divide-y divide-line border-t border-line">
            {Object.entries(m).filter(([k]) => k !== "interviews_per_sent").map(([k, v]) => <MetricRow key={k} k={k} m={v} />)}
          </ul>
        </Card>
      )}
    </div>
  );
}
