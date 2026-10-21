"use client";

import * as Popover from "@radix-ui/react-popover";
import { AlertOctagon, CalendarClock, ChevronDown, CircleSlash, MessageSquareQuote, Rocket } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useAction } from "@/lib/queries";
import { FactChip, RequirementIcon } from "../domain";
import { Badge, Button, Callout, Card, Textarea, cx } from "../ui";
import { Modal, SectionTitle, factIndex, type Detail } from "./shared";

const REC_COPY = {
  apply: { title: "Lintel recommends: apply", tone: "ok" as const },
  ask: { title: "Lintel recommends: answer first, then decide", tone: "gate" as const },
  skip: { title: "Lintel recommends: skip", tone: "neutral" as const },
};

export function FitBriefView({ d }: { d: Detail }) {
  const brief = d.application.fit_brief;
  const idx = factIndex(d);
  const [showPosting, setShowPosting] = useState(false);
  if (!brief) return null;
  const rec = REC_COPY[brief.recommendation];
  const musts = brief.requirements.filter((r) => r.importance === "must");
  const nices = brief.requirements.filter((r) => r.importance === "nice");
  return (
    <div className="space-y-5">
      <Callout tone={rec.tone} title={rec.title} icon={<Rocket className="size-4" />}>
        {brief.recommendation_reason} <span className="text-ink-3">{brief.summary}</span>
      </Callout>

      {brief.conflicts.length > 0 && (
        <div className="space-y-2">
          {brief.conflicts.map((c, i) => (
            <Callout key={i} tone={c.severity === "hard" ? "bad" : "warn"} icon={<AlertOctagon className="size-4" />} title={`${c.filter}${c.severity === "soft" ? " (check)" : ""}`}>
              {c.detail}
            </Callout>
          ))}
        </div>
      )}

      {[{ title: "Must have", items: musts }, { title: "Nice to have", items: nices }].map((group) =>
        group.items.length ? (
          <div key={group.title}>
            <div className="eyebrow mb-2">{group.title}</div>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {group.items.map((r, i) => (
                <li key={i} className="flex gap-3 px-4 py-3">
                  <div className="pt-0.5"><RequirementIcon status={r.status} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-medium text-ink">{r.text}</div>
                    <div className="mt-0.5 text-[12.5px] text-ink-2">
                      {r.note}{" "}
                      {r.evidence_fact_ids.map((id) => <FactChip key={id} id={id} facts={d.facts} index={idx.get(id)} />)}
                    </div>
                    {r.interview_question && (
                      <div className="mt-2 flex gap-2 rounded-lg bg-surface-2 px-3 py-2 text-[12.5px] text-ink-2">
                        <MessageSquareQuote className="mt-0.5 size-3.5 shrink-0 text-accent" />
                        <span><span className="font-medium text-ink">Lintel will ask:</span> {r.interview_question}</span>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}

      <div className="flex flex-wrap gap-2 text-[12.5px]">
        {brief.compensation && <Badge tone="neutral">Pay: {brief.compensation}</Badge>}
        {brief.location && <Badge tone="neutral">{brief.location}</Badge>}
        <Badge tone="muted">Score {Math.round(brief.score * 100)} / 100</Badge>
      </div>

      <div className="rounded-xl border border-line">
        <button type="button" onClick={() => setShowPosting((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-left text-[13.5px] font-medium text-ink">
          <span>Posting text <span className="font-normal text-ink-3">· treated as data, never as instructions</span></span>
          <ChevronDown className={cx("size-4 text-ink-3 transition", showPosting && "rotate-180")} />
        </button>
        {showPosting && <div className="max-h-96 overflow-y-auto whitespace-pre-wrap border-t border-line px-4 py-3 text-[13px] leading-relaxed text-ink-2">{d.job.description}</div>}
      </div>
    </div>
  );
}

export function FitPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const [budgetFull, setBudgetFull] = useState(false);
  const [reason, setReason] = useState("");
  const go = useAction(() => api.post(`/applications/${id}/decide`, { go: true }), {
    invalidate: [["application", id], ["queue"]],
    success: "Going ahead. Lintel is building the form model and your questions.",
    quietError: true,
  });
  const nextWeek = useAction(() => api.post(`/applications/${id}/decide`, { go: true, next_week: true }), {
    invalidate: [["application", id], ["queue"]],
    success: "Queued for next week's budget.",
  });
  const skip = useAction(() => api.post(`/applications/${id}/decide`, { go: false, reason: reason || "you skipped this role" }), {
    invalidate: [["application", id], ["queue"]],
    success: "Skipped.",
  });
  const queued = d.application.week_budget_slot && d.application.week_budget_slot > d.budget.week_start;
  const b = d.budget;

  if (d.application.state === "imported" || !d.application.fit_brief) {
    return (
      <Card className="p-6">
        <SectionTitle gate="Gate 1 · Fit brief" hint="Reading the posting and comparing it with your confirmed facts.">Preparing the fit brief…</SectionTitle>
        <div className="space-y-3">{[0, 1, 2, 3].map((i) => <div key={i} className="shimmer h-12 rounded-xl" />)}</div>
      </Card>
    );
  }

  return (
    <Card className="gate-ring p-6">
      <SectionTitle gate="Gate 1 · Fit brief" hint="Requirements met with evidence, gaps, uncertain items and conflicts. You decide go or skip.">
        Is this role worth one of your applications?
      </SectionTitle>
      <FitBriefView d={d} />
      <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex flex-wrap items-center gap-2 rounded-b-[14px] border-t border-line bg-surface/95 px-6 py-4 backdrop-blur">
        {queued ? (
          <Badge tone="accent"><CalendarClock className="size-3" /> Queued for the week of {d.application.week_budget_slot}</Badge>
        ) : (
          <Button
            variant="gate"
            size="lg"
            loading={go.isPending}
            onClick={() =>
              go.mutate(undefined, {
                onError: (e) => {
                  if (e instanceof ApiError && e.code === "budget_full") setBudgetFull(true);
                  else toast.error(errorMessage(e));
                },
              })
            }
          >
            Go · use 1 of {b.remaining} left this week
          </Button>
        )}
        <Popover.Root>
          <Popover.Trigger asChild>
            <Button variant="secondary" size="lg" icon={<CircleSlash className="size-4" />}>Skip</Button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content sideOffset={8} align="start" className="z-50 w-80 rounded-xl border border-line bg-surface p-4 shadow-[var(--shadow-lg)]">
              <div className="text-[13.5px] font-medium text-ink">Why skip? <span className="font-normal text-ink-3">(optional)</span></div>
              <Textarea className="mt-2 min-h-[72px]" placeholder="e.g. Needs on-site in SF" value={reason} onChange={(e) => setReason(e.target.value)} />
              <Button className="mt-3 w-full" variant="primary" loading={skip.isPending} onClick={() => skip.mutate()}>Skip this role</Button>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
        <span className="ml-auto text-[12.5px] text-ink-3">{b.used} of {b.budget} used this week</span>
      </div>
      <Modal open={budgetFull} onOpenChange={setBudgetFull} title="This week's budget is used" description={`You set ${b.budget} applications a week. The surplus waits, so effort goes to the roles most likely to convert.`}>
        <div className="flex flex-wrap gap-2">
          <Button variant="gate" loading={nextWeek.isPending} onClick={() => nextWeek.mutate(undefined, { onSuccess: () => setBudgetFull(false) })}>Queue for next week</Button>
          <Button variant="secondary" onClick={() => (window.location.href = "/settings#budget")}>Raise my budget</Button>
        </div>
      </Modal>
    </Card>
  );
}
