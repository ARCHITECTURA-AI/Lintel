"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { BookUser, FileText, History, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/app/shared";
import { CandidateReview } from "@/components/candidates";
import { FactCard, ScopeBadge } from "@/components/domain";
import { TagInput } from "@/components/tags";
import { Badge, Button, Card, EmptyState, Field, Hash, Input, PageHeader, Select, Skeleton, Textarea } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { KIND_LABEL, SCOPE_LABEL, day } from "@/lib/format";
import { useAction, useCandidates, useDocuments, useFacts } from "@/lib/queries";
import type { ClaimScope, FactKind, FactRow } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const KINDS: FactKind[] = ["role", "achievement", "skill", "education", "certification", "contact", "link", "eligibility", "preference", "demographic"];
const SCOPE_FOR: Record<FactKind, ClaimScope[]> = {
  contact: ["personal"], link: ["personal"], eligibility: ["personal"], preference: ["personal"], demographic: ["personal"],
  role: ["employment", "project", "coursework"], achievement: ["employment", "project", "coursework", "education", "personal"],
  skill: ["employment", "project", "coursework", "personal"], education: ["education"], certification: ["certification"],
};

function FactForm({ fact, onDone }: { fact?: FactRow; onDone: () => void }) {
  const [kind, setKind] = useState<FactKind>(fact?.kind ?? "achievement");
  const [scope, setScope] = useState<ClaimScope>(fact?.claim_scope ?? "employment");
  const [statement, setStatement] = useState(fact?.statement ?? "");
  const [employer, setEmployer] = useState((fact?.attributes.employer as string) ?? "");
  const [skills, setSkills] = useState<string[]>((fact?.attributes.skills as string[]) ?? []);
  const [prof, setProf] = useState((fact?.attributes.proficiency as string) ?? "");
  const scopes = SCOPE_FOR[kind];
  const body = { kind, claim_scope: scopes.includes(scope) ? scope : scopes[0], statement, attributes: { ...(fact?.attributes ?? {}), employer: employer || undefined, skills, proficiency: prof || undefined } };
  const save = useAction(() => (fact ? api.post(`/facts/${fact.id}/supersede`, body) : api.post("/facts", body)), {
    invalidate: [["facts", false], ["facts", true]],
    success: fact ? "Saved as a new version. The old one stays in history." : "Added to your ledger.",
    onSuccess: onDone,
  });
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Kind"><Select value={kind} disabled={Boolean(fact)} onChange={(e) => setKind(e.target.value as FactKind)}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</Select></Field>
        <Field label="Where it happened"><Select value={scopes.includes(scope) ? scope : scopes[0]} onChange={(e) => setScope(e.target.value as ClaimScope)}>{scopes.map((s) => <option key={s} value={s}>{SCOPE_LABEL[s]}</option>)}</Select></Field>
      </div>
      <Field label="Statement" hint="what's true, in plain words"><Textarea value={statement} onChange={(e) => setStatement(e.target.value)} /></Field>
      {scope === "employment" && <Field label="Employer"><Input value={employer} onChange={(e) => setEmployer(e.target.value)} /></Field>}
      {["skill", "achievement", "role"].includes(kind) && <Field label="Tools and skills" hint="optional"><TagInput value={skills} onChange={setSkills} placeholder="e.g. Python, Postgres" /></Field>}
      {kind === "skill" && (
        <Field label="How well">
          <Select value={prof} onChange={(e) => setProf(e.target.value)}>
            <option value="">Not stated</option><option value="familiar">Familiar with</option><option value="working">Working experience</option><option value="expert">Expert</option>
          </Select>
        </Field>
      )}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onDone}>Cancel</Button><Button variant="primary" disabled={!statement.trim()} loading={save.isPending} onClick={() => save.mutate()}>{fact ? "Save new version" : "Add fact"}</Button></div>
    </div>
  );
}

function HistoryView({ id }: { id: string }) {
  const { data } = useQuery({ queryKey: ["fact-history", id], queryFn: () => api.get<FactRow[]>(`/facts/${id}/history`) });
  return (
    <ol className="relative space-y-3 border-l border-line pl-5">
      {data?.map((f, i) => (
        <li key={f.id} className="relative">
          <span className="absolute -left-[25px] top-1 size-2.5 rounded-full border-2 border-surface bg-ink-3" />
          <div className="text-[12px] text-ink-3">Version {i + 1} · {day(f.created_at)} {f.retracted && <Badge tone="bad">Removed</Badge>}</div>
          <FactCard fact={f} />
        </li>
      ))}
    </ol>
  );
}

function FactList({ facts }: { facts: FactRow[] }) {
  const [edit, setEdit] = useState<FactRow | null>(null);
  const [hist, setHist] = useState<string | null>(null);
  const retract = useAction((id: string) => api.post(`/facts/${id}/retract`), { invalidate: [["facts", false]], success: "Removed. Drafts won't cite it again." });
  const groups = KINDS.map((k) => [k, facts.filter((f) => f.kind === k)] as const).filter(([, v]) => v.length);
  return (
    <div className="space-y-6">
      {groups.map(([k, items]) => (
        <section key={k}>
          <div className="mb-2 flex items-center gap-2"><span className="eyebrow">{KIND_LABEL[k]}</span><Badge tone="muted">{items.length}</Badge></div>
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
            {items.map((f) => (
              <li key={f.id} className="group flex gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] text-ink">{f.statement}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
                    <ScopeBadge scope={f.claim_scope} />
                    {(f.attributes.skills as string[] | undefined)?.slice(0, 6).map((s) => <Badge key={s} tone="muted">{s}</Badge>)}
                    <span>{f.source_ref}</span>
                    {f.supersedes_fact_id && <span>· edited</span>}
                  </div>
                </div>
                <div className="flex shrink-0 items-start gap-0.5 opacity-60 transition group-hover:opacity-100">
                  <Button size="sm" variant="ghost" aria-label="History" onClick={() => setHist(f.id)}><History className="size-3.5" /></Button>
                  <Button size="sm" variant="ghost" aria-label="Edit" onClick={() => setEdit(f)}><Pencil className="size-3.5" /></Button>
                  <Button size="sm" variant="ghost" aria-label="Remove" onClick={() => retract.mutate(f.id)}><Trash2 className="size-3.5" /></Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <Modal open={Boolean(edit)} onOpenChange={(v) => !v && setEdit(null)} title="Edit fact" description="Facts are append-only. Saving creates a new version that supersedes this one; applications keep naming the version they were built from.">
        {edit && <FactForm fact={edit} onDone={() => setEdit(null)} />}
      </Modal>
      <Modal open={Boolean(hist)} onOpenChange={(v) => !v && setHist(null)} title="Fact history">{hist && <HistoryView id={hist} />}</Modal>
    </div>
  );
}

export default function LedgerPage() {
  const { data: facts, isLoading } = useFacts();
  const { data: cands } = useCandidates();
  const { data: docs } = useDocuments();
  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const shown = (facts ?? []).filter((f) => !q || f.statement.toLowerCase().includes(q.toLowerCase()));
  const tab = "rounded-lg px-3 py-1.5 text-[13px] text-ink-3 data-[state=active]:bg-surface data-[state=active]:font-medium data-[state=active]:text-ink data-[state=active]:shadow-sm";
  return (
    <div className="animate-rise">
      <PageHeader eyebrow="Gate 2 starts here" title="Fact ledger" description="Everything Lintel may say about you. Append-only and versioned: edits create new facts, and every application names the exact set it was built from."
        actions={<>
          <Button variant="secondary" icon={<Upload className="size-4" />} onClick={() => file.current?.click()}>Upload résumé</Button>
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Add a fact</Button>
        </>} />
      <input ref={file} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={async (e) => {
        const f = e.target.files?.[0]; if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        try { const r = await api.upload<{ candidates: number }>("/documents/resume", fd); toast.success(`${r.candidates} new candidate facts to review.`); qc.invalidateQueries(); }
        catch (err) { toast.error(errorMessage(err)); }
      }} />
      <Tabs.Root defaultValue={cands?.length ? "pending" : "facts"}>
        <Tabs.List className="mb-5 flex w-fit gap-1 rounded-xl bg-muted p-1">
          <Tabs.Trigger value="facts" className={tab}>Confirmed <span className="tabular-nums text-ink-3">{facts?.length ?? ""}</span></Tabs.Trigger>
          <Tabs.Trigger value="pending" className={tab}>To confirm <span className="tabular-nums text-ink-3">{cands?.length ?? ""}</span></Tabs.Trigger>
          <Tabs.Trigger value="docs" className={tab}>Documents</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="facts">
          <Input className="mb-5 max-w-sm" placeholder="Search your facts" value={q} onChange={(e) => setQ(e.target.value)} />
          {isLoading ? <Skeleton className="h-64" /> : shown.length ? <FactList facts={shown} /> : (
            <Card><EmptyState icon={<BookUser className="size-5" />} title="No facts yet">Upload a résumé or add facts by hand. Drafts can only cite what&apos;s here.</EmptyState></Card>
          )}
        </Tabs.Content>
        <Tabs.Content value="pending"><Card className="p-5"><CandidateReview /></Card></Tabs.Content>
        <Tabs.Content value="docs">
          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {docs?.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-[13.5px]">
                  <FileText className="size-4 text-ink-3" />
                  <a className="flex-1 font-medium text-ink hover:underline" href={`/api/documents/${d.id}/download`} target="_blank" rel="noreferrer">{d.filename}</a>
                  <Badge tone={d.kind === "resume_variant" ? "accent" : "neutral"}>{d.kind === "resume_variant" ? "Tailored variant" : d.kind === "resume_base" ? "Base résumé" : d.kind}</Badge>
                  <Hash value={d.sha256} />
                  <span className="text-[12px] text-ink-3">{day(d.created_at)}</span>
                </li>
              ))}
            </ul>
            {!docs?.length && <EmptyState title="No documents">Stored encrypted; approvals bind to their hashes, not filenames.</EmptyState>}
          </Card>
        </Tabs.Content>
      </Tabs.Root>
      <Modal open={adding} onOpenChange={setAdding} title="Add a fact" description="Say what's true. Lintel will cite it, never stretch it.">
        <FactForm onDone={() => setAdding(false)} />
      </Modal>
    </div>
  );
}
