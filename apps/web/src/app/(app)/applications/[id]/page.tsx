"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ArrowLeft, ExternalLink, Info, MoreHorizontal, XCircle } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import { ApprovedPanel, FillPanel, ReviewPanel, SubmittingPanel } from "@/components/app/execution-panels";
import { AuditRail } from "@/components/app/audit-rail";
import { DraftsPanel } from "@/components/app/drafts-panel";
import { FitBriefView, FitPanel } from "@/components/app/fit-panel";
import { GroundingPanel } from "@/components/app/grounding-panel";
import { OutcomePanel } from "@/components/app/outcome-panel";
import { SectionTitle } from "@/components/app/shared";
import { CompanyAvatar, FitBadge, LoopStepper, ModeBadge, PlatformBadge, StatePill } from "@/components/domain";
import { Callout, Card, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useApplication } from "@/lib/queries";
import type { ApplicationDetail } from "@/lib/types";

const CLOSED_COPY: Record<string, { title: string; body: string }> = {
  skipped: { title: "You skipped this role", body: "It doesn't count against your budget. The fit brief stays here for reference." },
  cancelled: { title: "Cancelled", body: "Nothing was sent. Every run was stopped and any approval revoked." },
  expired: { title: "The posting closed", body: "It disappeared from the company's feed, so Lintel stopped work on it." },
  draft_only: { title: "Draft-only", body: "This site is prohibited for automation, or you closed the packet. Lintel never fills or clicks here." },
};

function Panel({ d }: { d: ApplicationDetail }) {
  const s = d.application.state;
  if (s === "imported" || s === "fit_review") return <FitPanel d={d} />;
  if (s === "grounding") return <GroundingPanel d={d} />;
  if (s === "drafted") return <DraftsPanel d={d} />;
  if (s === "filling") return <FillPanel d={d} />;
  if (s === "in_review") return <ReviewPanel d={d} />;
  if (s === "approved") return <ApprovedPanel d={d} />;
  if (s === "submitting") return <SubmittingPanel d={d} />;
  if (["confirmed", "submission_uncertain", "user_reported_submitted"].includes(s)) return <OutcomePanel d={d} />;
  const c = CLOSED_COPY[s];
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <SectionTitle hint={c?.body}>{c?.title ?? s}</SectionTitle>
        {d.sent && <OutcomePanel d={d} />}
      </Card>
      {d.application.fit_brief && (
        <Card className="p-6">
          <SectionTitle>Fit brief</SectionTitle>
          <FitBriefView d={d} />
        </Card>
      )}
    </div>
  );
}

export default function ApplicationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: d, isLoading, error } = useApplication(id);
  const cancel = useAction(() => api.post(`/applications/${id}/cancel`, { note: "" }), { invalidate: [["application", id]], success: "Application cancelled." });

  if (error) return <Card><EmptyState title="Application not found">It may belong to another account, or it was deleted.</EmptyState></Card>;
  if (isLoading || !d) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-20" />
        <Skeleton className="h-10" />
        <Skeleton className="h-96" />
      </div>
    );
  }
  const a = d.application;
  const terminal = ["confirmed", "draft_only", "skipped", "submission_uncertain", "user_reported_submitted", "cancelled", "expired", "submitting"].includes(a.state);
  return (
    <div className="animate-rise">
      <Link href="/applications" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
        <ArrowLeft className="size-3.5" /> Applications
      </Link>
      <header className="mb-5 flex flex-wrap items-start gap-4">
        <CompanyAvatar name={d.job.company_name} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-[28px] leading-tight text-ink sm:text-[32px]">{d.job.title}</h1>
          <p className="mt-0.5 text-[14px] text-ink-2">
            {d.job.company_name} · {d.job.location || "Location not stated"}{a.fit_brief?.compensation ? ` · ${a.fit_brief.compensation}` : ""}
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <StatePill state={a.state} />
            <FitBadge label={a.fit_label} score={a.fit_score} />
            <ModeBadge mode={a.support_mode} />
            <PlatformBadge platform={d.job.platform} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a href={d.job.apply_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line-strong bg-surface px-3 text-[13px] text-ink-2 hover:bg-muted">
            Posting <ExternalLink className="size-3.5" />
          </a>
          {!terminal && (
            <Dropdown.Root>
              <Dropdown.Trigger aria-label="More actions" className="grid size-9 place-items-center rounded-[10px] border border-line-strong bg-surface text-ink-2 hover:bg-muted">
                <MoreHorizontal className="size-4" />
              </Dropdown.Trigger>
              <Dropdown.Portal>
                <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-52 rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow-lg)]">
                  <Dropdown.Item onSelect={() => cancel.mutate()} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] text-bad outline-none data-[highlighted]:bg-bad-soft">
                    <XCircle className="size-4" /> Cancel application
                  </Dropdown.Item>
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>
          )}
        </div>
      </header>
      <LoopStepper state={a.state} />
      {d.destination?.known_limitations && a.support_mode !== "draft_only" && !terminal && (
        <Callout className="mt-4" icon={<Info className="size-4" />} tone="neutral">
          <span className="font-medium text-ink">{d.destination.domain}:</span> {d.destination.known_limitations}
        </Callout>
      )}
      <div className="mt-6 grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0"><Panel d={d} /></div>
        <div className="xl:sticky xl:top-20"><AuditRail d={d} /></div>
      </div>
    </div>
  );
}
