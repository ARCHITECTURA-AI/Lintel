"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "./api";
import type {
  AppSummary,
  ApplicationDetail,
  Budget,
  Candidate,
  ContactRow,
  Dashboard,
  Destination,
  DeviceRow,
  DocumentRow,
  FactRow,
  FollowUpRow,
  JobRow,
  Me,
  NotificationRow,
  TaskRow,
  TrustMetrics,
  WatchCompany,
  WeeklyReview,
} from "./types";

const LIVE_STATES = new Set(["imported", "grounding", "filling", "approved", "submitting"]);

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), staleTime: 60_000 });
export const useDashboard = () =>
  useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard"), refetchInterval: 10_000 });
export const useApplications = (state?: string) =>
  useQuery({ queryKey: ["applications", state ?? "all"], queryFn: () => api.get<AppSummary[]>(`/applications${state ? `?state=${state}` : ""}`) });
export const useQueue = () =>
  useQuery({
    queryKey: ["queue"],
    queryFn: () => api.get<{ budget: Budget; items: AppSummary[] }>("/applications/queue"),
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.state === "imported") ? 2_000 : 15_000),
  });
export const useApplication = (id: string) =>
  useQuery({
    queryKey: ["application", id],
    queryFn: () => api.get<ApplicationDetail>(`/applications/${id}`),
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return false;
      const live = LIVE_STATES.has(d.application.state) || d.runs.some((r) => ["queued", "running", "waiting_user"].includes(r.state));
      return live ? 1_500 : 15_000;
    },
  });
export const useTasks = () => useQuery({ queryKey: ["tasks"], queryFn: () => api.get<TaskRow[]>("/tasks"), refetchInterval: 15_000 });
export const useNotifications = () =>
  useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<{ items: NotificationRow[]; unread: number }>("/notifications"),
    refetchInterval: 15_000,
  });
export const useDevices = () =>
  useQuery({ queryKey: ["devices"], queryFn: () => api.get<DeviceRow[]>("/devices"), refetchInterval: 5_000 });
export const useWatchlist = () =>
  useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchCompany[]>("/watchlist"), refetchInterval: 20_000 });
export const useJobs = (params: string) => useQuery({ queryKey: ["jobs", params], queryFn: () => api.get<JobRow[]>(`/jobs?${params}`) });
export const useFacts = (history = false) =>
  useQuery({ queryKey: ["facts", history], queryFn: () => api.get<FactRow[]>(`/facts${history ? "?include_history=true" : ""}`) });
export const useCandidates = () => useQuery({ queryKey: ["candidates"], queryFn: () => api.get<Candidate[]>("/fact-candidates") });
export const useDocuments = () => useQuery({ queryKey: ["documents"], queryFn: () => api.get<DocumentRow[]>("/documents") });
export const useReview = (weeks = 12) =>
  useQuery({ queryKey: ["review", weeks], queryFn: () => api.get<WeeklyReview>(`/outcomes/review?weeks=${weeks}`) });
export const useMetrics = () => useQuery({ queryKey: ["metrics"], queryFn: () => api.get<TrustMetrics>("/metrics") });
export const useFollowUps = () => useQuery({ queryKey: ["follow-ups"], queryFn: () => api.get<FollowUpRow[]>("/follow-ups") });
export const useContacts = () => useQuery({ queryKey: ["contacts"], queryFn: () => api.get<ContactRow[]>("/contacts") });
export const useRegistry = () => useQuery({ queryKey: ["registry"], queryFn: () => api.get<Destination[]>("/registry") });

/** A mutation with toasts and cache invalidation, for buttons that change server state. */
export function useAction<TVars = void, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { invalidate?: QueryKey[]; success?: string | ((r: TRes) => string); onSuccess?: (r: TRes) => void; quietError?: boolean } = {},
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (res) => {
      for (const k of opts.invalidate ?? []) qc.invalidateQueries({ queryKey: k });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(res) : opts.success);
      opts.onSuccess?.(res);
    },
    onError: (e) => {
      if (!opts.quietError) toast.error(errorMessage(e));
    },
  });
}
