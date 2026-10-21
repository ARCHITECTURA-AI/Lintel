"use client";

import { AlertTriangle, BadgeCheck, Check, CircleDot, Clock, Hand, Laptop, Loader2, Lock, MousePointerClick, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MODE_HELP, MODE_LABEL, dateTime, displayValue, inFuture } from "@/lib/format";
import { useAction, useDevices } from "@/lib/queries";
import type { RunRow, StepRow, SupportMode } from "@/lib/types";
import { FactChip } from "../domain";
import { Badge, Button, Callout, Card, Hash, cx } from "../ui";
import { Consents, DraftCard } from "./drafts-panel";
import { SectionTitle, factIndex, labelFor, type Detail } from "./shared";

const WAIT_COPY: Record<string, string> = {
  captcha: "A bot challenge appeared. Complete it in the Lintel browser window, then press Resume there. Lintel never solves or evades one.",
  mfa: "The site wants to verify it's you. Finish in the Lintel browser window, then press Resume.",
  login: "The site asked you to sign in. Do it in the Lintel browser window (its own profile, never your everyday one), then press Resume.",
  modal: "A dialog covered the form. Lintel doesn't click things it wasn't approved to. Close it, then press Resume.",
  session_expired: "The page timed out. Reload it in the Lintel browser window, then press Resume.",
  missing_fact: "The live form asks questions Lintel hadn't seen. Answer them here, then press Resume in the browser.",
  validation: "The site rejected a value. Fix it in the browser window, then press Resume.",
  paused: "Lintel pauses after 15 minutes of active automation. Press Resume to continue.",
  no_progress: "The page didn't respond as expected. Check the window, then press Resume.",
};

const ACTION_LABEL: Record<string, string> = {
  verify_signature: "Verified the signed payload",
  navigate: "Opened the form",
  read_form: "Read the form",
  fill: "Typed",
  select: "Selected",
  check: "Ticked",
  upload: "Attached",
  verify: "Read back",
  click: "Clicked",
  pause: "Paused for you",
  resume: "Resumed with a fresh read",
  guard_armed: "Armed the Submit Guard",
  guard_check: "Guard checked a click",
  submit_intent: "Wrote the submit intent",
  outcome: "Observed the outcome",
  payload_reissued: "Reconciled with the live form",
  gate: "Policy gate refused an action",
  end: "Run ended",
  user_submitted: "You sent it outside the Guard",
  adopt: "Sent your edits for re-approval",
  restore: "Put the approved values back",
};

export function StepList({ d, steps, limit }: { d: Detail; steps: StepRow[]; limit?: number }) {
  const shown = limit ? steps.slice(-limit) : steps;
  return (
    <ol className="space-y-1">
      {shown.map((s) => (
        <li key={s.id} className="flex items-start gap-2.5 text-[12.5px]">
          <span className={cx("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full",
            s.verification === "ok" ? "bg-ok-soft text-ok" : s.verification === "skipped" ? "bg-muted text-ink-3" : "bg-bad-soft text-bad")}>
            {s.verification === "ok" ? <Check className="size-2.5" strokeWidth={3} /> : s.verification === "skipped" ? <CircleDot className="size-2.5" /> : <X className="size-2.5" strokeWidth={3} />}
          </span>
          <span className="min-w-0 flex-1 text-ink-2">
            <span className="text-ink">{ACTION_LABEL[s.action] ?? s.action}</span>
            {s.field_key && <span> · {labelFor(d, s.field_key)}</span>}
            {s.value_len !== null && <span className="text-ink-3"> · {s.value_len} chars</span>}
            {s.detail && <span className="block truncate text-ink-3" title={s.detail}>{s.detail}</span>}
          </span>
          {s.value_hash && <span className="hidden font-mono text-[10.5px] text-ink-3 sm:inline">{s.value_hash.slice(0, 8)}</span>}
        </li>
      ))}
    </ol>
  );
}

export function FillPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const run: RunRow | undefined = [...d.runs].reverse().find((r) => ["queued", "running", "waiting_user"].includes(r.state));
  const steps = run ? d.steps.filter((s) => s.run_id === run.id) : [];
  const { data: devices } = useDevices();
  const online = devices?.some((x) => x.online);
  const resume = useAction(() => api.post(`/runs/${run?.id}/resume`), { invalidate: [["application", id]], success: "Resumed. The runner starts from a fresh read." });
  const cancel = useAction(() => api.post(`/applications/${id}/runs/${run?.id}/cancel`), { invalidate: [["application", id]], success: "Stopped the fill." });
  const fills = d.drafts.filter((x) => x.status === "ready" && x.category !== "consent").length;
  const done = steps.filter((s) => s.action === "verify" && s.verification === "ok").length;
  return (
    <Card className="p-6">
      <SectionTitle gate="Step 5 · Fill" hint="In your own browser, with your own connection. Values come only from the signed payload and are read back after every step.">
        Filling the form in your browser
      </SectionTitle>
      {!run ? (
        <Callout tone="neutral" icon={<Loader2 className="size-4 animate-spin" />}>Finishing up…</Callout>
      ) : run.state === "queued" ? (
        <Callout tone={online ? "gate" : "warn"} icon={<Laptop className="size-4" />} title={online ? "Waiting for the runner to pick this up" : "Your runner is offline"}>
          {online ? "It claims work every couple of seconds." : <>Start it on your machine with <code>lintel start</code>. The fill begins as soon as it connects.</>}
        </Callout>
      ) : run.state === "waiting_user" ? (
        <Callout tone="warn" icon={<Hand className="size-4" />} title="Lintel needs you in the browser window"
          actions={<Button size="sm" variant="secondary" loading={resume.isPending} onClick={() => resume.mutate()}>I&apos;ve done it, resume</Button>}>
          {WAIT_COPY[run.waiting_reason ?? ""] ?? "Complete the step in the Lintel browser window, then press Resume."}
        </Callout>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3">
          <Loader2 className="size-5 animate-spin text-accent" />
          <div className="flex-1 text-[13.5px] text-ink">
            Typing and verifying values
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.min(100, (done / Math.max(1, fills)) * 100)}%` }} /></div>
          </div>
          <span className="text-[12.5px] tabular-nums text-ink-3">{done} / {fills}</span>
        </div>
      )}
      {steps.length > 0 && (
        <div className="mt-5">
          <div className="eyebrow mb-2">Step log · values are never logged, only a hash and a length</div>
          <StepList d={d} steps={steps} limit={14} />
        </div>
      )}
      {run && <div className="mt-5 flex justify-end"><Button size="sm" variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>Stop filling</Button></div>}
    </Card>
  );
}

function ModeChoice({ d, mode, setMode }: { d: Detail; mode: SupportMode; setMode: (m: SupportMode) => void }) {
  if (d.max_mode !== "approved_submission") return null;
  const opts: SupportMode[] = ["assisted_fill", "approved_submission"];
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {opts.map((m) => (
        <button key={m} type="button" onClick={() => setMode(m)}
          className={cx("rounded-xl border p-3.5 text-left transition", mode === m ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-line-strong")}>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
            {m === "assisted_fill" ? <MousePointerClick className="size-4" /> : <Lock className="size-4" />}
            {m === "assisted_fill" ? "I'll click Submit myself" : "Lintel clicks once"}
          </div>
          <div className="mt-1 text-[12.5px] text-ink-2">{MODE_HELP[m]}</div>
        </button>
      ))}
    </div>
  );
}

export function ReviewPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const a = d.application;
  const idx = factIndex(d);
  const [mode, setMode] = useState<SupportMode>(a.support_mode === "approved_submission" ? "approved_submission" : "assisted_fill");
  const approve = useAction(() => api.post(`/applications/${id}/approve`, { payload_hash: a.payload_hash, mode }), {
    invalidate: [["application", id]],
    success: "Approved and signed. Your click is next.",
  });
  const refill = useAction(() => api.post(`/applications/${id}/fill`), { invalidate: [["application", id]], success: "Filling the changes in your browser." });
  const previous = d.approvals.filter((x) => x.payload_hash !== a.payload_hash).at(-1);
  const prevAnswers = new Map((previous?.payload.answers ?? []).map((x) => [x.field_key, JSON.stringify(x.value)]));
  const free = d.drafts.filter((x) => x.decision === "draft_needed" && x.status !== "skipped");
  const rest = d.drafts.filter((x) => x.decision !== "draft_needed" && x.status === "ready" && x.category !== "consent");
  const payloadDoc = a.payload?.documents?.[0];
  return (
    <div className="space-y-6">
      <Card className="gate-ring p-6">
        <SectionTitle gate="Gate 3 · Review" hint="The approval covers this exact payload, not the page. It's signed for your runner, expires 30 minutes after you approve, and any change to any field voids it.">
          Approve exactly what will be sent
        </SectionTitle>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-line bg-surface-2 px-4 py-3 text-[12.5px] text-ink-2">
          <span>Payload <Hash value={a.payload_hash} n={12} /></span>
          <span>Destination <code className="text-ink">{a.payload?.destination.job_identity}</code></span>
          <span>Profile version <Hash value={a.profile_version_id} n={8} label="Profile version" /></span>
          <span>{a.payload?.answers.length ?? 0} answers · {a.payload?.documents.length ?? 0} document · {a.payload?.consents.length ?? 0} consent</span>
        </div>
        {!d.fill.current && (
          <Callout tone="warn" className="mt-4" icon={<RefreshCw className="size-4" />} title="The browser form holds an older version"
            actions={<Button size="sm" variant="secondary" loading={refill.isPending} onClick={() => refill.mutate()}>Fill the changes</Button>}>
            You changed an answer after the fill. Approval needs the browser to hold this exact payload.
          </Callout>
        )}
        {previous && (
          <Callout tone="neutral" className="mt-4" title="Changed since your last approval">
            {d.drafts.filter((x) => prevAnswers.has(x.field_key) && prevAnswers.get(x.field_key) !== JSON.stringify(a.payload?.answers.find((y) => y.field_key === x.field_key)?.value)).map((x) => x.label).join(", ") || "Documents or consents changed."}
          </Callout>
        )}
      </Card>

      <div className="space-y-4">{free.map((x) => <DraftCard key={x.field_key} d={d} draft={x} editable />)}</div>

      <Card className="overflow-hidden">
        <table className="w-full text-[13px]">
          <thead className="bg-muted/60 text-left text-[12px] text-ink-3">
            <tr><th className="px-5 py-2.5 font-medium">Field</th><th className="px-5 py-2.5 font-medium">Value</th><th className="px-5 py-2.5 font-medium">In your browser</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rest.map((x) => (
              <tr key={x.field_key}>
                <td className="px-5 py-2.5 align-top text-ink-2">{x.label}</td>
                <td className="px-5 py-2.5 align-top text-ink">
                  {x.category === "document" ? <span className="inline-flex flex-wrap items-center gap-1.5">{d.resume?.filename} <Hash value={payloadDoc?.sha256} /></span> : displayValue(x.value, x.options)}{" "}
                  {x.fact_ids.map((f) => <FactChip key={f} id={f} facts={d.facts} index={idx.get(f)} />)}
                </td>
                <td className="px-5 py-2.5 align-top">
                  {d.fill.verified[x.field_key] === "ok" ? <Badge tone="ok"><Check className="size-3" /> Read back</Badge> : d.fill.verified[x.field_key] ? <Badge tone="bad">Differs</Badge> : <Badge tone="muted">Not filled</Badge>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="p-6">
        <div className="eyebrow mb-2">Consents</div>
        <Consents d={d} editable />
        <div className="mt-6">
          <ModeChoice d={d} mode={mode} setMode={setMode} />
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button variant="gate" size="lg" icon={<ShieldCheck className="size-4" />} disabled={!d.readiness.ready || !d.fill.current} loading={approve.isPending} onClick={() => approve.mutate()}>
            Approve this payload
          </Button>
          <span className="text-[12.5px] text-ink-3">
            {mode === "approved_submission" ? "Lintel will click Submit once, after the Guard re-checks every field." : "Then switch to the Lintel browser window and click the site's own Submit."}
          </span>
        </div>
      </Card>
    </div>
  );
}

function Countdown({ until }: { until: string }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const ms = Math.max(0, new Date(until).getTime() - Date.now());
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return <span className="font-display text-[34px] tabular-nums leading-none text-ink">{m}:{String(s).padStart(2, "0")}</span>;
}

export function ApprovedPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const ap = d.live_approval;
  const submitRun = [...d.runs].reverse().find((r) => r.kind === "submit");
  const armed = submitRun?.state === "running" && d.steps.some((s) => s.run_id === submitRun.id && s.action === "guard_armed");
  const blocked = d.steps.filter((s) => submitRun && s.run_id === submitRun.id && s.action === "guard_check" && s.verification === "blocked").at(-1);
  const revoke = useAction(() => api.post(`/applications/${id}/revoke`), { invalidate: [["application", id]], success: "Approval revoked." });
  const arm = useAction(() => api.post(`/applications/${id}/arm`), { invalidate: [["application", id]], success: "Guard re-armed." });
  const sent = useAction(() => api.post(`/applications/${id}/report-sent`, { note: "sent outside the Guard" }), { invalidate: [["application", id]], success: "Recorded as sent by you." });
  const lintelClicks = d.application.support_mode === "approved_submission";
  const steps = [
    { label: "Approved and signed", done: true },
    { label: "Guard armed in your browser", done: armed, live: !armed },
    { label: lintelClicks ? "Lintel clicks Submit once" : "Your click on the site's Submit", done: false, live: armed },
  ];
  return (
    <Card className="gate-ring p-6">
      <SectionTitle gate="Step 7 · Send" hint={lintelClicks ? "Lintel clicks once, after the Guard re-reads every field against your approval." : "Switch to the Lintel browser window and click the site's own Submit. The Guard checks every field, checkbox and file against your approval first."}>
        {lintelClicks ? "Sending under your approval" : "Your click is next"}
      </SectionTitle>
      <div className="grid gap-5 sm:grid-cols-[1fr_auto]">
        <ol className="space-y-2.5">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center gap-3 text-[14px]">
              <span className={cx("grid size-6 place-items-center rounded-full", s.done ? "bg-ok text-white dark:text-[#06180e]" : s.live ? "bg-accent-soft text-accent" : "bg-muted text-ink-3")}>
                {s.done ? <Check className="size-3.5" strokeWidth={3} /> : s.live ? <Loader2 className="size-3.5 animate-spin" /> : i + 1}
              </span>
              <span className={s.done ? "text-ink" : "text-ink-2"}>{s.label}</span>
            </li>
          ))}
        </ol>
        {ap && (
          <div className="rounded-xl border border-line bg-surface-2 px-5 py-4 text-center">
            <div className="text-[12px] text-ink-3"><Clock className="mr-1 inline size-3" />Approval expires in</div>
            <div className="mt-1"><Countdown until={ap.expires_at} /></div>
            <div className="mt-1 text-[11.5px] text-ink-3">Payload <span className="font-mono">{ap.payload_hash.slice(0, 10)}</span></div>
          </div>
        )}
      </div>
      {blocked && (
        <Callout tone="bad" className="mt-5" icon={<AlertTriangle className="size-4" />} title="The Guard blocked a click">
          {blocked.detail}. Nothing was sent. In the browser you can put back the approved values, or send your edits to Lintel to re-approve.
        </Callout>
      )}
      {!armed && submitRun?.state !== "running" && submitRun?.state !== "queued" && (
        <Callout tone="warn" className="mt-5" title="The Guard isn't armed" actions={<Button size="sm" variant="secondary" loading={arm.isPending} onClick={() => arm.mutate()}>Arm it again</Button>}>
          The runner went offline before your click. Nothing was sent; start <code>lintel start</code> and arm the Guard again.
        </Callout>
      )}
      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        <Button variant="secondary" loading={revoke.isPending} onClick={() => revoke.mutate()}>Revoke approval</Button>
        <Button variant="ghost" loading={sent.isPending} onClick={() => sent.mutate()}>I submitted it myself</Button>
        <span className="ml-auto self-center text-[12px] text-ink-3">The Guard is a seatbelt, not a lock. Sending outside it is recorded honestly.</span>
      </div>
    </Card>
  );
}

export function SubmittingPanel({ d }: { d: Detail }) {
  const intent = d.intents.at(-1);
  return (
    <Card className="p-6">
      <SectionTitle gate="Step 7 · Send" hint="The submit intent was written before the click. Lintel is watching for the confirmation page.">Confirming…</SectionTitle>
      <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3 text-[13.5px]">
        <Loader2 className="size-5 animate-spin text-accent" />
        <span className="flex-1 text-ink">Intent recorded at fence <strong>{intent?.fence}</strong> · {dateTime(intent?.created_at)}</span>
      </div>
      <p className="mt-3 text-[12.5px] text-ink-3">If no confirmation appears, Lintel marks this “submission uncertain” and never sends it again on its own.</p>
    </Card>
  );
}

export function ModeLine({ mode }: { mode: SupportMode }) {
  return <span>{MODE_LABEL[mode]}</span>;
}

export function AuditTrio({ d }: { d: Detail }) {
  const consumed = d.approvals.find((a) => a.consumed_at);
  const intent = d.intents.at(-1);
  const adapterOutcome = d.outcomes.find((o) => o.source === "adapter");
  const items = [
    { label: "Approval", ok: Boolean(consumed), detail: consumed ? `consumed ${dateTime(consumed.consumed_at)}` : "none" },
    { label: "Submit intent", ok: Boolean(intent), detail: intent ? `fence ${intent.fence}` : "none" },
    { label: "Outcome", ok: Boolean(adapterOutcome), detail: adapterOutcome ? "confirmation observed" : "not observed" },
  ];
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {items.map((x) => (
        <div key={x.label} className={cx("rounded-xl border px-3.5 py-2.5", x.ok ? "border-ok-line bg-ok-soft/60" : "border-line bg-surface-2")}>
          <div className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
            {x.ok ? <BadgeCheck className="size-4 text-ok" /> : <CircleDot className="size-4 text-ink-3" />}{x.label}
          </div>
          <div className="text-[12px] text-ink-2">{x.detail}</div>
        </div>
      ))}
    </div>
  );
}

export { inFuture };
