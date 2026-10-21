"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AppShell } from "@/components/shell";
import { Spinner } from "@/components/ui";
import { useMe } from "@/lib/queries";

export default function AppLayout({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (me && !me.onboarded && !pathname.startsWith("/onboarding")) router.replace("/onboarding");
  }, [me, pathname, router]);
  if (isLoading || !me) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner className="size-5" />
      </div>
    );
  }
  if (pathname.startsWith("/onboarding")) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
