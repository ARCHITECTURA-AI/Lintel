"use client";

import { AlertTriangle, CircleCheck, MailQuestion, Send, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { STAGE_LABEL, USER_STAGES, dateTime, day } from "@/lib/format";
import { useAction } from "@/lib/queries";
import type { OutcomeStage } from "@/lib/types";
import { Ago } from "../domain";
import { Badge, Button, ButtonLink, Callout, Card, CopyButton, Field, Input, Select, Textarea, cx } from "../ui";
import { AuditTrio } from "./execution-panels";
import { SectionTitle, type Detail } from "./shared";

function StageForm({ d, allowReported }: { d: Detail; allowReported?: boolean }) {
  const id = d.application.id;
  const stages: OutcomeStage[] = allowReported ? ["user_reported_submitted", ...USER_STAGES] : USER_STAGES;
  const [stage, setStage] = useState<OutcomeStage>(stages[0]);
  const [note, setNote] = useState("");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const add = useAction(() => api.post(`/applications/${id}/outcomes`, { stage, note, occurred_at: new Date(when + "T12:00:00").toISOString() }), {
    invalidate: [["application", id], ["review"]],
    success: "Recorded. Your weekly review uses it.",
    onSuccess: () => setNote(""),
  });
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_160px]">
      <Field label="What happened">
        <Select value={stage} onChange={(e) => setStage(e.target.value as OutcomeStage)}>
          {stages.map((s) => <option key={s} value={s}>{s === "user_reported_submitted" ? "I sent it myself" : STAGE_LABEL[s]}</option>)}
        </Select>
      </Field>
      <Field label="When"><Input type="date" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
      <div className="sm:col-span-2">
        <Field label="Note" hint="optional"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Recruiter call booked for Tuesday" /></Field>
      </div>
      <div className="sm:col-span-2"><Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>Add to the outcome loop</Button></div>
    </div>
  );
}

function Evidence({ d }: { d: Detail }) {
  const id = d.application.id;
  const [text, setText] = useState("");
  const [ref, setRef] = useState("");
  const save = useAction(() => api.post(`/applications/${id}/evidence`, { text, reference_number: ref || null }), {
    invalidate: [["application", id]],
    success: "Evidence saved.",
    onSuccess: () => { setText(""); setRef(""); },
  });
  return (
    <div className="space-y-3">
      {d.evidence.map((e) => (
        <div key={e.id} className="rounded-xl border border-line bg-surface-2 p-3 text-[13px]">
          {e.reference_number && <div className="font-mono text-[12.5px] text-ink">Reference {e.reference_number}</div>}
          {e.text && <p className="mt-1 text-ink-2">{e.text}</p>}
          <div className="mt-1 text-[11.5px] text-ink-3">{e.kind.replace("_", " ")} · {dateTime(e.created_at)}{e.page_hash ? ` · page ${e.page_hash.slice(0, 10)}` : ""}</div>
        </div>
      ))}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_180px]">
        <Textarea className="min-h-[60px]" placeholder="Paste the confirmation message or email" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="space-y-2">
          <Input placeholder="Reference number" value={ref} onChange={(e) => setRef(e.target.value)} />
          <Button className="w-full" size="sm" variant="secondary" disabled={!text && !ref} loading={save.isPending} onClick={() => save.mutate()}>Save evidence</Button>
        </div>
      </div>
    </div>
  );
}

function FollowUps({ d }: { d: Detail }) {
  const fus = d.follow_ups.filter((f) => f.status !== "dismissed");
  const mark = useAction((v: { id: string; status: string }) => api.post(`/follow-ups/${v.id}/mark`, { status: v.status }), { invalidate: [["application", d.application.id]] });
  const draftNow = useAction((fid: string) => api.post(`/follow-ups/${fid}/draft`), { invalidate: [["application", d.application.id]] });
  if (!fus.length) return <p className="text-[13px] text-ink-3">A follow-up is drafted for you if there&apos;s no reply after your no-reply window.</p>;
  return (
    <ul className="space-y-3">
      {fus.map((f) => (
        <li key={f.id} className="rounded-xl border border-line p-4">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <Badge tone={f.status === "ready" ? "ok" : f.status === "sent" ? "muted" : "neutral"}>{f.kind === "referral_ask" ? "Referral ask" : "Follow-up"} · {f.status}</Badge>
            <span className="text-ink-3">{f.status === "scheduled" ? `Due ${day(f.due_at)}` : f.sent_at ? `Sent ${day(f.sent_at)}` : ""}</span>
          </div>
          {f.draft ? (
            <>
              <p className="mt-2 whitespace-pre-wrap rounded-lg bg-surface-2 p-3 text-[13.5px] text-ink">{f.draft}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <CopyButton text={f.draft} />
                {f.status !== "sent" && <Button size="sm" variant="secondary" icon={<Send className="size-3.5" />} onClick={() => mark.mutate({ id: f.id, status: "sent" })}>I sent it</Button>}
                {f.status !== "sent" && <Button size="sm" variant="ghost" onClick={() => mark.mutate({ id: f.id, status: "dismissed" })}>Dismiss</Button>}
              </div>
            </>
          ) : (
            <Button className="mt-2" size="sm" variant="secondary" loading={draftNow.isPending} onClick={() => draftNow.mutate(f.id)}>Draft it now</Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function Referrals({ d }: { d: Detail }) {
  const id = d.application.id;
  const ask = useAction((cid: string) => api.post(`/applications/${id}/referral/${cid}`), { invalidate: [["application", id]], success: "Drafted. Copy it and send it yourself." });
  if (!d.contacts.length) {
    return (
      <Callout icon={<UserPlus className="size-4" />} title={`Do you know anyone at ${d.job.company_name}?`} actions={<ButtonLink href="/contacts" size="sm">Add a contact</ButtonLink>}>
        A referral is a human lever autofill can&apos;t pull. Lintel suggests who to ask and drafts the note; it never messages anyone.
      </Callout>
    );
  }
  return (
    <ul className="space-y-2">
      {d.contacts.map((c, i) => (
        <li key={c.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium text-ink">{c.name} {i === 0 && <Badge tone="accent">Best person to ask</Badge>}</div>
            <div className="text-[12.5px] text-ink-3">{c.relationship.replace("_", " ")} · {c.company}</div>
          </div>
          <Button size="sm" variant="secondary" loading={ask.isPending} onClick={() => ask.mutate(c.id)}>Draft a referral ask</Button>
        </li>
      ))}
    </ul>
  );
}

export function OutcomePanel({ d }: { d: Detail }) {
  const s = d.application.state;
  const ref = d.evidence.find((e) => e.reference_number)?.reference_number;
  return (
    <div className="space-y-6">
      {s === "confirmed" && (
        <Card className="p-6">
          <div className="flex items-start gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-ok-soft text-ok"><CircleCheck className="size-6" /></span>
            <div>
              <div className="eyebrow text-ok">Sent and confirmed</div>
              <h3 className="font-display mt-1 text-[26px] leading-tight text-ink">The application went through</h3>
              <p className="mt-1 text-[13.5px] text-ink-2">
                Confirmation observed {dateTime(d.application.confirmed_at)}{ref ? <> · reference <span className="font-mono text-ink">{ref}</span></> : null}. Lintel never sends it again.
              </p>
            </div>
          </div>
          <div className="mt-5"><AuditTrio d={d} /></div>
        </Card>
      )}
      {s === "submission_uncertain" && (
        <Card className="border-warn-line p-6">
          <div className="flex items-start gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-warn-soft text-warn"><AlertTriangle className="size-6" /></span>
            <div>
              <div className="eyebrow text-warn">Submission uncertain</div>
              <h3 className="font-display mt-1 text-[26px] leading-tight text-ink">Lintel can&apos;t confirm this was sent</h3>
              <p className="mt-1 max-w-2xl text-[13.5px] text-ink-2">
                The submit intent was written, the click happened, then no confirmation was seen. Lintel will not retry: a second click could send it twice.
                Check your email or the site. If you find a confirmation, record it below.
              </p>
            </div>
          </div>
          <div className="mt-5"><AuditTrio d={d} /></div>
          <div className="mt-6 border-t border-line pt-5"><StageForm d={d} allowReported /></div>
        </Card>
      )}
      {s === "user_reported_submitted" && (
        <Card className="p-6">
          <div className="flex items-start gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent"><MailQuestion className="size-6" /></span>
            <div>
              <div className="eyebrow">Sent by you</div>
              <h3 className="font-display mt-1 text-[26px] leading-tight text-ink">You sent this one yourself</h3>
              <p className="mt-1 text-[13.5px] text-ink-2">Recorded honestly as sent outside the Guard. Paste the confirmation so your outcome record has evidence.</p>
            </div>
          </div>
        </Card>
      )}

      <Card className="p-6">
        <SectionTitle gate="Step 8 · Learn" hint="Stages from sent to offer. Your weekly review shows which variant, source and company size produced replies.">Outcome loop</SectionTitle>
        <ol className="mb-5 space-y-2">
          {d.outcomes.map((o) => (
            <li key={o.id} className="flex items-center gap-3 text-[13.5px]">
              <span className={cx("size-2 rounded-full", ["interview", "final_round", "offer", "accepted", "recruiter_screen"].includes(o.stage) ? "bg-ok" : o.stage === "rejected" ? "bg-bad" : "bg-ink-3")} />
              <span className="font-medium text-ink">{STAGE_LABEL[o.stage]}</span>
              <span className="text-ink-3">· {o.source === "adapter" ? "observed by the runner" : o.source === "system" ? "Lintel" : "you"} · <Ago iso={o.occurred_at} /></span>
              {o.note && <span className="truncate text-ink-2">· {o.note}</span>}
            </li>
          ))}
        </ol>
        {s !== "submission_uncertain" && <StageForm d={d} />}
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-6">
          <SectionTitle hint="Short, grounded, and sent by you.">Follow-up</SectionTitle>
          <FollowUps d={d} />
        </Card>
        <Card className="p-6">
          <SectionTitle hint="People you listed at this company, best first.">Referral</SectionTitle>
          <Referrals d={d} />
        </Card>
      </div>

      <Card className="p-6">
        <SectionTitle hint="Text, not pictures: the matched confirmation text, the reference number and a page hash.">Evidence</SectionTitle>
        <Evidence d={d} />
      </Card>
      <p className="text-center text-[12.5px] text-ink-3">No feature here promises an interview. <Link href="/outcomes" className="text-accent hover:underline">See what&apos;s working for you</Link>.</p>
    </div>
  );
}
