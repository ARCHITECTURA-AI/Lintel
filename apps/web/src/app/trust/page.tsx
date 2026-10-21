"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Minus, X } from "lucide-react";
import Link from "next/link";
import { Wordmark } from "@/components/logo";
import { Badge, Card, Skeleton, cx } from "@/components/ui";

type Report = {
  generated_at: string | null;
  version?: string;
  headline?: { label: string; value: string; target?: string; ok?: boolean }[];
  claim_check?: {
    cases: number; supported?: number; unsupported?: number; unsupported_leaked: number; leakage_rate: number; verifier_recall: number | null; false_blocks: number;
    by_category: { category: string; cases: number; caught: number; leaked: number }[];
    examples: { sentence: string; verdict: string; reason: string; category?: string }[];
    development?: { cases: number; unsupported: number; unsupported_leaked: number; false_blocks: number; supported: number };
    note?: string;
  };
  crash_tests?: { point: string; description: string; final_state: string; sends: number; resent: boolean; passed: boolean }[];
  lab?: { flow: string; skin: string; passed: boolean; detail: string }[];
  injection?: { case: string; target: string; held: boolean; detail: string }[];
  property_tests?: { name: string; examples: number; passed: boolean }[];
  guard?: { injected_mismatches: number; blocked: number };
  limits?: string[];
  will_not_do?: string[];
  note?: string;
};

function Mark({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) return <Minus className="size-4 text-ink-3" />;
  return ok ? <span className="grid size-5 place-items-center rounded-full bg-ok-soft text-ok"><Check className="size-3" strokeWidth={3} /></span> : <span className="grid size-5 place-items-center rounded-full bg-bad-soft text-bad"><X className="size-3" strokeWidth={3} /></span>;
}

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="mt-12">
      <h2 className="font-display text-[26px] text-ink">{title}</h2>
      {sub && <p className="mt-1 max-w-3xl text-[14px] text-ink-2">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function TrustReport() {
  const { data: r, isLoading } = useQuery({ queryKey: ["trust-report"], queryFn: () => fetch("/api/public/trust-report").then((x) => x.json() as Promise<Report>) });
  return (
    <div className="min-h-dvh bg-bg">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <Link href="/"><Wordmark /></Link>
        <Badge tone="gate">Public report</Badge>
      </header>
      <main className="mx-auto max-w-5xl px-6 pb-24">
        <p className="eyebrow">Trust Report</p>
        <h1 className="font-display mt-2 text-[44px] leading-[1.05] text-ink">A system designed to be wrong safely, with proof.</h1>
        <p className="mt-4 max-w-3xl text-[15.5px] leading-relaxed text-ink-2">
          Measured numbers from the claim-check evaluation, the crash tests, the property tests and the Lintel Lab flows. Failures are published next to successes; that&apos;s what makes the numbers believable.
          {r?.generated_at && <> Generated {new Date(r.generated_at).toLocaleString()}.</>}
        </p>
        {isLoading ? <Skeleton className="mt-10 h-64" /> : !r?.generated_at ? (
          <Card className="mt-10 p-6 text-[14px] text-ink-2">No report yet. Run <code>uv run lintel-evals</code> to generate it.</Card>
        ) : (
          <>
            {r.headline && (
              <div className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {r.headline.map((h) => (
                  <Card key={h.label} className="p-5">
                    <div className="flex items-center justify-between text-[12.5px] text-ink-3">{h.label}<Mark ok={h.ok} /></div>
                    <div className="font-display mt-1 text-[32px] leading-tight text-ink">{h.value}</div>
                    {h.target && <div className="text-[12px] text-ink-3">target {h.target}</div>}
                  </Card>
                ))}
              </div>
            )}
            {r.claim_check && (
              <Section title="Claim check" sub="Synthetic profiles and jobs built to tempt fabrication: project versus employment, overlapping dates, “familiar with” versus “expert”, invented numbers and employers. We score leakage of unsupported claims and report the verifier's recall separately.">
                <Card className="overflow-hidden">
                  <table className="w-full text-[13.5px]">
                    <thead className="bg-muted/60 text-left text-[12px] text-ink-3"><tr><th className="px-5 py-2.5 font-medium">Temptation</th><th className="px-3 py-2.5 text-right font-medium">Cases</th><th className="px-3 py-2.5 text-right font-medium">Caught</th><th className="px-5 py-2.5 text-right font-medium">Leaked</th></tr></thead>
                    <tbody className="divide-y divide-line">
                      {r.claim_check.by_category.map((c) => (
                        <tr key={c.category}><td className="px-5 py-2.5 text-ink">{c.category}</td><td className="px-3 py-2.5 text-right tabular-nums">{c.cases}</td><td className="px-3 py-2.5 text-right tabular-nums">{c.caught}</td><td className={cx("px-5 py-2.5 text-right tabular-nums", c.leaked ? "font-semibold text-bad" : "text-ink-3")}>{c.leaked}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
                <p className="mt-3 text-[13px] text-ink-2">
                  {r.claim_check.cases} cases · {r.claim_check.unsupported_leaked} unsupported claims leaked ({(r.claim_check.leakage_rate * 100).toFixed(1)}%) · {r.claim_check.false_blocks} true sentences blocked
                  {r.claim_check.verifier_recall !== null ? ` · the model-free verifier alone catches ${(r.claim_check.verifier_recall * 100).toFixed(0)}%; the token and scope checks catch the rest` : ""}.
                </p>
                {r.claim_check.development && (
                  <p className="mt-1 text-[13px] text-ink-3">
                    {r.claim_check.note} Development set: {r.claim_check.development.cases} cases, {r.claim_check.development.unsupported_leaked} of {r.claim_check.development.unsupported} leaked, {r.claim_check.development.false_blocks} of {r.claim_check.development.supported} true sentences blocked.
                  </p>
                )}
                {r.claim_check.examples.length > 0 && (
                  <Card className="mt-4 overflow-hidden"><ul className="divide-y divide-line">
                    {r.claim_check.examples.map((e) => (
                      <li key={e.sentence} className="px-5 py-3 text-[13.5px]">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={cx("rounded-full px-2 py-0.5 text-[11.5px] font-medium", e.verdict === "blocked" ? "bg-ok-soft text-ok" : e.verdict === "leaked" ? "bg-bad-soft text-bad" : "bg-warn-soft text-warn")}>{e.verdict}</span>
                          {e.category && <span className="text-[12px] text-ink-3">{e.category}</span>}
                        </div>
                        <div className="mt-1 text-ink">“{e.sentence}”</div>
                        <div className="text-[12.5px] text-ink-2">{e.reason}</div>
                      </li>
                    ))}
                  </ul></Card>
                )}
              </Section>
            )}
            {r.crash_tests && (
              <Section title="Crash tests" sub="The runner is killed at each step of the submit sequence. Lintel guarantees it never sends twice on its own authority; when it can't know, it says so.">
                <Card className="overflow-hidden">
                  <table className="w-full text-[13.5px]">
                    <thead className="bg-muted/60 text-left text-[12px] text-ink-3"><tr><th className="px-5 py-2.5 font-medium">Killed</th><th className="px-3 py-2.5 font-medium">Final state</th><th className="px-3 py-2.5 text-right font-medium">Sends observed</th><th className="px-5 py-2.5 font-medium">Result</th></tr></thead>
                    <tbody className="divide-y divide-line">
                      {r.crash_tests.map((c) => (
                        <tr key={c.point}><td className="px-5 py-2.5"><div className="text-ink">{c.point}</div><div className="text-[12px] text-ink-3">{c.description}</div></td><td className="px-3 py-2.5"><code>{c.final_state}</code></td><td className="px-3 py-2.5 text-right tabular-nums">{c.sends}</td><td className="px-5 py-2.5"><span className="flex items-center gap-2"><Mark ok={c.passed} />{c.resent ? "resent" : "never resent"}</span></td></tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              </Section>
            )}
            {r.lab && (
              <Section title="Lintel Lab flows" sub="Form skins that copy the patterns of Greenhouse, Lever and Ashby, plus conditional fields, multi-step flow, file upload, validation errors, session expiry, a CAPTCHA placeholder, an unexpected modal and a timeout right after submit.">
                <Card className="overflow-hidden"><ul className="divide-y divide-line">
                  {r.lab.map((l) => <li key={l.flow} className="flex items-start gap-3 px-5 py-3 text-[13.5px]"><Mark ok={l.passed} /><div className="min-w-0 flex-1"><div className="text-ink">{l.flow} <span className="text-ink-3">· {l.skin}</span></div><div className="text-[12.5px] text-ink-2">{l.detail}</div></div></li>)}
                </ul></Card>
                {r.guard && <p className="mt-3 text-[13px] text-ink-2">Submit Guard: blocked {r.guard.blocked} of {r.guard.injected_mismatches} injected mismatches.</p>}
              </Section>
            )}
            {r.injection && (
              <Section title="Prompt-injection suite" sub="Job text and page text that try to change tools, reveal data or trigger uploads. Page text is data: the planner reads fields, not prose, and tool availability comes from the mode and the registry.">
                <Card className="overflow-hidden"><ul className="divide-y divide-line">
                  {r.injection.map((i) => <li key={i.case} className="flex items-start gap-3 px-5 py-3 text-[13.5px]"><Mark ok={i.held} /><div><div className="text-ink">{i.case} <span className="text-ink-3">· {i.target}</span></div><div className="text-[12.5px] text-ink-2">{i.detail}</div></div></li>)}
                </ul></Card>
              </Section>
            )}
            {r.property_tests && (
              <Section title="Property tests">
                <Card className="overflow-hidden"><ul className="divide-y divide-line">
                  {r.property_tests.map((p) => <li key={p.name} className="flex items-center gap-3 px-5 py-3 text-[13.5px]"><Mark ok={p.passed} /><span className="flex-1 text-ink">{p.name}</span><span className="text-[12.5px] text-ink-3">{p.examples} generated examples</span></li>)}
                </ul></Card>
              </Section>
            )}
            <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2">
              {r.will_not_do && (
                <Card className="p-6"><h2 className="font-display text-[22px] text-ink">What Lintel will not do</h2>
                  <ul className="mt-3 space-y-2 text-[13.5px] text-ink-2">{r.will_not_do.map((x) => <li key={x} className="flex gap-2"><X className="mt-0.5 size-4 shrink-0 text-bad" />{x}</li>)}</ul></Card>
              )}
              {r.limits && (
                <Card className="p-6"><h2 className="font-display text-[22px] text-ink">Honest limits</h2>
                  <ul className="mt-3 space-y-2 text-[13.5px] text-ink-2">{r.limits.map((x) => <li key={x} className="flex gap-2"><Minus className="mt-0.5 size-4 shrink-0 text-ink-3" />{x}</li>)}</ul></Card>
              )}
            </div>
            {r.note && <p className="mt-8 text-[13px] text-ink-3">{r.note}</p>}
          </>
        )}
      </main>
    </div>
  );
}
