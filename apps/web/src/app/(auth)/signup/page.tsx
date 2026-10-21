"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <h2 className="font-display text-[32px] leading-tight text-ink">Create your account</h2>
      <p className="mt-1.5 mb-7 text-[14px] text-ink-2">Ten minutes to set up. After that, a reviewed, truthful packet takes minutes.</p>
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api.post("/auth/register", { email, password, full_name: name });
            router.push("/onboarding");
          } catch (err) {
            setError(errorMessage(err));
            setBusy(false);
          }
        }}
      >
        <Field label="Your name" htmlFor="name">
          <Input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password" hint="at least 10 characters">
          <Input id="password" type="password" autoComplete="new-password" minLength={10} required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {error && <p role="alert" className="rounded-lg border border-bad-line bg-bad-soft px-3 py-2 text-[13px] text-bad">{error}</p>}
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Create account</Button>
        <p className="text-[12px] leading-relaxed text-ink-3">
          Lintel stores facts you confirm, drafts, documents and an audit trail. It never stores your passwords or browser logins for other sites; those stay on your machine. Export or delete everything from Settings, any time.
        </p>
      </form>
      <p className="mt-6 text-center text-[13.5px] text-ink-2">
        Already have an account? <Link href="/login" className="font-medium text-accent hover:underline">Sign in</Link>
      </p>
    </>
  );
}
