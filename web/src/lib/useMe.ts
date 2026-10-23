import { useQuery } from "@tanstack/react-query";

import { meEndpointOptions } from "../api/@tanstack/react-query.gen";

/**
 * Who the caller is and which mode the server runs in.
 * In live mode an anonymous caller gets 401: `me` is then undefined and the shell offers sign in.
 */
export function useMe() {
  const query = useQuery({ ...meEndpointOptions(), retry: false, staleTime: 30_000 });
  return {
    me: query.data,
    isPending: query.isPending,
    isError: query.isError,
  };
}
