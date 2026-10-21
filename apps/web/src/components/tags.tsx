"use client";

import { X } from "lucide-react";
import { useState } from "react";

export function TagInput({ value, onChange, placeholder, suggestions }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; suggestions?: string[] }) {
  const [draft, setDraft] = useState("");
  const add = (t: string) => {
    const v = t.trim();
    if (v && !value.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...value, v]);
    setDraft("");
  };
  return (
    <div>
      <div className="field-input flex min-h-9 flex-wrap items-center gap-1.5 py-1.5">
        {value.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[12.5px] text-ink">
            {t}
            <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))} className="text-ink-3 hover:text-ink"><X className="size-3" /></button>
          </span>
        ))}
        <input
          className="min-w-24 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-ink-3"
          value={draft}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); }
            if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
          }}
          onBlur={() => draft && add(draft)}
        />
      </div>
      {suggestions && suggestions.filter((s) => !value.includes(s)).length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {suggestions.filter((s) => !value.includes(s)).map((s) => (
            <button key={s} type="button" onClick={() => add(s)} className="rounded-md border border-dashed border-line-strong px-2 py-0.5 text-[12px] text-ink-3 hover:border-ink-3 hover:text-ink">+ {s}</button>
          ))}
        </div>
      )}
    </div>
  );
}
