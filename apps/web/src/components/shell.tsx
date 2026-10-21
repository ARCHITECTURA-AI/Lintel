"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import {
  Bell,
  BookUser,
  Building2,
  ChartNoAxesColumn,
  Compass,
  Inbox,
  Laptop,
  LayoutGrid,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  ScrollText,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { initials } from "@/lib/format";
import { useDashboard, useMe, useNotifications } from "@/lib/queries";
import { Wordmark } from "./logo";
import { cx } from "./ui";

type NavItem = { href: string; label: string; icon: ReactNode; badge?: number };

function useNav(): { section: string; items: NavItem[] }[] {
  const { data: dash } = useDashboard();
  const { data: notes } = useNotifications();
  const needsYou = dash?.tasks.length ?? 0;
  const queue = dash?.counts?.fit_review ?? 0;
  return [
    {
      section: "Work",
      items: [
        { href: "/", label: "Today", icon: <LayoutGrid className="size-4" />, badge: needsYou || undefined },
        { href: "/queue", label: "Fit queue", icon: <ListChecks className="size-4" />, badge: queue || undefined },
        { href: "/applications", label: "Applications", icon: <ScrollText className="size-4" /> },
      ],
    },
    {
      section: "Discover",
      items: [
        { href: "/watchlist", label: "Watchlist", icon: <Building2 className="size-4" /> },
        { href: "/jobs", label: "Jobs", icon: <Compass className="size-4" /> },
      ],
    },
    {
      section: "You",
      items: [
        { href: "/ledger", label: "Fact ledger", icon: <BookUser className="size-4" /> },
        { href: "/outcomes", label: "Outcomes", icon: <ChartNoAxesColumn className="size-4" /> },
        { href: "/contacts", label: "Contacts", icon: <Users className="size-4" /> },
      ],
    },
    {
      section: "System",
      items: [
        { href: "/inbox", label: "Inbox", icon: <Inbox className="size-4" />, badge: notes?.unread || undefined },
        { href: "/devices", label: "Local Runner", icon: <Laptop className="size-4" /> },
        { href: "/registry", label: "Destinations", icon: <ShieldCheck className="size-4" /> },
        { href: "/settings", label: "Settings", icon: <Settings className="size-4" /> },
      ],
    },
  ];
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const nav = useNav();
  return (
    <nav className="space-y-5" aria-label="Main">
      {nav.map((group) => (
        <div key={group.section}>
          <div className="eyebrow mb-1.5 px-3">{group.section}</div>
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "flex h-9 items-center gap-2.5 rounded-[10px] px-3 text-[13.5px] transition",
                      active ? "bg-surface font-medium text-ink shadow-[var(--shadow)] ring-1 ring-line" : "text-ink-2 hover:bg-muted hover:text-ink",
                    )}
                  >
                    <span className={active ? "text-ink" : "text-ink-3"}>{item.icon}</span>
                    <span className="flex-1">{item.label}</span>
                    {item.badge ? (
                      <span className="min-w-5 rounded-full bg-accent px-1.5 text-center text-[11px] font-semibold leading-5 text-white dark:text-[#0d1630]">
                        {item.badge > 99 ? "99+" : item.badge}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function RunnerStatus() {
  const { data } = useDashboard();
  const r = data?.runner;
  const state = !r ? "loading" : !r.paired ? "unpaired" : r.online ? "online" : "offline";
  const label = { loading: "Checking runner…", unpaired: "Runner not paired", online: "Runner online", offline: "Runner offline" }[state];
  const dot = { loading: "bg-ink-3", unpaired: "bg-warn", online: "bg-ok", offline: "bg-ink-3" }[state];
  return (
    <Link href="/devices" className="flex items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2.5 text-[12.5px] hover:border-line-strong">
      <span className="relative flex size-2.5">
        {state === "online" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok opacity-40" />}
        <span className={cx("relative inline-flex size-2.5 rounded-full", dot)} />
      </span>
      <span className="flex-1 text-ink-2">{label}</span>
      <Laptop className="size-3.5 text-ink-3" />
    </Link>
  );
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const mq = window.matchMedia(DARK_QUERY);
  mq.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    mq.removeEventListener("change", onChange);
  };
}

function currentTheme(): "light" | "dark" {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => null);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      aria-label={`Switch to ${next} theme`}
      className="grid size-9 place-items-center rounded-[10px] text-ink-2 hover:bg-muted hover:text-ink"
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("lintel-theme", next);
        } catch {}
      }}
    >
      {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function UserMenu() {
  const { data: me } = useMe();
  const router = useRouter();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button type="button" aria-label="Account" className="grid size-9 place-items-center rounded-full bg-ink text-[12px] font-semibold text-bg">
          {initials(me?.full_name || me?.email || "?")}
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={8} className="z-50 min-w-56 rounded-xl border border-line bg-surface p-1.5 shadow-[var(--shadow-lg)]">
          <div className="px-2.5 py-2">
            <div className="text-[13.5px] font-medium text-ink">{me?.full_name || "You"}</div>
            <div className="text-[12.5px] text-ink-3">{me?.email}</div>
          </div>
          <Dropdown.Separator className="my-1 h-px bg-line" />
          <Dropdown.Item asChild>
            <Link href="/settings" className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] text-ink-2 outline-none data-[highlighted]:bg-muted data-[highlighted]:text-ink">
              <Settings className="size-4" /> Settings
            </Link>
          </Dropdown.Item>
          <Dropdown.Item asChild>
            <Link href="/trust" className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] text-ink-2 outline-none data-[highlighted]:bg-muted data-[highlighted]:text-ink">
              <ShieldCheck className="size-4" /> Trust Report
            </Link>
          </Dropdown.Item>
          <Dropdown.Item
            onSelect={async () => {
              await api.post("/auth/logout").catch(() => null);
              router.push("/login");
            }}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13.5px] text-ink-2 outline-none data-[highlighted]:bg-muted data-[highlighted]:text-ink"
          >
            <LogOut className="size-4" /> Sign out
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function Bellink() {
  const { data } = useNotifications();
  return (
    <Link href="/inbox" aria-label={`Inbox${data?.unread ? `, ${data.unread} unread` : ""}`} className="relative grid size-9 place-items-center rounded-[10px] text-ink-2 hover:bg-muted hover:text-ink">
      <Bell className="size-4" />
      {data?.unread ? <span className="absolute right-2 top-2 size-2 rounded-full bg-accent ring-2 ring-bg" /> : null}
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === pathname;
  const setOpen = (v: boolean) => setOpenOn(v ? pathname : null);
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[256px_1fr]">
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-line bg-surface-2/60 px-3 py-5 lg:flex">
        <Link href="/" className="px-3">
          <Wordmark />
        </Link>
        <div className="flex-1 overflow-y-auto">
          <NavLinks />
        </div>
        <RunnerStatus />
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-bg/85 px-4 backdrop-blur lg:px-8">
          <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Trigger asChild>
              <button type="button" aria-label="Open menu" className="grid size-9 place-items-center rounded-[10px] text-ink-2 hover:bg-muted lg:hidden">
                <Menu className="size-5" />
              </button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px]" />
              <Dialog.Content className="fixed inset-y-0 left-0 z-50 flex w-[280px] flex-col gap-6 overflow-y-auto bg-bg px-3 py-5 shadow-[var(--shadow-lg)]">
                <Dialog.Title className="sr-only">Menu</Dialog.Title>
                <div className="flex items-center justify-between px-3">
                  <Wordmark />
                  <Dialog.Close aria-label="Close menu" className="grid size-8 place-items-center rounded-lg hover:bg-muted">
                    <X className="size-4" />
                  </Dialog.Close>
                </div>
                <NavLinks onNavigate={() => setOpen(false)} />
                <RunnerStatus />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <Link href="/" className="lg:hidden">
            <Wordmark className="scale-90" />
          </Link>
          <div className="flex-1" />
          <span className="hidden text-[12.5px] text-ink-3 md:inline">The agent prepares, you sign off.</span>
          <ThemeToggle />
          <Bellink />
          <UserMenu />
        </header>
        <main className="mx-auto w-full max-w-[1240px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
