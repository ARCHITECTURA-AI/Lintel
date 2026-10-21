"use client";

import { Building2, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Ago, CompanyAvatar, PlatformBadge } from "@/components/domain";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useWatchlist } from "@/lib/queries";

const SIZES = ["1-50", "51-200", "201-1000", "1000+"];

export default function WatchlistPage() {
  const { data, isLoading } = useWatchlist();
  const [url, setUrl] = useState("");
  const [size, setSize] = useState("");
  const [detected, setDetected] = useState<{ platform: string; board: string; name: string } | null>(null);
  const detect = useAction(() => api.post<{ platform: string; board: string; name: string }>("/watchlist/detect", { url }), { onSuccess: (r) => setDetected(r as { platform: string; board: string; name: string }) });
  const add = useAction(() => api.post("/watchlist", { url, company_size: size || null }), {
    invalidate: [["watchlist"]],
    success: "Added. Lintel is reading the board now.",
    onSuccess: () => { setUrl(""); setDetected(null); setSize(""); },
  });
  const sync = useAction((id: string) => api.post(`/watchlist/${id}/sync`), { invalidate: [["watchlist"], ["queue"]], success: "Board synced." });
  const remove = useAction((id: string) => api.del(`/watchlist/${id}`), { invalidate: [["watchlist"]], success: "Removed from the watchlist." });
  const setCompanySize = useAction((v: { id: string; size: string }) => api.patch(`/watchlist/${v.id}`, { company_size: v.size }), { invalidate: [["watchlist"]] });
  return (
    <div className="animate-rise">
      <PageHeader eyebrow="Discovery" title="Watchlist" description="Paste a careers URL and Lintel detects the platform and board. Public job-board feeds only: no scraping, no logins, polled gently with caching." />
      <Card className="mb-6 p-5">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input value={url} onChange={(e) => { setUrl(e.target.value); setDetected(null); }} placeholder="https://job-boards.greenhouse.io/company or https://company.com/careers"
            onKeyDown={(e) => e.key === "Enter" && url && detect.mutate()} />
          <Select value={size} onChange={(e) => setSize(e.target.value)} className="sm:w-44" aria-label="Company size">
            <option value="">Company size…</option>
            {SIZES.map((s) => <option key={s} value={s}>{s} people</option>)}
          </Select>
          {detected ? (
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>Add {detected.name}</Button>
          ) : (
            <Button variant="secondary" disabled={!url} loading={detect.isPending} onClick={() => detect.mutate()}>Detect</Button>
          )}
        </div>
        {detected && (
          <p className="mt-3 text-[13px] text-ink-2">
            Found a <strong className="text-ink">{detected.platform}</strong> board named <code>{detected.board}</code>. Company size feeds your weekly review.
          </p>
        )}
      </Card>
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : data?.length ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((c) => (
            <Card key={c.id} className="p-5">
              <div className="flex items-start gap-3">
                <CompanyAvatar name={c.name} />
                <div className="min-w-0 flex-1">
                  <div className="text-[15px] font-semibold text-ink">{c.name}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5"><PlatformBadge platform={c.platform} /><Badge tone="muted">{c.board_name}</Badge></div>
                </div>
                <Button size="sm" variant="ghost" aria-label="Remove" onClick={() => remove.mutate(c.id)}><Trash2 className="size-3.5" /></Button>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 text-[12.5px]">
                <div><div className="text-ink-3">Open roles</div><div className="font-display text-[22px] text-ink tabular-nums">{c.job_count}</div></div>
                <div><div className="text-ink-3">Match you</div><div className="font-display text-[22px] text-ink tabular-nums">{c.matched}</div></div>
                <div>
                  <div className="text-ink-3">Size</div>
                  <select className="mt-1 w-full bg-transparent text-[13px] text-ink outline-none" value={c.company_size ?? ""} onChange={(e) => setCompanySize.mutate({ id: c.id, size: e.target.value })}>
                    <option value="">Not set</option>
                    {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-[12.5px] text-ink-3">
                {c.last_sync_status === "error" ? <span className="text-bad">{c.last_error}</span> : <span>Synced <Ago iso={c.last_synced_at} /></span>}
                <Link href={`/jobs?company=${c.id}`} className="ml-auto text-accent hover:underline">See roles</Link>
                <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} loading={sync.isPending && sync.variables === c.id} onClick={() => sync.mutate(c.id)}>Sync</Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card><EmptyState icon={<Building2 className="size-5" />} title="No companies yet">Ashby has no endpoint that lists its customers, so discovery starts from companies you choose.</EmptyState></Card>
      )}
    </div>
  );
}
