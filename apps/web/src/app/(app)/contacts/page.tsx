"use client";

import { Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useContacts } from "@/lib/queries";

const REL = [["former_colleague", "Former colleague"], ["friend", "Friend"], ["alum", "Alum"], ["acquaintance", "Acquaintance"], ["recruiter", "Recruiter"], ["other", "Other"]];

export default function ContactsPage() {
  const { data } = useContacts();
  const [form, setForm] = useState({ name: "", company: "", relationship: "former_colleague", email: "", notes: "" });
  const add = useAction(() => api.post("/contacts", { ...form, email: form.email || null }), {
    invalidate: [["contacts"], ["tasks"]],
    success: "Added. Lintel will suggest them for roles at that company.",
    onSuccess: () => setForm({ ...form, name: "", email: "", notes: "" }),
  });
  const del = useAction((id: string) => api.del(`/contacts/${id}`), { invalidate: [["contacts"]] });
  const byCompany = new Map<string, NonNullable<typeof data>>();
  for (const c of data ?? []) byCompany.set(c.company, [...(byCompany.get(c.company) ?? []), c]);
  return (
    <div className="animate-rise">
      <PageHeader title="Contacts" description="People you know at companies you're applying to. Entered by you, never scraped. Lintel suggests who to ask for a referral and drafts the note; you send it." />
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
        <Card className="overflow-hidden">
          {byCompany.size ? [...byCompany.entries()].map(([co, people]) => (
            <section key={co} className="border-b border-line last:border-0">
              <div className="bg-surface-2 px-5 py-2 text-[12.5px] font-semibold text-ink-2">{co}</div>
              <ul className="divide-y divide-line">
                {people.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium text-ink">{c.name}</div>
                      <div className="text-[12.5px] text-ink-3">{c.email ?? ""}{c.notes ? ` · ${c.notes}` : ""}</div>
                    </div>
                    <Badge tone="neutral">{REL.find((r) => r[0] === c.relationship)?.[1]}</Badge>
                    <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => del.mutate(c.id)}><Trash2 className="size-3.5" /></Button>
                  </li>
                ))}
              </ul>
            </section>
          )) : <EmptyState icon={<Users className="size-5" />} title="No contacts yet">Follow-ups and referrals are the human levers that autofill doesn&apos;t touch.</EmptyState>}
        </Card>
        <Card className="space-y-3 p-5">
          <div className="text-[14px] font-semibold text-ink">Add someone</div>
          <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Company"><Input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></Field>
          <Field label="How you know them"><Select value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value })}>{REL.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
          <Field label="Email" hint="optional"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Notes" hint="optional"><Textarea className="min-h-[60px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <Button variant="primary" className="w-full" disabled={!form.name || !form.company} loading={add.isPending} onClick={() => add.mutate()}>Add contact</Button>
        </Card>
      </div>
    </div>
  );
}
