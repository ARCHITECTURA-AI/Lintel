"use client";

import { Download, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Modal } from "@/components/app/shared";
import { TagInput } from "@/components/tags";
import { Button, Callout, Card, CardHeader, Field, Input, PageHeader, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useMe } from "@/lib/queries";
import type { HardFilters, Me, Targets } from "@/lib/types";

export default function SettingsPage() {
  const { data: me } = useMe();
  const router = useRouter();
  const [s, setS] = useState<Partial<Me>>({});
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  useEffect(() => { if (me) setS(me); }, [me]);
  const save = useAction(() => api.patch("/me", { full_name: s.full_name, timezone: s.timezone, weekly_budget: s.weekly_budget, no_reply_days: s.no_reply_days, targets: s.targets, hard_filters: s.hard_filters, notification_prefs: s.notification_prefs }), { invalidate: [["me"]], success: "Settings saved." });
  const del = useAction(() => api.post("/me/delete", { confirm: typed }), { onSuccess: () => router.replace("/signup") });
  if (!me) return null;
  const t: Targets = s.targets ?? {};
  const f: HardFilters = s.hard_filters ?? {};
  const n = s.notification_prefs ?? {};
  return (
    <div className="animate-rise">
      <PageHeader title="Settings" actions={<Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>} />
      <div className="space-y-6">
        <Card>
          <CardHeader title="You" />
          <div className="grid gap-4 px-5 pb-5 sm:grid-cols-2">
            <Field label="Name"><Input value={s.full_name ?? ""} onChange={(e) => setS({ ...s, full_name: e.target.value })} /></Field>
            <Field label="Time zone" hint="weeks start Monday here"><Input value={s.timezone ?? ""} onChange={(e) => setS({ ...s, timezone: e.target.value })} placeholder="Asia/Kolkata" /></Field>
          </div>
        </Card>
        <Card id="budget">
          <CardHeader title="Budget and follow-ups" description="Interviews per application is the metric that matters. The budget protects it from the pull toward volume." />
          <div className="grid gap-4 px-5 pb-5 sm:grid-cols-2">
            <Field label="Applications per week"><Input type="number" min={0} max={50} value={s.weekly_budget ?? 5} onChange={(e) => setS({ ...s, weekly_budget: Number(e.target.value) })} /></Field>
            <Field label="Days before a follow-up is drafted"><Input type="number" min={3} max={90} value={s.no_reply_days ?? 14} onChange={(e) => setS({ ...s, no_reply_days: Number(e.target.value) })} /></Field>
          </div>
        </Card>
        <Card>
          <CardHeader title="Targets" description="Roles on your watchlist that match these get a fit brief." />
          <div className="grid gap-4 px-5 pb-5 sm:grid-cols-2">
            <Field label="Titles"><TagInput value={t.titles ?? []} onChange={(v) => setS({ ...s, targets: { ...t, titles: v } })} /></Field>
            <Field label="Exclude titles"><TagInput value={t.exclude_titles ?? []} onChange={(v) => setS({ ...s, targets: { ...t, exclude_titles: v } })} /></Field>
            <Field label="Locations"><TagInput value={t.locations ?? []} onChange={(v) => setS({ ...s, targets: { ...t, locations: v } })} /></Field>
            <label className="flex items-center gap-3 self-end pb-2 text-[13.5px] text-ink"><Toggle checked={t.remote_ok ?? true} onChange={(v) => setS({ ...s, targets: { ...t, remote_ok: v } })} label="Remote anywhere" /> Include remote roles anywhere</label>
          </div>
        </Card>
        <Card>
          <CardHeader title="Hard filters" description="Conflicts show on the fit brief with a skip recommendation." />
          <div className="grid gap-4 px-5 pb-5 sm:grid-cols-2">
            <Field label="Allowed locations"><TagInput value={f.locations ?? []} onChange={(v) => setS({ ...s, hard_filters: { ...f, locations: v } })} /></Field>
            <Field label="Exclude seniority"><TagInput value={f.exclude_seniority ?? []} onChange={(v) => setS({ ...s, hard_filters: { ...f, exclude_seniority: v } })} /></Field>
            <Field label="Exclude companies"><TagInput value={f.exclude_companies ?? []} onChange={(v) => setS({ ...s, hard_filters: { ...f, exclude_companies: v } })} /></Field>
            <label className="flex items-center gap-3 self-end pb-2 text-[13.5px] text-ink"><Toggle checked={Boolean(f.remote_only)} onChange={(v) => setS({ ...s, hard_filters: { ...f, remote_only: v } })} label="Remote only" /> Remote roles only</label>
          </div>
        </Card>
        <Card>
          <CardHeader title="Notifications" description="One daily digest by default, and an immediate message only when a run is blocked. Emails carry links, never résumé content." />
          <div className="space-y-3 px-5 pb-5 text-[13.5px] text-ink">
            <label className="flex items-center gap-3"><Toggle checked={n.email ?? true} onChange={(v) => setS({ ...s, notification_prefs: { ...n, email: v } })} label="Email" /> Email</label>
            <label className="flex items-center gap-3"><Toggle checked={(n.digest ?? "daily") === "daily"} onChange={(v) => setS({ ...s, notification_prefs: { ...n, digest: v ? "daily" : "off" } })} label="Daily digest" /> Daily digest</label>
            <label className="flex items-center gap-3"><Toggle checked={Boolean(n.push)} onChange={(v) => setS({ ...s, notification_prefs: { ...n, push: v } })} label="Web push" /> Web push when a run is blocked</label>
            <p className="text-[12px] text-ink-3">WhatsApp arrives in a later release.</p>
          </div>
        </Card>
        <Card>
          <CardHeader title="Your data" description="Export and deletion are part of the product from day one." />
          <div className="flex flex-wrap gap-3 px-5 pb-5">
            <a href="/api/me/export" className="inline-flex h-9 items-center gap-2 rounded-[10px] border border-line-strong bg-surface px-3.5 text-[13.5px] font-medium text-ink hover:bg-muted"><Download className="size-4" /> Export everything (.zip)</a>
            <Button variant="danger" onClick={() => setConfirm(true)}>Delete my account</Button>
          </div>
        </Card>
      </div>
      <Modal open={confirm} onOpenChange={setConfirm} title="Delete your account?" description="This hard-deletes your facts, drafts, documents and step logs.">
        <Callout tone="warn" icon={<TriangleAlert className="size-4" />}>Deletion can&apos;t recall applications already sent to employers. Backups age out on the documented schedule.</Callout>
        <Field label={`Type ${me.email} to confirm`}><Input className="mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} /></Field>
        <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(false)}>Keep my account</Button><Button variant="danger" disabled={typed.toLowerCase() !== me.email.toLowerCase()} loading={del.isPending} onClick={() => del.mutate()}>Delete everything</Button></div>
      </Modal>
    </div>
  );
}
