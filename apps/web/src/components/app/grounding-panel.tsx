"use client";

import { Check, Loader2, MessageSquareQuote, Sparkles, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { displayValue } from "@/lib/format";
import { useAction } from "@/lib/queries";
import type { TaskRow } from "@/lib/types";
import { FactCard } from "../domain";
import { Badge, Button, ButtonLink, Callout, Card, Input, Label, Textarea, Toggle, cx } from "../ui";
import { SectionTitle, type Detail } from "./shared";

function Choice({ options, value, onChange }: { options: { label: string; value: string }[]; value: string | null; onChange: (v: string) => void }) {
  if (options.length > 5) {
    return (
      <select className="field-input h-9" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  return (
    <div role="radiogroup" className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cx("h-9 rounded-[10px] border px-3.5 text-[13.5px] transition",
            value === o.value ? "border-accent bg-accent-soft font-medium text-accent-ink" : "border-line-strong bg-surface text-ink-2 hover:border-ink-3")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function UnknownAnswer({ t, appId }: { t: TaskRow; appId: string }) {
  const opts = (t.data.options as { label: string; value: string }[]) ?? [];
  const [value, setValue] = useState<string | null>(null);
  const eligibility = t.data.category === "eligibility";
  const [remember, setRemember] = useState(eligibility);
  const save = useAction(
    () => api.post(`/applications/${appId}/answers/${t.data.field_key}`, { value, scope: remember ? "all" : "application" }),
    { invalidate: [["application", appId]], success: "Saved as a confirmed fact." },
  );
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="text-[14px] font-medium text-ink">{t.title}{t.data.required ? <span className="text-bad"> *</span> : null}</div>
        <Badge tone={eligibility ? "gate" : "neutral"}>{eligibility ? "Never guessed" : t.data.category === "preference" ? "Your preference" : "Only you know"}</Badge>
      </div>
      <div className="mt-3">
        {opts.length ? (
          <Choice options={opts} value={value} onChange={setValue} />
        ) : t.data.field_type === "textarea" ? (
          <Textarea value={value ?? ""} onChange={(e) => setValue(e.target.value)} />
        ) : (
          <Input value={value ?? ""} onChange={(e) => setValue(e.target.value)} placeholder="Your answer" />
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-[12.5px] text-ink-2">
          <Toggle checked={remember} onChange={setRemember} label="Remember for all applications" />
          Remember for all applications
        </label>
        <Button size="sm" variant="primary" disabled={!value} loading={save.isPending} onClick={() => save.mutate()}>Save answer</Button>
      </div>
    </li>
  );
}

const SCOPES = [
  { value: "employment", label: "In a job" },
  { value: "project", label: "Personal project" },
  { value: "coursework", label: "Coursework" },
  { value: "personal", label: "Other" },
];

export function InterviewCard({ t, appId }: { t: TaskRow; appId?: string }) {
  const [answer, setAnswer] = useState("");
  const [scope, setScope] = useState("project");
  const [employer, setEmployer] = useState("");
  const inv = [["application", appId], ["tasks"], ["facts", false]];
  const save = useAction(
    () => api.post(`/tasks/${t.id}/interview`, { answer, claim_scope: scope, employer: scope === "employment" ? employer : null }),
    { invalidate: inv, success: "Saved to your ledger as a confirmed fact." },
  );
  const none = useAction(() => api.post(`/tasks/${t.id}/interview`, { none: true }), { invalidate: inv, success: "Noted. Lintel won't claim it." });
  return (
    <li className="rounded-xl border border-accent-line bg-surface p-4">
      <div className="flex gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent"><MessageSquareQuote className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] text-ink-3">{t.body}</div>
          <div className="mt-1 text-[14.5px] font-medium leading-snug text-ink">{t.title}</div>
        </div>
      </div>
      <Textarea className="mt-3" value={answer} onChange={(e) => setAnswer(e.target.value)}
        placeholder="Say what happened, where, and roughly how much. Your words become the fact a draft cites." />
      <div className="mt-3">
        <Label>Where was this?</Label>
        <Choice options={SCOPES} value={scope} onChange={setScope} />
        {scope === "employment" && <Input className="mt-2" placeholder="Employer" value={employer} onChange={(e) => setEmployer(e.target.value)} />}
        <p className="mt-2 text-[12px] text-ink-3">A personal project can never be written up as a job. Lintel keeps the difference.</p>
      </div>
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button size="sm" variant="ghost" loading={none.isPending} onClick={() => none.mutate()}>I haven&apos;t done this</Button>
        <Button size="sm" variant="primary" disabled={answer.trim().length < 3 || (scope === "employment" && !employer.trim())} loading={save.isPending} onClick={() => save.mutate()}>
          Save as a fact
        </Button>
      </div>
    </li>
  );
}

export function GroundingPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const [drafting, setDrafting] = useState(false);
  const open = d.tasks.filter((t) => t.status === "open");
  const unknown = open.filter((t) => t.type === "unknown_answer");
  const interviews = open.filter((t) => t.type === "fact_interview");
  const referral = open.find((t) => t.type === "referral");
  const blocking = d.grounding?.blocking.length ?? 0;
  const resolved = d.drafts.filter((x) => x.status === "ready" && x.decision !== "draft_needed");
  const confirm = useAction(() => api.post(`/applications/${id}/grounding/confirm`), {
    invalidate: [["application", id]],
    onSuccess: () => setDrafting(true),
  });

  if (drafting) {
    return (
      <Card className="p-8">
        <div className="flex flex-col items-center text-center">
          <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-accent"><Loader2 className="size-6 animate-spin" /></span>
          <div className="font-display mt-4 text-[22px] text-ink">Drafting from your confirmed facts</div>
          <p className="mt-1.5 max-w-md text-[13.5px] text-ink-2">
            Each sentence cites the facts behind it, then passes three checks: tokens, scope, and a separate verifier. A sentence that fails twice becomes a question for you.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="gate-ring p-6">
      <SectionTitle gate="Gate 2 · Grounding" hint="Lintel asks rather than guesses. Your answers become facts in your ledger, tagged with where they came from.">
        Confirm the facts this application depends on
      </SectionTitle>

      {unknown.length > 0 && (
        <section className="mt-5">
          <div className="eyebrow mb-2">Questions only you can answer · {unknown.length}</div>
          <ul className="space-y-3">{unknown.map((t) => <UnknownAnswer key={t.id} t={t} appId={id} />)}</ul>
        </section>
      )}

      {interviews.length > 0 && (
        <section className="mt-6">
          <div className="eyebrow mb-1">Fact Interview · {interviews.length}</div>
          <p className="mb-3 text-[13px] text-ink-2">The role asks for evidence your ledger doesn&apos;t have. Many weak applications are weak because true, relevant experience never reached the page.</p>
          <ul className="space-y-3">{interviews.map((t) => <InterviewCard key={t.id} t={t} appId={id} />)}</ul>
        </section>
      )}

      {d.grounding && d.grounding.plan.length > 0 && (
        <section className="mt-6">
          <div className="eyebrow mb-2">Facts your drafts will cite</div>
          <div className="space-y-3">
            {d.grounding.plan.map((p) => (
              <div key={p.field_key} className="rounded-xl border border-line bg-surface-2 p-4">
                <div className="text-[13.5px] font-medium text-ink">{p.label}</div>
                {p.fact_ids.length ? (
                  <ul className="mt-2.5 space-y-2.5">
                    {p.fact_ids.map((fid) => d.facts[fid] && <li key={fid} className="rounded-lg border border-line bg-surface p-3"><FactCard fact={d.facts[fid]} compact /></li>)}
                  </ul>
                ) : (
                  <p className="mt-1 text-[13px] text-ink-3">No confirmed fact speaks to this yet. Lintel will ask you after drafting.</p>
                )}
              </div>
            ))}
          </div>
          <p className="mt-2 text-[12.5px] text-ink-3">Something wrong? <Link href="/ledger" className="text-accent hover:underline">Fix it in your ledger</Link>; facts are versioned, never edited in place.</p>
        </section>
      )}

      {resolved.length > 0 && (
        <section className="mt-6">
          <div className="eyebrow mb-2">Filled from your ledger · {resolved.length}</div>
          <ul className="grid gap-x-6 gap-y-1.5 rounded-xl border border-line px-4 py-3 sm:grid-cols-2">
            {resolved.map((x) => (
              <li key={x.field_key} className="flex min-w-0 items-baseline gap-2 text-[13px]">
                <Check className="size-3.5 shrink-0 translate-y-0.5 text-ok" />
                <span className="shrink-0 text-ink-3">{x.label}</span>
                <span className="truncate text-ink">{x.category === "document" ? (d.resume?.filename ?? "Résumé") : displayValue(x.value, x.options)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {referral && (
        <Callout className="mt-6" icon={<UserPlus className="size-4" />} title={referral.title} actions={<ButtonLink href="/contacts" size="sm">Add contacts</ButtonLink>}>
          {referral.body}
        </Callout>
      )}

      <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex flex-wrap items-center gap-3 rounded-b-[14px] border-t border-line bg-surface/95 px-6 py-4 backdrop-blur">
        <Button variant="gate" size="lg" disabled={blocking > 0} loading={confirm.isPending} icon={<Sparkles className="size-4" />} onClick={() => confirm.mutate()}>
          Confirm facts and draft
        </Button>
        <span className="text-[12.5px] text-ink-3">
          {blocking > 0 ? `Answer ${blocking} required question${blocking === 1 ? "" : "s"} first.` : interviews.length ? "Unanswered interview questions are set aside, never guessed." : "Every fact above is confirmed by you."}
        </span>
      </div>
    </Card>
  );
}
