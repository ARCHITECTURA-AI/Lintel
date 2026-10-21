"use client";

import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { KIND_LABEL, SCOPE_LABEL } from "@/lib/format";
import { useAction, useCandidates } from "@/lib/queries";
import type { Candidate, ClaimScope, FactKind } from "@/lib/types";
import { ScopeBadge } from "./domain";
import { Badge, Button, Select, Spinner, Textarea } from "./ui";

const ORDER: FactKind[] = ["contact", "link", "role", "achievement", "education", "certification", "skill", "eligibility", "preference", "demographic"];
const SCOPES: ClaimScope[] = ["employment", "project", "coursework", "education", "certification", "personal"];

function Row({ c }: { c: Candidate }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(c.statement);
  const [scope, setScope] = useState<ClaimScope>(c.claim_scope);
  const inv = [["candidates"], ["facts", false], ["dashboard"]];
  const confirm = useAction(() => api.post(`/fact-candidates/${c.id}/confirm`, editing ? { statement: text, claim_scope: scope } : {}), { invalidate: inv });
  const reject = useAction(() => api.post(`/fact-candidates/${c.id}/reject`), { invalidate: inv });
  return (
    <li className="flex gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        {editing ? (
          <div className="space-y-2">
            <Textarea className="min-h-[64px]" value={text} onChange={(e) => setText(e.target.value)} />
            <Select value={scope} onChange={(e) => setScope(e.target.value as ClaimScope)} className="w-56">
              {SCOPES.map((s) => <option key={s} value={s}>{SCOPE_LABEL[s]}</option>)}
            </Select>
          </div>
        ) : (
          <>
            <p className="text-[13.5px] text-ink">{c.statement}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3"><ScopeBadge scope={c.claim_scope} /> {c.source_ref}</div>
          </>
        )}
      </div>
      <div className="flex shrink-0 items-start gap-1">
        {!editing && <Button size="sm" variant="ghost" aria-label="Edit" onClick={() => setEditing(true)}><Pencil className="size-3.5" /></Button>}
        <Button size="sm" variant="ghost" aria-label="Not true" loading={reject.isPending} onClick={() => reject.mutate()}><X className="size-3.5" /></Button>
        <Button size="sm" variant="secondary" loading={confirm.isPending} onClick={() => confirm.mutate()} icon={<Check className="size-3.5" />}>Confirm</Button>
      </div>
    </li>
  );
}

export function CandidateReview() {
  const { data, isLoading } = useCandidates();
  const all = useAction((ids: string[]) => api.post("/fact-candidates/confirm-many", { ids }), {
    invalidate: [["candidates"], ["facts", false]],
    success: (r) => `${(r as { confirmed: number }).confirmed} facts confirmed.`,
  });
  if (isLoading) return <Spinner />;
  if (!data?.length) return <p className="text-[13.5px] text-ink-3">Nothing waiting for confirmation.</p>;
  const groups = ORDER.map((k) => [k, data.filter((c) => c.kind === k)] as const).filter(([, v]) => v.length);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent-line bg-accent-soft px-4 py-3">
        <p className="text-[13.5px] text-ink">Read each one. Only confirmed facts can ever be cited, and a project stays a project.</p>
        <Button size="sm" variant="gate" loading={all.isPending} onClick={() => all.mutate(data.map((c) => c.id))}>I&apos;ve read them all: confirm {data.length}</Button>
      </div>
      {groups.map(([k, items]) => (
        <div key={k}>
          <div className="mb-2 flex items-center gap-2"><span className="eyebrow">{KIND_LABEL[k]}</span><Badge tone="muted">{items.length}</Badge></div>
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">{items.map((c) => <Row key={c.id} c={c} />)}</ul>
        </div>
      ))}
    </div>
  );
}
