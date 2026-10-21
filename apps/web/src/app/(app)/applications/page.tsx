"use client";

import { ScrollText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Ago, CompanyAvatar, FitBadge, ModeBadge, StatePill } from "@/components/domain";
import { Card, EmptyState, PageHeader, Skeleton, cx } from "@/components/ui";
import { useApplications } from "@/lib/queries";

const FILTERS = [
  { key: "active", label: "In progress", states: ["imported", "fit_review", "grounding", "drafted", "filling", "in_review", "approved", "submitting"] },
  { key: "sent", label: "Sent", states: ["confirmed", "user_reported_submitted", "submission_uncertain"] },
  { key: "closed", label: "Closed", states: ["skipped", "cancelled", "expired", "draft_only"] },
  { key: "all", label: "All", states: [] as string[] },
];

export default function ApplicationsPage() {
  const [filter, setFilter] = useState("active");
  const { data, isLoading } = useApplications();
  const f = FILTERS.find((x) => x.key === filter)!;
  const rows = (data ?? []).filter((a) => !f.states.length || f.states.includes(a.state));
  const count = (k: string) => (data ?? []).filter((a) => { const s = FILTERS.find((x) => x.key === k)!.states; return !s.length || s.includes(a.state); }).length;
  return (
    <div className="animate-rise">
      <PageHeader title="Applications" description="Every role you've considered, with its lifecycle and audit trail." />
      <div className="mb-4 flex flex-wrap gap-1 rounded-xl bg-muted p-1 sm:w-fit" role="tablist">
        {FILTERS.map((x) => (
          <button key={x.key} role="tab" aria-selected={filter === x.key} onClick={() => setFilter(x.key)}
            className={cx("rounded-lg px-3 py-1.5 text-[13px]", filter === x.key ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-3 hover:text-ink")}>
            {x.label} <span className="tabular-nums text-ink-3">{data ? count(x.key) : ""}</span>
          </button>
        ))}
      </div>
      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : rows.length ? (
          <ul className="divide-y divide-line">
            {rows.map((a) => (
              <li key={a.id}>
                <Link href={`/applications/${a.id}`} className="flex flex-wrap items-center gap-3 px-5 py-3.5 transition hover:bg-surface-2">
                  <CompanyAvatar name={a.job.company_name} size="sm" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium text-ink">{a.job.title}</div>
                    <div className="truncate text-[12.5px] text-ink-3">{a.job.company_name} · {a.job.location} · updated <Ago iso={a.state_changed_at} /></div>
                  </div>
                  <div className="hidden items-center gap-2 md:flex"><FitBadge label={a.fit_label} score={a.fit_score} /><ModeBadge mode={a.support_mode} /></div>
                  <StatePill state={a.state} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={<ScrollText className="size-5" />} title="Nothing here yet">Applications appear when a role matches your targets or you add one.</EmptyState>
        )}
      </Card>
    </div>
  );
}
