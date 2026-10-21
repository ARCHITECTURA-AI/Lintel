import type { ReactNode } from "react";
import { Wordmark } from "@/components/logo";

const GATES = [
  { n: "1", title: "Fit brief", body: "You decide go or skip, with the evidence and the gaps in front of you." },
  { n: "2", title: "Grounding", body: "You confirm every fact a draft depends on. Lintel asks; it never guesses." },
  { n: "3", title: "Review", body: "You approve the exact payload. Then your own click, checked by the Submit Guard." },
];

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden overflow-hidden border-r border-line bg-surface-2 p-12 lg:flex lg:flex-col">
        <Wordmark />
        <div className="mt-auto max-w-lg">
          <p className="eyebrow">Supervised job applications</p>
          <h1 className="font-display mt-3 text-[44px] leading-[1.05] text-ink">The agent prepares.<br />You sign off.</h1>
          <p className="mt-4 text-[15px] leading-relaxed text-ink-2">
            Fewer applications, each one grounded in facts you confirmed and approved before it leaves. Every sentence traces to your ledger.
          </p>
          <ol className="mt-10 space-y-3">
            {GATES.map((g) => (
              <li key={g.n} className="flex gap-4 rounded-2xl border border-accent-line bg-surface p-4">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent text-[13px] font-semibold text-white dark:text-[#0d1630]">{g.n}</span>
                <div>
                  <div className="text-[14px] font-semibold text-ink">Gate {g.n}: {g.title}</div>
                  <div className="text-[13.5px] text-ink-2">{g.body}</div>
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-10 text-[12.5px] text-ink-3">Zero claims in a sent application that you didn&apos;t confirm as true.</p>
        </div>
      </aside>
      <main className="flex min-h-dvh flex-col px-6 py-10 sm:px-12">
        <div className="lg:hidden"><Wordmark /></div>
        <div className="m-auto w-full max-w-[400px] py-10">{children}</div>
      </main>
    </div>
  );
}
