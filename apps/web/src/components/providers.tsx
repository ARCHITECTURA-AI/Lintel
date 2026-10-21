"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5_000, refetchOnWindowFocus: true, retry: (n, e) => n < 2 && !(e as { status?: number })?.status },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider delayDuration={200}>{children}</Tooltip.Provider>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: { background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--border)", borderRadius: 12, boxShadow: "var(--shadow-lg)", fontSize: 13.5 },
        }}
      />
    </QueryClientProvider>
  );
}
