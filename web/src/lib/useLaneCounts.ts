import { useQuery } from "@tanstack/react-query";

import { listCasesOptions } from "../api/@tanstack/react-query.gen";
import type { Lane } from "../api/types.gen";
import { laneTotals } from "../components/queue/search";
import { useMe } from "./useMe";

export interface LaneCounts {
  entries: { lane: Lane; count: number }[];
  total: number;
}

/**
 * Lane counts for the rail. They come from `counts_by_lane` on the same list endpoint the queue
 * reads (one row requested, nothing else used), so no endpoint is added. The query key starts
 * with `listCases`, so every refresh of the queue refreshes these counts too. Nothing is asked
 * until the API has said who the caller is (an anonymous live visitor gets no counts).
 */
export function useLaneCounts(): LaneCounts | null {
  const { me } = useMe();
  const query = useQuery({
    ...listCasesOptions({ query: { limit: 1 } }),
    enabled: me !== undefined,
    staleTime: 30_000,
    retry: false,
  });
  if (!query.data) return null;
  return laneTotals(query.data.counts_by_lane);
}
