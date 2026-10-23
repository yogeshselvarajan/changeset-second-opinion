import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import {
  getCaseEvidenceOptions,
  getCaseOptions,
  getConfigOptions,
  getJobOptions,
  getRunOptions,
  listCaseRunsOptions,
} from "../../api/@tanstack/react-query.gen";
import type { JobStatus, Option } from "../../api/types.gen";
import { retryTransient } from "./failure";

/** How often to look again while an analysis is running. */
export const POLL_MS = 2000;

const TERMINAL: ReadonlySet<JobStatus> = new Set<JobStatus>(["succeeded", "failed", "cancelled"]);

export function isTerminal(status: JobStatus | undefined): boolean {
  return status !== undefined && TERMINAL.has(status);
}

/** The case, looked at again every two seconds while its status says an analysis is running. */
export function useCaseDetail(id: string) {
  return useQuery({
    ...getCaseOptions({ path: { id } }),
    retry: retryTransient,
    refetchInterval: (query) => (query.state.data?.status === "analyzing" ? POLL_MS : false),
  });
}

/** The evidence snapshot the case currently points at. */
export function useEvidence(id: string, snapshotId: string | null | undefined) {
  return useQuery({
    ...getCaseEvidenceOptions({
      path: { id },
      query: snapshotId ? { snapshot_id: snapshotId } : undefined,
    }),
    enabled: Boolean(snapshotId),
    retry: retryTransient,
  });
}

export function useRuns(id: string) {
  return useQuery({ ...listCaseRunsOptions({ path: { id } }), retry: retryTransient });
}

/** One run with its receipt: the reconciliation note and the timings live there. */
export function useRunDetail(runId: string | null | undefined) {
  return useQuery({
    ...getRunOptions({ path: { id: runId ?? "" } }),
    enabled: Boolean(runId),
    retry: retryTransient,
  });
}

/** The community configuration: option labels and descriptions for the answers. */
export function useConfig() {
  return useQuery({
    ...getConfigOptions(),
    retry: retryTransient,
    staleTime: 5 * 60_000,
  });
}

/** Poll a background job every two seconds until it ends. */
export function useAnalysisJob(jobId: string | null) {
  return useQuery({
    ...getJobOptions({ path: { id: jobId ?? "" } }),
    enabled: Boolean(jobId),
    retry: retryTransient,
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : POLL_MS),
  });
}

const CASE_QUERY_IDS: ReadonlySet<string> = new Set(["getCase", "getCaseEvidence", "listCaseRuns"]);

/** Refetch everything the case screen shows for one case (after an analysis finishes). */
export function invalidateCase(queryClient: QueryClient, caseId: string): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: (query) => {
      const key = query.queryKey[0] as { _id?: string; path?: { id?: string } } | undefined;
      return Boolean(key?._id && CASE_QUERY_IDS.has(key._id) && key.path?.id === caseId);
    },
  });
}

export function useInvalidateCase(caseId: string): () => Promise<void> {
  const queryClient = useQueryClient();
  return () => invalidateCase(queryClient, caseId);
}

export interface OptionInfo {
  label: string;
  description?: string;
}

/** Look up an option's label and description by its code. */
export function optionLookup(options: readonly Option[] | undefined): Map<string, OptionInfo> {
  const lookup = new Map<string, OptionInfo>();
  for (const option of options ?? []) {
    lookup.set(option.code, { label: option.label, description: option.description });
  }
  return lookup;
}
