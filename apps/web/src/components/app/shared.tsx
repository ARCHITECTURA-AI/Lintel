"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import type { ApplicationDetail } from "@/lib/types";
import { cx } from "../ui";

export type Detail = ApplicationDetail;

export function factIndex(d: Detail): Map<string, number> {
  const order = new Map<string, number>();
  const push = (id: string) => {
    if (!order.has(id)) order.set(id, order.size);
  };
  for (const dr of d.drafts) {
    for (const s of dr.sentences ?? []) s.fact_ids.forEach(push);
    (dr.fact_ids ?? []).forEach(push);
  }
  for (const r of d.application.fit_brief?.requirements ?? []) r.evidence_fact_ids.forEach(push);
  for (const p of d.grounding?.plan ?? []) p.fact_ids.forEach(push);
  return order;
}

export function labelFor(d: Detail, fieldKey: string | null | undefined): string {
  if (!fieldKey) return "";
  return d.drafts.find((x) => x.field_key === fieldKey)?.label ?? fieldKey;
}

export function Modal({ open, onOpenChange, title, description, children, wide }: { open: boolean; onOpenChange: (v: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/35 backdrop-blur-[2px]" />
        <Dialog.Content className={cx("fixed left-1/2 top-1/2 z-50 max-h-[88dvh] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border border-line bg-surface p-6 shadow-[var(--shadow-lg)]", wide ? "max-w-3xl" : "max-w-lg")}>
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="font-display text-[22px] leading-tight text-ink">{title}</Dialog.Title>
              {description && <Dialog.Description className="mt-1 text-[13.5px] text-ink-2">{description}</Dialog.Description>}
            </div>
            <Dialog.Close aria-label="Close" className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-3 hover:bg-muted hover:text-ink">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function SectionTitle({ children, hint, gate }: { children: ReactNode; hint?: ReactNode; gate?: string }) {
  return (
    <div className="mb-3 mt-1">
      {gate && <div className="eyebrow mb-1 text-accent">{gate}</div>}
      <h3 className="font-display text-[21px] leading-tight text-ink">{children}</h3>
      {hint && <p className="mt-1 text-[13.5px] text-ink-2">{hint}</p>}
    </div>
  );
}
