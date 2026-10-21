"use client";

import { Bell, CheckCheck } from "lucide-react";
import Link from "next/link";
import { Ago } from "@/components/domain";
import { Button, Card, CardHeader, EmptyState, PageHeader, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAction, useNotifications, useTasks } from "@/lib/queries";

export default function InboxPage() {
  const { data } = useNotifications();
  const { data: tasks } = useTasks();
  const readAll = useAction(() => api.post("/notifications/read-all"), { invalidate: [["notifications"]] });
  const read = useAction((id: string) => api.post(`/notifications/${id}/read`), { invalidate: [["notifications"]] });
  const dismiss = useAction((id: string) => api.post(`/tasks/${id}/dismiss`), { invalidate: [["tasks"]] });
  return (
    <div className="animate-rise">
      <PageHeader title="Inbox" description="In-app first, then email, then web push. Every link opens here, behind your sign-in."
        actions={<Button variant="secondary" icon={<CheckCheck className="size-4" />} onClick={() => readAll.mutate()}>Mark all read</Button>} />
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_380px]">
        <Card className="overflow-hidden">
          {data?.items.length ? (
            <ul className="divide-y divide-line">
              {data.items.map((n) => (
                <li key={n.id}>
                  <Link href={n.link} onClick={() => !n.read_at && read.mutate(n.id)} className={cx("flex gap-3 px-5 py-3.5 hover:bg-surface-2", !n.read_at && "bg-accent-soft/30")}>
                    <span className={cx("mt-2 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : n.urgent ? "bg-warn" : "bg-accent")} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-medium text-ink">{n.title}</span>
                      <span className="block text-[13px] text-ink-2">{n.body}</span>
                    </span>
                    <span className="shrink-0 text-[12px] text-ink-3"><Ago iso={n.created_at} /></span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <EmptyState icon={<Bell className="size-5" />} title="Nothing yet">Lintel tells you when a gate is waiting, a run is blocked, or a follow-up is ready.</EmptyState>}
        </Card>
        <Card>
          <CardHeader title="Open tasks" description="Questions and requests only you can answer." />
          <ul className="divide-y divide-line border-t border-line">
            {tasks?.map((t) => (
              <li key={t.id} className="flex items-start gap-2 px-5 py-3">
                <Link href={t.application_id ? `/applications/${t.application_id}` : "#"} className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium text-ink">{t.title}</span>
                  <span className="block text-[12px] text-ink-3">{t.job ? `${t.job.title} · ${t.job.company_name}` : t.type}</span>
                </Link>
                <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(t.id)}>Dismiss</Button>
              </li>
            ))}
            {!tasks?.length && <li className="px-5 py-4 text-[13px] text-ink-3">No open tasks.</li>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
