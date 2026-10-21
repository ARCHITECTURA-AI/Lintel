"use client";

import { Laptop } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction, useDevices } from "@/lib/queries";
import { Button, CopyButton, Input } from "./ui";

export function PairInstructions({ initialCode = "" }: { initialCode?: string }) {
  const [code, setCode] = useState(initialCode);
  const { data: devices } = useDevices();
  const apiUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "http://localhost:8000";
  const pair = useAction(() => api.post<{ device_name: string }>("/devices/pair", { user_code: code }), {
    invalidate: [["devices"]],
    success: (r) => `Paired “${(r as { device_name: string }).device_name}”.`,
    onSuccess: () => setCode(""),
  });
  const cmds = [`uv tool install ./apps/runner   # or: pipx install lintel-runner`, `lintel pair --api ${apiUrl}`, `lintel start`];
  return (
    <div className="space-y-4">
      <ol className="space-y-3 text-[13.5px] text-ink-2">
        <li><span className="font-medium text-ink">1. Install and pair on your machine.</span> The runner opens its own visible browser profile; your logins and cookies stay on your computer.</li>
      </ol>
      <div className="relative rounded-xl bg-ink p-4 font-mono text-[12.5px] leading-relaxed text-bg">
        {cmds.map((c) => <div key={c}><span className="select-none opacity-50">$ </span>{c}</div>)}
        <div className="absolute right-2 top-2"><CopyButton text={cmds.join("\n")} /></div>
      </div>
      <div className="text-[13.5px] text-ink-2"><span className="font-medium text-ink">2. Enter the code it shows.</span></div>
      <div className="flex gap-2">
        <Input className="max-w-48 font-mono uppercase tracking-widest" placeholder="ABCD-EFGH" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <Button variant="gate" disabled={code.replace("-", "").length < 8} loading={pair.isPending} onClick={() => pair.mutate()}>Pair this runner</Button>
      </div>
      {devices && devices.filter((d) => !d.revoked_at).length > 0 && (
        <ul className="space-y-1.5">
          {devices.filter((d) => !d.revoked_at).map((d) => (
            <li key={d.id} className="flex items-center gap-2 text-[13px] text-ink">
              <Laptop className="size-4 text-ink-3" /> {d.name}
              <span className={d.online ? "text-ok" : "text-ink-3"}>· {d.online ? "online" : "offline"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
