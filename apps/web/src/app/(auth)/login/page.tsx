"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Me } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const me = await api.post<Me>("/auth/login", { email, password });
          const next = params.get("next");
          router.push(!me.onboarded ? "/onboarding" : next && next.startsWith("/") ? next : "/");
        } catch (err) {
          setError(errorMessage(err));
          setBusy(false);
        }
      }}
    >
      <Field label="Email" htmlFor="email">
        <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field label="Password" htmlFor="password">
        <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      {error && <p role="alert" className="rounded-lg border border-bad-line bg-bad-soft px-3 py-2 text-[13px] text-bad">{error}</p>}
      <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Sign in</Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <>
      <h2 className="font-display text-[32px] leading-tight text-ink">Welcome back</h2>
      <p className="mt-1.5 mb-7 text-[14px] text-ink-2">Sign in to see what&apos;s waiting for you.</p>
      <Suspense>
        <LoginForm />
      </Suspense>
      <p className="mt-6 text-center text-[13.5px] text-ink-2">
        New to Lintel? <Link href="/signup" className="font-medium text-accent hover:underline">Create an account</Link>
      </p>
    </>
  );
}
