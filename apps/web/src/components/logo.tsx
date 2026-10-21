import { cx } from "./ui";

// The lintel: a beam over two posts. It carries the load so a person can walk through.
export function LintelMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cx("size-7", className)} aria-hidden>
      <rect x="3" y="7" width="26" height="5.5" rx="1.6" fill="currentColor" />
      <rect x="6.5" y="12.5" width="4.5" height="14" rx="1.2" fill="currentColor" opacity="0.55" />
      <rect x="21" y="12.5" width="4.5" height="14" rx="1.2" fill="currentColor" opacity="0.55" />
      <rect x="11" y="18" width="10" height="8.5" rx="1" fill="var(--accent)" opacity="0.9" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-2 text-ink", className)}>
      <LintelMark />
      <span className="font-display text-[22px] leading-none tracking-[-0.02em]">Lintel</span>
    </span>
  );
}
