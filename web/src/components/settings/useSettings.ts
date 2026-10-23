import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  getWorkspaceSettingsOptions,
  getWorkspaceSettingsQueryKey,
  updateWorkspaceSettingsMutation,
} from "../../api/@tanstack/react-query.gen";
import type { PublicBranding, WorkspaceSettings } from "../../api/types.gen";
import { setBranding } from "../../branding/branding";
import { retryTransient } from "../case/failure";
import {
  classifySave,
  buildUpdate,
  settingsIfMatch,
  type SaveOutcome,
  type SettingsEdit,
} from "./settingsModel";

export function useSettings() {
  return useQuery({ ...getWorkspaceSettingsOptions(), retry: retryTransient, staleTime: 0 });
}

/** What visitors see after a save, so the top strip and the home page follow without a reload. */
export function brandingFrom(settings: WorkspaceSettings): PublicBranding {
  return {
    name: settings.name,
    tagline: settings.tagline,
    accent_hex: settings.accent_hex,
    accent_dark_hex: settings.accent_dark_hex,
    community_paragraph: settings.community_paragraph,
    has_logo: Boolean(settings.logo_svg),
    osm_signin_enabled: settings.osm_signin_enabled && settings.osm_signin_configured,
  };
}

export type SaveResult = { ok: true; settings: WorkspaceSettings } | ({ ok: false } & SaveOutcome);

/**
 * Save the settings. The body is the server's current values with `patch` laid over them, and
 * `If-Match` carries the version those values came from, so a save over someone else's change is a
 * 412 instead of a silent overwrite.
 */
export function useSaveSettings(current: WorkspaceSettings) {
  const queryClient = useQueryClient();
  const mutation = useMutation(updateWorkspaceSettingsMutation());

  const save = useCallback(
    async (patch: Partial<SettingsEdit>): Promise<SaveResult> => {
      try {
        const saved = await mutation.mutateAsync({
          body: buildUpdate(current, patch),
          headers: { "if-match": settingsIfMatch(current.version) },
        });
        queryClient.setQueryData(getWorkspaceSettingsQueryKey(), saved);
        setBranding(brandingFrom(saved));
        return { ok: true, settings: saved };
      } catch (error) {
        return { ok: false, ...classifySave(error) };
      }
    },
    [current, mutation, queryClient],
  );

  return { save, isSaving: mutation.isPending };
}
