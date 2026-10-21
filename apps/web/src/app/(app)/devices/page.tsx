"use client";

import { Laptop, ShieldCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PairInstructions } from "@/components/pair";
import { Ago } from "@/components/domain";
import { Badge, Button, Card, CardHeader, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useDevices } from "@/lib/queries";

function Devices() {
  const params = useSearchParams();
  const { data } = useDevices();
  const revoke = useAction((id: string) => api.post(`/devices/${id}/revoke`), { invalidate: [["devices"]], success: "Revoked. That runner can't take work any more." });
  return (
    <div className="animate-rise">
      <PageHeader title="Local Runner" description="A small app on your machine that opens a visible browser, fills forms from your approved payload, and stands the Submit Guard in front of your click." />
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card className="p-6">
            <h2 className="mb-4 text-[15.5px] font-semibold text-ink">Pair a runner</h2>
            <PairInstructions initialCode={params.get("code") ?? ""} />
          </Card>
          <Card>
            <CardHeader title="Paired devices" description="Each runner gets its own token, kept in your operating system's keychain." />
            <ul className="divide-y divide-line border-t border-line">
              {data?.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                  <Laptop className="size-5 text-ink-3" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-medium text-ink">{d.name}</div>
                    <div className="text-[12.5px] text-ink-3">{d.platform} · v{d.runner_version} · paired <Ago iso={d.paired_at} /> · seen <Ago iso={d.last_seen_at} /></div>
                  </div>
                  {d.revoked_at ? <Badge tone="muted">Revoked</Badge> : <Badge tone={d.online ? "ok" : "neutral"} dot>{d.online ? "Online" : "Offline"}</Badge>}
                  {!d.revoked_at && <Button size="sm" variant="danger" onClick={() => revoke.mutate(d.id)}>Revoke</Button>}
                </li>
              ))}
              {!data?.length && <li className="px-5 py-5 text-[13px] text-ink-3">No runners paired yet.</li>}
            </ul>
          </Card>
        </div>
        <Card className="p-5">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-ink"><ShieldCheck className="size-4 text-accent" /> What stays on your machine</div>
          <ul className="mt-3 space-y-2.5 text-[13px] text-ink-2">
            <li><strong className="text-ink">Logins and cookies.</strong> The runner uses its own browser profile. The cloud has no logins to protect, leak or delete.</li>
            <li><strong className="text-ink">CAPTCHA and sign-in checks.</strong> They&apos;re just a paused window you complete yourself. Lintel never solves or evades them.</li>
            <li><strong className="text-ink">Traces.</strong> Step logs send only a hash and a length of each value. Browser traces stay local unless you share one.</li>
            <li><strong className="text-ink">Where it can go.</strong> Only hosts in the destination registry, and it uploads only documents on the approved list, matched by hash.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

export default function DevicesPage() {
  return <Suspense><Devices /></Suspense>;
}
