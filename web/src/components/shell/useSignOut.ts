import { useMutation, useQueryClient } from "@tanstack/react-query";

import { logoutEndpointMutation, meEndpointQueryKey } from "../../api/@tanstack/react-query.gen";
import { t } from "../../i18n";
import { useAnnounce } from "./Announcer";

/** Sign out, refresh who the caller is, and tell screen reader users. Used by the strip and the palette. */
export function useSignOut(): () => void {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const logout = useMutation({
    ...logoutEndpointMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: meEndpointQueryKey() });
      announce(t("login.loggedOut"));
    },
  });
  return () => logout.mutate({});
}
