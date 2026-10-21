"use client";

import { ArrowDown, ArrowUp, Check, ClipboardCopy, FileText, Pencil, PenLine, RefreshCw, Send, ShieldAlert, ShieldCheck, Wand2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { displayValue } from "@/lib/format";
import { useAction } from "@/lib/queries";
import type { DraftRow, SentenceRow, VariantRow } from "@/lib/types";
import { CheckList, FactChip, SentenceLine } from "../domain";
import { Badge, Button, Callout, Card, CopyButton, Hash, Textarea, cx } from "../ui";
import { Modal, SectionTitle, factIndex, type Detail } from "./shared";

const STATUS = {
  ready: { label: "Ready", tone: "ok" as const },
  needs_user: { label: "Needs you", tone: "warn" as const },
  blocked: { label: "Blocked by claim check", tone: "bad" as const },
  pending: { label: "Waiting", tone: "neutral" as const },
  skipped: { label: "Skipped", tone: "muted" as const },
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function DraftEditor({ d, draft, onClose }: { d: Detail; draft: DraftRow; onClose: () => void }) {
  const id = d.application.id;
  const [text, setText] = useState<string>(typeof draft.value === "string" ? draft.value : draft.sentences.map((s) => s.text).join(" "));
  const debounced = useDebounced(text, 450);
  const [preview, setPreview] = useState<SentenceRow[] | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!debounced.trim()) {
      setPreview([]);
      return;
    }
    setChecking(true);
    api
      .post<SentenceRow[]>(`/applications/${id}/check`, { text: debounced })
      .then((r) => !cancelled && setPreview(r))
      .catch(() => null)
      .finally(() => !cancelled && setChecking(false));
    return () => {
      cancelled = true;
    };
  }, [debounced, id]);
  const save = useAction(() => api.put<DraftRow>(`/applications/${id}/drafts/${draft.field_key}`, { text }), {
    invalidate: [["application", id]],
    success: (r) => ((r as DraftRow).status === "ready" ? "Saved. Every sentence traces to a fact." : "Saved, but blocked by the claim check."),
    onSuccess: () => onClose(),
  });
  const failing = preview?.filter((s) => !s.check.passed) ?? [];
  const idx = factIndex(d);
  return (
    <div className="space-y-4">
      <div>
        <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-[180px] text-[14px]" maxLength={draft.max_length ?? undefined} autoFocus />
        <div className="mt-1 flex justify-between text-[12px] text-ink-3">
          <span>{checking ? "Checking claims…" : failing.length ? `${failing.length} sentence${failing.length === 1 ? "" : "s"} can't be backed by your facts` : "Every sentence traces to your facts"}</span>
          {draft.max_length && <span className="tabular-nums">{text.length} / {draft.max_length}</span>}
        </div>
      </div>
      {preview && preview.length > 0 && (
        <ul className="space-y-2">
          {preview.map((s, i) => (
            <li key={i} className={cx("rounded-xl border p-3 text-[13px]", s.check.passed ? "border-line bg-surface-2" : "border-bad-line bg-bad-soft")}>
              <div className="flex gap-2">
                {s.check.passed ? <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" /> : <ShieldAlert className="mt-0.5 size-4 shrink-0 text-bad" />}
                <div className="min-w-0 flex-1">
                  <div className="text-ink">{s.text} {s.fact_ids.map((f) => <FactChip key={f} id={f} facts={d.facts} index={idx.get(f)} />)}</div>
                  {!s.check.passed && <div className="mt-2"><CheckList checks={s.check.checks.filter((c) => c.outcome !== "skipped")} /></div>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Callout tone="neutral">Edits go through the same three checks. A claim no confirmed fact supports is blocked. Add the fact to your ledger first if it&apos;s true.</Callout>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save answer</Button>
      </div>
    </div>
  );
}

export function DraftCard({ d, draft, editable }: { d: Detail; draft: DraftRow; editable: boolean }) {
  const id = d.application.id;
  const idx = factIndex(d);
  const [editing, setEditing] = useState(false);
  const redraft = useAction(() => api.post(`/applications/${id}/drafts/${draft.field_key}/redraft`), { invalidate: [["application", id]], success: "Redrafted and checked." });
  const accept = useAction(() => api.post(`/applications/${id}/drafts/${draft.field_key}/accept-partial`), { invalidate: [["application", id]], success: "Kept the sentences that trace to your facts." });
  const st = STATUS[draft.status];
  const cited = [...new Set(draft.sentences.flatMap((s) => s.fact_ids))];
  const hasFailed = draft.sentences.some((s) => !s.check.passed);
  const verified = d.fill.verified[draft.field_key];
  return (
    <article className="rounded-2xl border border-line bg-surface">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-5 py-3.5">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold text-ink">{draft.label}</div>
          <div className="mt-0.5 text-[12.5px] text-ink-3">{draft.status_detail}</div>
        </div>
        <div className="flex items-center gap-2">
          {verified === "ok" && <Badge tone="ok"><Check className="size-3" /> In your browser</Badge>}
          {draft.edited_by_user && <Badge tone="muted"><PenLine className="size-3" /> Edited by you</Badge>}
          <Badge tone={st.tone}>{st.label}</Badge>
        </div>
      </header>
      <div className="px-5 py-4 text-[14.5px] leading-[1.75] text-ink">
        {draft.sentences.length ? (
          draft.sentences.map((s, i) => <SentenceLine key={i} s={s} facts={d.facts} factIndex={idx} />)
        ) : (
          <span className="text-ink-3">No draft yet. Nothing in your ledger answers this; tell Lintel what&apos;s true and it drafts from that.</span>
        )}
      </div>
      {cited.length > 0 && (
        <div className="border-t border-line px-5 py-3">
          <div className="eyebrow mb-2">Sources</div>
          <ul className="space-y-1.5">
            {cited.map((fid) => (
              <li key={fid} className="flex gap-2 text-[12.5px] text-ink-2">
                <FactChip id={fid} facts={d.facts} index={idx.get(fid)} />
                <span className="min-w-0">{d.facts[fid]?.statement ?? "A fact that has since changed"}<span className="text-ink-3"> · {d.facts[fid]?.source_ref}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {editable && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          <Button size="sm" variant="secondary" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>Edit</Button>
          <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} loading={redraft.isPending} onClick={() => redraft.mutate()}>Redraft</Button>
          {hasFailed && draft.status === "needs_user" && (
            <Button size="sm" variant="ghost" loading={accept.isPending} onClick={() => accept.mutate()}>Keep only checked sentences</Button>
          )}
          {draft.max_length && typeof draft.value === "string" && <span className="ml-auto text-[12px] tabular-nums text-ink-3">{draft.value.length} / {draft.max_length}</span>}
        </footer>
      )}
      <Modal open={editing} onOpenChange={setEditing} title={draft.label} description="Write freely. Lintel checks each sentence as you type." wide>
        <DraftEditor d={d} draft={draft} onClose={() => setEditing(false)} />
      </Modal>
    </article>
  );
}

export function VariantCard({ d, v, editable }: { d: Detail; v: VariantRow; editable: boolean }) {
  const id = d.application.id;
  const approve = useAction(() => api.post(`/applications/${id}/variants/${v.id}/approve`), { invalidate: [["application", id]], success: "Variant approved and stored with its hash." });
  const reject = useAction(() => api.post(`/applications/${id}/variants/${v.id}/reject`), { invalidate: [["application", id]], success: "Keeping your base résumé." });
  const changes = v.diff.filter((c) => c.kind !== "unchanged");
  const groups = useMemo(() => {
    const m = new Map<string, typeof v.diff>();
    for (const c of v.diff) m.set(c.entry || c.group, [...(m.get(c.entry || c.group) ?? []), c]);
    return [...m.entries()];
  }, [v]);
  return (
    <article className="rounded-2xl border border-line bg-surface">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-5 py-3.5">
        <div>
          <div className="flex items-center gap-2 text-[14px] font-semibold text-ink"><Wand2 className="size-4 text-accent" /> Résumé tailored for this role</div>
          <div className="mt-0.5 text-[12.5px] text-ink-3">
            {v.check_summary.moved ?? 0} moved · {v.check_summary.reworded ?? 0} reworded{v.check_summary.reverted ? ` · ${v.check_summary.reverted} rewording(s) reverted by the claim check` : ""}. Never a new claim.
          </div>
        </div>
        <Badge tone={v.status === "approved" ? "ok" : v.status === "rejected" ? "muted" : "gate"}>{v.status === "proposed" ? "Your call" : v.status === "approved" ? "Approved" : "Not used"}</Badge>
      </header>
      <div className="space-y-4 px-5 py-4">
        {groups.map(([entry, items]) => (
          <div key={entry}>
            <div className="mb-1.5 text-[12.5px] font-semibold text-ink-2">{entry}</div>
            <ul className="space-y-1.5">
              {items.map((c) => (
                <li key={c.bullet_id} className={cx("flex gap-2 rounded-lg px-2.5 py-1.5 text-[13px]", c.kind === "moved" ? "bg-accent-soft/60" : c.kind === "reworded" ? "bg-ok-soft" : "")}>
                  <span className="mt-0.5 w-4 shrink-0 text-ink-3">
                    {c.kind === "moved" ? (c.to_index < c.from_index ? <ArrowUp className="size-3.5 text-accent" /> : <ArrowDown className="size-3.5 text-ink-3" />) : c.kind === "reworded" ? <PenLine className="size-3.5 text-ok" /> : "·"}
                  </span>
                  <span className="min-w-0">
                    {c.kind === "reworded" ? (
                      <>
                        <span className="text-ink-3 line-through decoration-ink-3/50">{c.before}</span>
                        <span className="block text-ink">{c.after}</span>
                      </>
                    ) : (
                      <span className={c.kind === "moved" ? "text-ink" : "text-ink-2"}>{c.after}</span>
                    )}
                    {c.kind !== "unchanged" && c.reason && <span className="block text-[11.5px] text-ink-3">{c.reason}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {!changes.length && <p className="text-[13px] text-ink-3">No changes proposed.</p>}
      </div>
      {v.status === "approved" && (
        <footer className="flex items-center gap-2 border-t border-line px-5 py-3 text-[12.5px] text-ink-2">
          <FileText className="size-3.5" /> Stored as PDF · <Hash value={v.document_sha256} />
          {v.document_id && <a className="ml-auto text-accent hover:underline" href={`/api/documents/${v.document_id}/download`} target="_blank" rel="noreferrer">Open PDF</a>}
        </footer>
      )}
      {editable && v.status === "proposed" && (
        <footer className="flex flex-wrap gap-2 border-t border-line px-5 py-3">
          <Button size="sm" variant="primary" loading={approve.isPending} onClick={() => approve.mutate()}>Use this variant</Button>
          <Button size="sm" variant="ghost" loading={reject.isPending} onClick={() => reject.mutate()}>Keep my base résumé</Button>
        </footer>
      )}
    </article>
  );
}

export function OtherAnswers({ d }: { d: Detail }) {
  const others = d.drafts.filter((x) => x.decision !== "draft_needed" && x.category !== "consent" && x.status !== "skipped");
  const idx = factIndex(d);
  if (!others.length) return null;
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <table className="w-full text-[13px]">
        <thead className="bg-muted/60 text-left text-[12px] text-ink-3">
          <tr><th className="px-4 py-2 font-medium">Field</th><th className="px-4 py-2 font-medium">Value</th><th className="hidden px-4 py-2 font-medium sm:table-cell">Source</th></tr>
        </thead>
        <tbody className="divide-y divide-line">
          {others.map((x) => (
            <tr key={x.field_key} className={x.status !== "ready" ? "bg-warn-soft/40" : ""}>
              <td className="px-4 py-2.5 align-top text-ink-2">{x.label}</td>
              <td className="px-4 py-2.5 align-top font-medium text-ink">
                {x.category === "document" ? (d.resume ? <span className="inline-flex items-center gap-1.5"><FileText className="size-3.5" />{d.resume.filename}</span> : "Upload a résumé") : x.status === "ready" ? displayValue(x.value, x.options) : <span className="font-normal text-warn">{x.status_detail}</span>}
              </td>
              <td className="hidden px-4 py-2.5 align-top text-ink-3 sm:table-cell">
                {x.fact_ids.map((f) => <FactChip key={f} id={f} facts={d.facts} index={idx.get(f)} />)}
                {!x.fact_ids.length && (x.category === "demographic" ? "Declined by default" : x.category === "document" ? "Matched by hash" : "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Consents({ d, editable }: { d: Detail; editable: boolean }) {
  const id = d.application.id;
  const consents = d.drafts.filter((x) => x.category === "consent");
  const set = useAction((v: { key: string; value: boolean }) => api.post(`/applications/${id}/consents/${v.key}`, { value: v.value }), { invalidate: [["application", id]] });
  if (!consents.length) return null;
  return (
    <div className="space-y-2">
      {consents.map((c) => (
        <label key={c.field_key} className={cx("flex cursor-pointer gap-3 rounded-xl border p-3.5 text-[13.5px]", c.value ? "border-ok-line bg-ok-soft/50" : "border-line bg-surface")}>
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={Boolean(c.value)} disabled={!editable || set.isPending}
            onChange={(e) => set.mutate({ key: c.field_key, value: e.target.checked })} />
          <span className="text-ink">{c.label}{c.required && <span className="text-bad"> *</span>}<span className="block text-[12px] text-ink-3">You tick consents yourself. Lintel never agrees on your behalf.</span></span>
        </label>
      ))}
    </div>
  );
}

function PacketDialog({ d, open, onOpenChange }: { d: Detail; open: boolean; onOpenChange: (v: boolean) => void }) {
  const items = d.drafts.filter((x) => x.status !== "skipped" && x.category !== "document");
  const all = items.map((x) => `${x.label}\n${displayValue(x.value, x.options)}`).join("\n\n");
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Your packet" description="Every answer in form order. Copy each into the site's form; Lintel doesn't click anything here." wide>
      <div className="mb-3 flex justify-end"><CopyButton text={all} label="Copy everything" /></div>
      <ul className="space-y-3">
        {items.map((x) => {
          const v = displayValue(x.value, x.options);
          return (
            <li key={x.field_key} className="rounded-xl border border-line p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="text-[12.5px] font-medium text-ink-3">{x.label}</div>
                <CopyButton text={v} />
              </div>
              <div className="mt-1 whitespace-pre-wrap text-[13.5px] text-ink">{v}</div>
            </li>
          );
        })}
      </ul>
      {d.resume && (
        <a className="mt-4 inline-flex items-center gap-2 text-[13.5px] font-medium text-accent hover:underline" href={`/api/documents/${d.resume.id}/download`} target="_blank" rel="noreferrer">
          <FileText className="size-4" /> Download the résumé to attach ({d.resume.filename})
        </a>
      )}
    </Modal>
  );
}

export function DraftsPanel({ d }: { d: Detail }) {
  const id = d.application.id;
  const [packet, setPacket] = useState(false);
  const free = d.drafts.filter((x) => x.decision === "draft_needed");
  const variant = d.variants.find((v) => v.status !== "rejected");
  const ready = d.readiness.ready;
  const draftOnly = d.application.support_mode === "draft_only";
  const fill = useAction(() => api.post(`/applications/${id}/fill`), { invalidate: [["application", id]], success: "Sent to your runner. Watch the Lintel browser window." });
  const sent = useAction(() => api.post(`/applications/${id}/report-sent`, { note: "sent from the packet" }), { invalidate: [["application", id]], success: "Recorded as sent by you." });
  const close = useAction(() => api.post(`/applications/${id}/close-packet`), { invalidate: [["application", id]], success: "Packet closed." });
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <SectionTitle gate="Step 4 · Drafts" hint="Every sentence cites the facts it rests on and passed the token check, the scope check and the verifier.">
          {free.length ? "Your answers, grounded" : "Your answers"}
        </SectionTitle>
        {!ready && (
          <Callout tone="warn" className="mb-4" title="A few things still need you">
            <ul className="mt-1 list-disc pl-4">{d.readiness.issues.map((i, k) => <li key={k}><span className="text-ink">{i.label}</span>: {i.detail}</li>)}</ul>
          </Callout>
        )}
        <div className="space-y-4">{free.map((x) => <DraftCard key={x.field_key} d={d} draft={x} editable />)}</div>
      </Card>

      {variant && <VariantCard d={d} v={variant} editable />}

      <Card className="p-6">
        <SectionTitle hint="Resolved from your ledger by handle. The field mapper only ever saw labels and handle names, never these values.">Everything else on the form</SectionTitle>
        <OtherAnswers d={d} />
        <div className="mt-5"><Consents d={d} editable /></div>
      </Card>

      <Card className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 p-4 shadow-[var(--shadow-lg)]">
        {draftOnly ? (
          <>
            <Button variant="gate" size="lg" icon={<ClipboardCopy className="size-4" />} onClick={() => setPacket(true)}>Open the packet</Button>
            <Button variant="secondary" loading={sent.isPending} onClick={() => sent.mutate()} icon={<Send className="size-4" />}>I sent it myself</Button>
            <Button variant="ghost" loading={close.isPending} onClick={() => close.mutate()}>Close without sending</Button>
            <span className="text-[12.5px] text-ink-3">This site is draft-only: Lintel prepares, you apply on the site.</span>
          </>
        ) : (
          <>
            <Button variant="gate" size="lg" disabled={!ready} loading={fill.isPending} onClick={() => fill.mutate()} icon={<Check className="size-4" />}>Fill in my browser</Button>
            <Button variant="ghost" onClick={() => setPacket(true)} icon={<ClipboardCopy className="size-4" />}>Packet</Button>
            <span className="text-[12.5px] text-ink-3">{ready ? "The Local Runner types these values into the site's form and reads each one back. It never clicks Submit." : "Resolve the items above to fill."}</span>
          </>
        )}
      </Card>
      <PacketDialog d={d} open={packet} onOpenChange={setPacket} />
    </div>
  );
}
