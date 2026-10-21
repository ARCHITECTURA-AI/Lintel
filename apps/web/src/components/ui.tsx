"use client";

import clsx from "clsx";
import { Check, Copy, Loader2 } from "lucide-react";
import Link from "next/link";
import { cloneElement, forwardRef, isValidElement, useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

export const cx = clsx;

type Variant = "primary" | "gate" | "secondary" | "ghost" | "danger" | "ok";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-bg hover:opacity-90 shadow-sm",
  gate: "bg-accent text-white hover:brightness-110 shadow-sm dark:text-[#0d1630]",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-muted",
  ghost: "text-ink-2 hover:bg-muted hover:text-ink",
  danger: "bg-surface text-bad border border-bad-line hover:bg-bad-soft",
  ok: "bg-ok text-white hover:brightness-110 shadow-sm dark:text-[#06180e]",
};
const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-lg",
  md: "h-9 px-3.5 text-[13.5px] gap-2 rounded-[10px]",
  lg: "h-11 px-5 text-[14.5px] gap-2 rounded-xl",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex select-none items-center justify-center whitespace-nowrap font-medium transition-[background,opacity,filter,box-shadow] disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function ButtonLink({ href, variant = "secondary", size = "md", className, children, icon }: { href: string; variant?: Variant; size?: Size; className?: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center whitespace-nowrap font-medium transition", VARIANTS[variant], SIZES[size], className)}>
      {icon}
      {children}
    </Link>
  );
}

export function Card({ className, children, id }: { className?: string; children: ReactNode; id?: string }) {
  return (
    <section id={id} className={cx("card", className)}>
      {children}
    </section>
  );
}

export function CardHeader({ title, eyebrow, actions, description, className }: { title: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; description?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-3 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h2 className="text-[15.5px] font-semibold tracking-[-0.005em] text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-[13.5px] text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "gate" | "ok" | "warn" | "bad" | "muted" | "progress" | "accent";
const TONES: Record<Tone, string> = {
  neutral: "bg-muted text-ink-2 border-line",
  muted: "bg-transparent text-ink-3 border-line",
  gate: "bg-accent-soft text-accent-ink border-accent-line",
  accent: "bg-accent-soft text-accent-ink border-accent-line",
  ok: "bg-ok-soft text-ok border-ok-line",
  warn: "bg-warn-soft text-warn border-warn-line",
  bad: "bg-bad-soft text-bad border-bad-line",
  progress: "bg-surface-2 text-ink-2 border-line-strong",
};

export function Badge({ tone = "neutral", children, className, dot, title }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-[12px] font-medium leading-none", TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current opacity-80" aria-hidden />}
      {children}
    </span>
  );
}

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] font-medium text-ink">
      {children}
      {hint && <span className="ml-1.5 font-normal text-ink-3">{hint}</span>}
    </label>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx("field-input h-9", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx("field-input min-h-[96px] resize-y leading-relaxed", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cx("field-input h-9 appearance-none bg-[length:16px] bg-[right_10px_center] bg-no-repeat pr-8", className)}
      style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2385817a' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}
      {...rest}>
      {children}
    </select>
  );
});

export function Field({ label, hint, children, error, htmlFor }: { label: ReactNode; hint?: ReactNode; children: ReactNode; error?: string | null; htmlFor?: string }) {
  // Link the label to its control: use the control's id, or give it one.
  const generated = useId();
  const child = isValidElement<{ id?: string }>(children) ? children : null;
  const id = htmlFor ?? child?.props.id ?? generated;
  return (
    <div>
      <Label htmlFor={child || htmlFor ? id : undefined} hint={hint}>{label}</Label>
      {child && !htmlFor && !child.props.id ? cloneElement(child, { id }) : children}
      {error && <p className="mt-1 text-[12.5px] text-bad">{error}</p>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-ink-3", className)} aria-label="Loading" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("shimmer rounded-lg", className)} aria-hidden />;
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-3 grid size-11 place-items-center rounded-2xl border border-line bg-surface-2 text-ink-3">{icon}</div>}
      <div className="font-display text-[19px] text-ink">{title}</div>
      {children && <div className="mt-1.5 max-w-md text-[13.5px] text-ink-2">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Meter({ value, max, tone = "ink", className, label }: { value: number; max: number; tone?: "ink" | "accent" | "ok" | "warn"; className?: string; label?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const color = { ink: "bg-ink", accent: "bg-accent", ok: "bg-ok", warn: "bg-warn" }[tone];
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)} role="meter" aria-valuenow={value} aria-valuemax={max} aria-label={label}>
      <div className={cx("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Hash({ value, n = 10, label }: { value: string | null | undefined; n?: number; label?: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-ink-3">—</span>;
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
      title={`${label ?? "SHA-256"}: ${value} (click to copy)`}
      className="group inline-flex items-center gap-1 rounded-md border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[11.5px] text-ink-2 hover:border-line-strong"
    >
      {value.slice(0, n)}
      {copied ? <Check className="size-3 text-ok" /> : <Copy className="size-3 opacity-0 transition group-hover:opacity-60" />}
    </button>
  );
}

export function CopyButton({ text, label = "Copy", size = "sm" }: { text: string; label?: string; size?: Size }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size={size}
      variant="secondary"
      icon={copied ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
      onClick={() => {
        navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{children}</kbd>;
}

export function PageHeader({ title, eyebrow, description, actions }: { title: ReactNode; eyebrow?: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h1 className="font-display text-[30px] leading-[1.1] text-ink sm:text-[34px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-[14.5px] text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cx("min-w-0", className)}>
      <div className="text-[12.5px] text-ink-3">{label}</div>
      <div className="mt-0.5 font-display text-[28px] leading-tight text-ink tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-[12.5px] text-ink-2">{sub}</div>}
    </div>
  );
}

export function Callout({ tone = "neutral", icon, title, children, className, actions }: { tone?: "neutral" | "gate" | "ok" | "warn" | "bad"; icon?: ReactNode; title?: ReactNode; children?: ReactNode; className?: string; actions?: ReactNode }) {
  const t = {
    neutral: "bg-surface-2 border-line text-ink-2",
    gate: "bg-accent-soft border-accent-line text-ink",
    ok: "bg-ok-soft border-ok-line text-ink",
    warn: "bg-warn-soft border-warn-line text-ink",
    bad: "bg-bad-soft border-bad-line text-ink",
  }[tone];
  const ic = { neutral: "text-ink-3", gate: "text-accent", ok: "text-ok", warn: "text-warn", bad: "text-bad" }[tone];
  return (
    <div className={cx("flex gap-3 rounded-xl border px-4 py-3", t, className)}>
      {icon && <div className={cx("mt-0.5 shrink-0", ic)}>{icon}</div>}
      <div className="min-w-0 flex-1 text-[13.5px]">
        {title && <div className="font-semibold text-ink">{title}</div>}
        {children && <div className={cx(title && "mt-0.5", "text-ink-2")}>{children}</div>}
        {actions && <div className="mt-2.5 flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx("relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full border transition disabled:opacity-50",
        checked ? "border-accent bg-accent" : "border-line-strong bg-muted")}
    >
      <span className={cx("inline-block size-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-[2px]")} />
    </button>
  );
}
