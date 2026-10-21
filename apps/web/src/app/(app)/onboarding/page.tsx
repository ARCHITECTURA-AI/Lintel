"use client";

import { ArrowLeft, ArrowRight, Check, FileUp, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CandidateReview } from "@/components/candidates";
import { Wordmark } from "@/components/logo";
import { PairInstructions } from "@/components/pair";
import { TagInput } from "@/components/tags";
import { Badge, Button, Callout, Card, Field, Input, Toggle, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useCandidates, useFacts, useMe, useWatchlist } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import type { HardFilters, Targets } from "@/lib/types";

const STEPS = ["Résumé", "Confirm facts", "Targets", "Filters & budget", "Watchlist", "Runner"];
const LAB = process.env.NEXT_PUBLIC_LAB_URL ?? "http://localhost:4100";
const COUNTRIES = [["US", "United States"], ["UK", "United Kingdom"], ["CA", "Canada"], ["DE", "Germany"], ["IN", "India"]] as const;

function ResumeStep({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const upload = async (file: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.upload<{ candidates: number }>("/documents/resume", fd);
      toast.success(`Read ${r.candidates} candidate facts from ${file.name}.`);
      qc.invalidateQueries({ queryKey: ["candidates"] });
      onDone();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <h2 className="font-display text-[28px] text-ink">Start with your résumé</h2>
      <p className="mt-1 text-[14px] text-ink-2">Lintel reads it into candidate facts. Nothing is used until you confirm it. Contact details are pulled out locally and never shown to a model.</p>
      <button type="button" onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
        className={cx("mt-6 flex w-full flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 transition", drag ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2 hover:border-ink-3")}>
        {busy ? <Loader2 className="size-7 animate-spin text-accent" /> : <FileUp className="size-7 text-ink-3" />}
        <span className="mt-3 text-[14.5px] font-medium text-ink">{busy ? "Reading your résumé…" : "Drop a PDF, DOCX or text file"}</span>
        <span className="mt-1 text-[12.5px] text-ink-3">or click to choose · up to 5 MB · stored encrypted, with its hash</span>
      </button>
      <input ref={input} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
    </div>
  );
}

function FactsStep() {
  const { data: facts } = useFacts();
  const { data: cands } = useCandidates();
  return (
    <div>
      <h2 className="font-display text-[28px] text-ink">Confirm what&apos;s true</h2>
      <p className="mt-1 mb-6 text-[14px] text-ink-2">
        Each confirmed fact joins your ledger with its source line. Drafts may only cite confirmed facts. Edit anything that overstates, and reject anything wrong.
      </p>
      <div className="mb-4 flex gap-2"><Badge tone="ok">{facts?.length ?? 0} confirmed</Badge><Badge tone="neutral">{cands?.length ?? 0} waiting</Badge></div>
      <CandidateReview />
    </div>
  );
}

function TargetsStep({ t, setT }: { t: Targets; setT: (t: Targets) => void }) {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-display text-[28px] text-ink">What are you looking for?</h2>
        <p className="mt-1 text-[14px] text-ink-2">Roles on your watchlist that match become fit briefs. Everything else stays visible under Jobs.</p>
      </div>
      <Field label="Titles to match" hint="any word in the title"><TagInput value={t.titles ?? []} onChange={(v) => setT({ ...t, titles: v })} placeholder="e.g. backend, ml engineer" suggestions={["engineer", "backend", "ai engineer", "ml engineer", "platform"]} /></Field>
      <Field label="Titles to exclude"><TagInput value={t.exclude_titles ?? []} onChange={(v) => setT({ ...t, exclude_titles: v })} placeholder="e.g. principal" suggestions={["senior staff", "principal", "director", "manager"]} /></Field>
      <Field label="Locations"><TagInput value={t.locations ?? []} onChange={(v) => setT({ ...t, locations: v })} placeholder="e.g. remote, india, london" suggestions={["remote", "india", "united states", "london"]} /></Field>
      <label className="flex items-center gap-3 text-[13.5px] text-ink"><Toggle checked={t.remote_ok ?? true} onChange={(v) => setT({ ...t, remote_ok: v })} label="Remote roles anywhere" /> Include remote roles anywhere</label>
    </div>
  );
}

function FiltersStep({ f, setF, budget, setBudget }: { f: HardFilters; setF: (f: HardFilters) => void; budget: number; setBudget: (n: number) => void }) {
  const needs = f.needs_sponsorship ?? {};
  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-[28px] text-ink">Hard filters and your weekly budget</h2>
        <p className="mt-1 text-[14px] text-ink-2">Fit briefs flag roles that conflict with these. Lintel never guesses your work authorization; it asks, and only reuses what you confirm.</p>
      </div>
      <div>
        <div className="mb-2 text-[13px] font-medium text-ink">Do you need visa sponsorship to work in…</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {COUNTRIES.map(([code, name]) => (
            <div key={code} className="flex items-center justify-between rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px]">
              <span className="text-ink">{name}</span>
              <div className="flex gap-1">
                {[["Yes", true], ["No", false]].map(([lbl, v]) => (
                  <button key={String(lbl)} type="button" onClick={() => setF({ ...f, needs_sponsorship: { ...needs, [code]: v as boolean } })}
                    className={cx("h-7 rounded-lg border px-2.5 text-[12.5px]", needs[code] === v ? "border-accent bg-accent-soft font-medium text-accent-ink" : "border-line text-ink-3 hover:text-ink")}>{lbl}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <Field label="Exclude seniority"><TagInput value={f.exclude_seniority ?? []} onChange={(v) => setF({ ...f, exclude_seniority: v })} suggestions={["staff", "principal", "director", "intern"]} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Minimum pay" hint="per year">
          <Input type="number" min={0} value={f.min_salary?.amount ?? ""} onChange={(e) => setF({ ...f, min_salary: { ...f.min_salary, amount: e.target.value ? Number(e.target.value) : undefined } })} placeholder="e.g. 60000" />
        </Field>
        <Field label="Currency"><Input value={f.min_salary?.currency ?? "USD"} onChange={(e) => setF({ ...f, min_salary: { ...f.min_salary, currency: e.target.value.toUpperCase() } })} /></Field>
      </div>
      <div className="rounded-2xl border border-accent-line bg-accent-soft/60 p-5">
        <div className="flex items-baseline justify-between">
          <div className="text-[14px] font-semibold text-ink">Applications per week</div>
          <div className="font-display text-[34px] leading-none text-ink tabular-nums">{budget}</div>
        </div>
        <input type="range" min={1} max={20} value={budget} onChange={(e) => setBudget(Number(e.target.value))} className="mt-3 w-full accent-[var(--accent)]" aria-label="Weekly budget" />
        <p className="mt-2 text-[12.5px] text-ink-2">Fewer, better applications. The queue ranks by fit and the surplus waits for next week. Most people do well with 3 to 8.</p>
      </div>
    </div>
  );
}

function WatchlistStep() {
  const { data } = useWatchlist();
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const add = async (u: string) => {
    setBusy(true);
    try {
      await api.post("/watchlist", { url: u });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      setUrl("");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const lab = [["greenhouse", "acme"], ["lever", "northwind"], ["ashby", "globex"], ["greenhouse", "initech"]];
  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-display text-[28px] text-ink">Companies to watch</h2>
        <p className="mt-1 text-[14px] text-ink-2">Paste a careers page. Lintel detects Greenhouse, Lever or Ashby and reads the public job board a few times a day. No scraping, no logins.</p>
      </div>
      <div className="flex gap-2">
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jobs.lever.co/company or a careers page" onKeyDown={(e) => e.key === "Enter" && url && add(url)} />
        <Button variant="primary" loading={busy} disabled={!url} onClick={() => add(url)}>Add</Button>
      </div>
      <Callout tone="gate" title="Try it with Lintel Lab" actions={<Button size="sm" variant="secondary" loading={busy} onClick={async () => { for (const [p, s] of lab) await add(`${LAB}/${p}/${s}`); }}>Add the four Lab companies</Button>}>
        A local test site with Greenhouse-, Lever- and Ashby-style boards and every awkward case.
      </Callout>
      {data && data.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {data.map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-4 py-2.5 text-[13.5px]">
              <Check className="size-4 text-ok" /><span className="flex-1 text-ink">{c.name}</span>
              <Badge tone="muted">{c.platform}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const [step, setStep] = useState(0);
  const [targets, setTargets] = useState<Targets>({ titles: [], exclude_titles: [], locations: [], remote_ok: true });
  const [filters, setFilters] = useState<HardFilters>({});
  const [budget, setBudget] = useState(5);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (me) {
      if (me.targets && Object.keys(me.targets).length) setTargets(me.targets);
      if (me.hard_filters && Object.keys(me.hard_filters).length) setFilters(me.hard_filters);
      setBudget(me.weekly_budget);
    }
  }, [me]);
  const save = async (extra: Record<string, unknown> = {}) => {
    setSaving(true);
    try {
      const locs = (targets.locations ?? []).map((l) => l[0].toUpperCase() + l.slice(1));
      await api.patch("/me", { targets, hard_filters: { ...filters, locations: filters.locations ?? locs }, weekly_budget: budget, ...extra });
      qc.invalidateQueries({ queryKey: ["me"] });
    } finally {
      setSaving(false);
    }
  };
  const next = async () => {
    if (step === 2 || step === 3) await save();
    if (step === STEPS.length - 1) {
      await save({ onboarding: { done: true } });
      router.replace("/");
      return;
    }
    setStep(step + 1);
  };
  return (
    <div className="min-h-dvh bg-bg">
      <header className="flex items-center justify-between px-6 py-5"><Wordmark /><span className="text-[13px] text-ink-3">Step {step + 1} of {STEPS.length}</span></header>
      <div className="mx-auto max-w-3xl px-4 pb-24">
        <ol className="mb-8 grid grid-cols-6 gap-1.5" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s}>
              <div className={cx("h-1 rounded-full", i <= step ? "bg-accent" : "bg-muted")} />
              <div className={cx("mt-1.5 hidden text-[11.5px] sm:block", i === step ? "font-medium text-ink" : "text-ink-3")}>{s}</div>
            </li>
          ))}
        </ol>
        <Card className="p-6 sm:p-8">
          {step === 0 && <ResumeStep onDone={() => setStep(1)} />}
          {step === 1 && <FactsStep />}
          {step === 2 && <TargetsStep t={targets} setT={setTargets} />}
          {step === 3 && <FiltersStep f={filters} setF={setFilters} budget={budget} setBudget={setBudget} />}
          {step === 4 && <WatchlistStep />}
          {step === 5 && (
            <div>
              <h2 className="font-display text-[28px] text-ink">Pair your Local Runner</h2>
              <p className="mt-1 mb-6 text-[14px] text-ink-2">The cloud plans and remembers; your machine acts. You can do this later: until then, Lintel prepares packets you copy yourself.</p>
              <PairInstructions />
            </div>
          )}
          <div className="mt-8 flex items-center justify-between border-t border-line pt-5">
            <Button variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)} icon={<ArrowLeft className="size-4" />}>Back</Button>
            <div className="flex gap-2">
              {(step === 0 || step === 5) && <Button variant="ghost" onClick={next}>{step === 0 ? "Skip for now" : "Do this later"}</Button>}
              {step !== 0 && <Button variant="primary" loading={saving} onClick={next}>{step === STEPS.length - 1 ? "Finish" : "Continue"} <ArrowRight className="size-4" /></Button>}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
