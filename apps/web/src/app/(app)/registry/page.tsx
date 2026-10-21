"use client";

import { ShieldCheck } from "lucide-react";
import { ModeBadge } from "@/components/domain";
import { Badge, Callout, Card, PageHeader, Select, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import { useAction, useMe, useRegistry } from "@/lib/queries";
import type { SupportMode } from "@/lib/types";

export default function RegistryPage() {
  const { data } = useRegistry();
  const { data: me } = useMe();
  const admin = Boolean(me?.is_admin);
  const patch = useAction((v: { id: string; body: Record<string, unknown> }) => api.patch(`/registry/${v.id}`, v.body), { invalidate: [["registry"]], success: "Registry updated." });
  return (
    <div className="animate-rise">
      <PageHeader eyebrow="Destination registry" title="Where Lintel may act" description="The registry decides the support mode, never a model. A destination that shows a bot challenge drops to assisted fill automatically, and Lintel never tries to solve or evade it." />
      {!admin && <Callout className="mb-5" icon={<ShieldCheck className="size-4" />}>Read-only. An administrator reviews each destination&apos;s terms before enabling assisted fill.</Callout>}
      <div className="space-y-3">
        {data?.map((d) => (
          <Card key={d.id} className="p-5">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[14px] font-medium text-ink">{d.domain}</span>
                  <Badge tone="muted">{d.platform}</Badge>
                  <Badge tone={d.policy_review_status === "approved" ? "ok" : d.policy_review_status === "rejected" ? "bad" : "warn"}>Terms {d.policy_review_status}{d.policy_review_date ? ` · ${day(d.policy_review_date)}` : ""}</Badge>
                  {d.bot_challenge_seen && <Badge tone="warn">Bot challenge seen</Badge>}
                </div>
                <p className="mt-2 max-w-3xl text-[13px] text-ink-2">{d.known_limitations}</p>
                {d.disabled_reason && <p className="mt-1 text-[12.5px] text-ink-3">{d.disabled_reason}</p>}
              </div>
              <div className="flex items-center gap-3">
                {admin ? (
                  <>
                    <Select className="w-52" value={d.support_mode} onChange={(e) => patch.mutate({ id: d.id, body: { support_mode: e.target.value as SupportMode } })}>
                      <option value="draft_only">Draft-only</option><option value="assisted_fill">Assisted fill</option><option value="approved_submission">Approved submission</option>
                    </Select>
                    <label className="flex items-center gap-2 text-[12.5px] text-ink-2"><Toggle checked={d.enabled} onChange={(v) => patch.mutate({ id: d.id, body: { enabled: v, policy_review_status: v ? "approved" : d.policy_review_status } })} label="Enabled" />Enabled</label>
                  </>
                ) : <ModeBadge mode={d.support_mode} />}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
