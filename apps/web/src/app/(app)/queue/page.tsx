"use client";

import { ArrowRight, CalendarClock, ListChecks } from "lucide-react";
import Link from "next/link";
import { CompanyAvatar, FitBadge, ModeBadge, PlatformBadge } from "@/components/domain";
import { Badge, Button, ButtonLink, Card, EmptyState, Meter, PageHeader, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useQueue } from "@/lib/queries";
import type { AppSummary } from "@/lib/types";

const REC = {
  apply: { label: "Recommend: apply", tone: "ok" as const },
  ask: { label: "Recommend: answer first", tone: "accent" as const },
  skip: { label: "Recommend: skip", tone: "neutral" as const },
};

function QueueCard({ a, rank }: { a: AppSummary; rank: number }) {
  const skip = useAction(() => api.post(`/applications/${a.id}/decide`, { go: false, reason: "skipped from the queue" }), {
    invalidate: [["queue"], ["applications"]],
    success: "Skipped. It won't count against your budget.",
  });
  const pending = a.state === "imported";
  return (
    <Card className={cx("p-5 transition", pending && "opacity-70")}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="hidden w-6 pt-2 text-right font-display text-[18px] text-ink-3 tabular-nums sm:block">{rank}</div>
        <CompanyAvatar name={a.job.company_name} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/applications/${a.id}`} className="text-[15.5px] font-semibold text-ink hover:underline">{a.job.title}</Link>
            <FitBadge label={a.fit_label} score={a.fit_score} />
          </div>
          <div className="mt-0.5 text-[13px] text-ink-2">
            {a.job.company_name} · {a.job.location || "Location not stated"}{a.job.comp ? ` · ${a.job.comp}` : ""}
          </div>
          {pending ? (
            <div className="mt-3 space-y-2"><Skeleton className="h-3.5 w-3/4" /><Skeleton className="h-3.5 w-1/2" /></div>
          ) : (
            <p className="mt-2.5 text-[13.5px] text-ink-2">{a.fit_summary}</p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {a.recommendation && <Badge tone={REC[a.recommendation].tone}>{REC[a.recommendation].label}</Badge>}
            <ModeBadge mode={a.support_mode} />
            <PlatformBadge platform={a.job.platform} />
            {a.week_budget_slot && <Badge tone="muted"><CalendarClock className="size-3" /> Queued for week of {a.week_budget_slot}</Badge>}
          </div>
        </div>
        <div className="flex w-full gap-2 sm:w-auto sm:flex-col">
          <ButtonLink href={`/applications/${a.id}`} variant="gate" icon={<ArrowRight className="size-4" />} className="flex-1 sm:flex-none">Open fit brief</ButtonLink>
          {!pending && <Button variant="ghost" onClick={() => skip.mutate()} loading={skip.isPending} className="flex-1 sm:flex-none">Skip</Button>}
        </div>
      </div>
    </Card>
  );
}

export default function QueuePage() {
  const { data, isLoading } = useQueue();
  const b = data?.budget;
  return (
    <div className="animate-rise">
      <PageHeader
        eyebrow="Gate 1"
        title="Fit queue"
        description="Ranked by fit. Your weekly budget protects interviews per application from the pull toward volume; the surplus waits."
      />
      {b && (
        <Card className="mb-6 flex flex-wrap items-center gap-5 p-5">
          <div className="min-w-56 flex-1">
            <div className="flex items-baseline justify-between text-[13px]">
              <span className="font-medium text-ink">This week&apos;s budget</span>
              <span className="tabular-nums text-ink-2">{b.used} of {b.budget} used</span>
            </div>
            <Meter className="mt-2" value={b.used} max={b.budget} tone={b.remaining ? "accent" : "warn"} label="Weekly budget" />
          </div>
          <div className="text-[13px] text-ink-2">
            {b.remaining ? <>You can say go to <strong className="text-ink">{b.remaining}</strong> more this week.</> : <>Budget used. New go decisions queue for next week.</>}
          </div>
          <ButtonLink href="/settings#budget" size="sm" variant="ghost">Change budget</ButtonLink>
        </Card>
      )}
      {isLoading ? (
        <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : data?.items.length ? (
        <div className="space-y-4">{data.items.map((a, i) => <QueueCard key={a.id} a={a} rank={i + 1} />)}</div>
      ) : (
        <Card>
          <EmptyState icon={<ListChecks className="size-5" />} title="The queue is empty" action={<ButtonLink href="/watchlist" variant="secondary">Add companies to watch</ButtonLink>}>
            New roles that match your targets land here with a fit brief. Lintel reads public job boards a few times a day.
          </EmptyState>
        </Card>
      )}
    </div>
  );
}
