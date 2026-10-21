"use client";

import { Compass, Link2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { CompanyAvatar, FitBadge, ModeBadge, StatePill } from "@/components/domain";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, money } from "@/lib/format";
import { useAction, useJobs } from "@/lib/queries";

function Jobs() {
  const params = useSearchParams();
  const router = useRouter();
  const company = params.get("company");
  const [matched, setMatched] = useState<"matched" | "all">("matched");
  const [q, setQ] = useState("");
  const [importUrl, setImportUrl] = useState("");
  const qs = new URLSearchParams();
  if (company) qs.set("company_id", company);
  if (matched === "matched") qs.set("matched", "true");
  if (q) qs.set("q", q);
  const { data, isLoading } = useJobs(qs.toString());
  const consider = useAction((id: string) => api.post<{ application_id: string }>(`/jobs/${id}/consider`), {
    invalidate: [["jobs"]],
    onSuccess: (r) => router.push(`/applications/${(r as { application_id: string }).application_id}`),
  });
  const imp = useAction(() => api.post<{ application_id: string }>("/jobs/import", { url: importUrl }), {
    onSuccess: (r) => router.push(`/applications/${(r as { application_id: string }).application_id}`),
  });
  return (
    <div className="animate-rise">
      <PageHeader eyebrow="Discovery" title="Jobs" description="Every open role on your watched boards. Roles that match your targets get a fit brief automatically; any other role is one click away." />
      <Card className="mb-5 flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
        <div className="flex gap-1 rounded-xl bg-muted p-1">
          {(["matched", "all"] as const).map((m) => (
            <button key={m} onClick={() => setMatched(m)} className={cx("rounded-lg px-3 py-1.5 text-[13px]", matched === m ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-3")}>
              {m === "matched" ? "Matches my targets" : "All open roles"}
            </button>
          ))}
        </div>
        <Input className="lg:max-w-64" placeholder="Filter by title, company, place" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="flex flex-1 gap-2 lg:justify-end">
          <Input className="lg:max-w-80" placeholder="Paste a single job URL" value={importUrl} onChange={(e) => setImportUrl(e.target.value)} />
          <Button variant="secondary" icon={<Link2 className="size-4" />} disabled={!importUrl} loading={imp.isPending} onClick={() => imp.mutate()}>Add role</Button>
        </div>
      </Card>
      {company && <div className="mb-3"><Badge tone="accent">Filtered to one company · <Link href="/jobs" className="underline">clear</Link></Badge></div>}
      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : data?.length ? (
          <ul className="divide-y divide-line">
            {data.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <CompanyAvatar name={j.company_name} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-medium text-ink">{j.title}</div>
                  <div className="truncate text-[12.5px] text-ink-3">
                    {j.company_name} · {j.location || "—"}{money(j.comp_min, j.comp_max, j.comp_currency) ? ` · ${money(j.comp_min, j.comp_max, j.comp_currency)}` : ""} · seen {ago(j.first_seen_at)}
                  </div>
                  {!j.target_match && <div className="text-[12px] text-ink-3">{j.match_reason}</div>}
                </div>
                <div className="hidden md:block"><ModeBadge mode={j.support_mode} /></div>
                {j.application_id ? (
                  <Link href={`/applications/${j.application_id}`} className="flex items-center gap-2">
                    {j.fit_label && <FitBadge label={j.fit_label} />}
                    {j.application_state && <StatePill state={j.application_state} />}
                  </Link>
                ) : (
                  <Button size="sm" variant="secondary" loading={consider.isPending && consider.variables === j.id} onClick={() => consider.mutate(j.id)}>Consider</Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon={<Compass className="size-5" />} title="No roles to show">Add companies to your watchlist, or show all open roles.</EmptyState>
        )}
      </Card>
    </div>
  );
}

export default function JobsPage() {
  return <Suspense><Jobs /></Suspense>;
}
