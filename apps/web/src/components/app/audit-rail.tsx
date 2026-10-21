"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { useState } from "react";
import { dateTime } from "@/lib/format";
import { Ago } from "../domain";
import { Badge, Hash, cx } from "../ui";
import { StepList } from "./execution-panels";
import type { Detail } from "./shared";

const RUN_TONE = { queued: "neutral", running: "accent", waiting_user: "warn", completed: "ok", failed: "bad", cancelled: "muted" } as const;

export function AuditRail({ d }: { d: Detail }) {
  const [openRun, setOpenRun] = useState<string | null>(null);
  const tab = "data-[state=active]:bg-surface data-[state=active]:text-ink data-[state=active]:shadow-sm rounded-lg px-2.5 py-1 text-[12.5px] text-ink-3";
  return (
    <Tabs.Root defaultValue="timeline" className="card overflow-hidden">
      <div className="border-b border-line px-4 pt-3.5 pb-3">
        <div className="eyebrow mb-2">Audit trail</div>
        <Tabs.List className="flex gap-1 rounded-[10px] bg-muted p-1" aria-label="Audit trail">
          <Tabs.Trigger value="timeline" className={tab}>Timeline</Tabs.Trigger>
          <Tabs.Trigger value="runs" className={tab}>Runs</Tabs.Trigger>
          <Tabs.Trigger value="approvals" className={tab}>Approvals</Tabs.Trigger>
        </Tabs.List>
      </div>
      <Tabs.Content value="timeline" className="max-h-[560px] overflow-y-auto p-4">
        <ol className="relative border-l border-line">
          {[...d.events].reverse().map((e) => (
            <li key={e.id} className="relative pb-4 pl-4 last:pb-0">
              <span className="absolute -left-[4.5px] top-1.5 size-2 rounded-full border border-surface bg-ink-3" />
              <div className="text-[13px] font-medium capitalize text-ink">{e.to_state.replaceAll("_", " ")}</div>
              <div className="text-[12px] text-ink-2">{e.reason}</div>
              <div className="text-[11.5px] text-ink-3">{e.actor} · <Ago iso={e.created_at} /></div>
            </li>
          ))}
        </ol>
      </Tabs.Content>
      <Tabs.Content value="runs" className="max-h-[560px] overflow-y-auto p-4">
        {d.runs.length ? (
          <ul className="space-y-2">
            {[...d.runs].reverse().map((r) => {
              const steps = d.steps.filter((s) => s.run_id === r.id);
              const open = openRun === r.id;
              return (
                <li key={r.id} className="rounded-xl border border-line">
                  <button type="button" onClick={() => setOpenRun(open ? null : r.id)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left">
                    <span className="text-[13px] font-medium capitalize text-ink">{r.kind.replace("_", " ")}</span>
                    <Badge tone={RUN_TONE[r.state]}>{r.state.replace("_", " ")}</Badge>
                    <span className="ml-auto text-[11.5px] text-ink-3">{steps.length} steps</span>
                  </button>
                  <div className={cx("border-t border-line px-3 py-2.5", !open && "hidden")}>
                    <div className="mb-2 text-[11.5px] text-ink-3">{dateTime(r.created_at)} · {r.action_count} actions{r.ended_reason ? ` · ${r.ended_reason}` : ""}</div>
                    <StepList d={d} steps={steps} />
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-[13px] text-ink-3">No runs yet. Runs are execution attempts by your Local Runner; each has an ordered step log.</p>
        )}
      </Tabs.Content>
      <Tabs.Content value="approvals" className="max-h-[560px] space-y-3 overflow-y-auto p-4">
        {d.approvals.length === 0 && d.intents.length === 0 && <p className="text-[13px] text-ink-3">Approvals bind to the payload hash and your runner, and expire after 30 minutes.</p>}
        {[...d.approvals].reverse().map((a) => (
          <div key={a.id} className="rounded-xl border border-line p-3 text-[12.5px]">
            <div className="flex items-center gap-2">
              <span className="font-medium text-ink">Approval</span>
              <Badge tone={a.consumed_at ? "ok" : a.revoked_at ? "muted" : "accent"}>{a.consumed_at ? "consumed" : a.revoked_at ? "revoked" : "live"}</Badge>
            </div>
            <div className="mt-1.5 space-y-0.5 text-ink-2">
              <div>Payload <Hash value={a.payload_hash} /></div>
              <div>Approved {dateTime(a.approved_at)} · expires {dateTime(a.expires_at)}</div>
              {a.revoked_reason && <div className="text-ink-3">{a.revoked_reason}</div>}
              <div className="text-ink-3">Signed with key {a.key_id}</div>
            </div>
          </div>
        ))}
        {d.intents.map((i) => (
          <div key={i.id} className="rounded-xl border border-ok-line bg-ok-soft/50 p-3 text-[12.5px]">
            <div className="font-medium text-ink">Submit intent · fence {i.fence}</div>
            <div className="mt-1 text-ink-2">Written before the click, {dateTime(i.created_at)} · {i.mode.replace("_", " ")}</div>
            <div className="mt-0.5"><Hash value={i.payload_hash} /></div>
          </div>
        ))}
      </Tabs.Content>
    </Tabs.Root>
  );
}
