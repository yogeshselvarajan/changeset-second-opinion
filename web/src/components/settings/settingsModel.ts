import type { Problem, WorkspaceSettings, WorkspaceUpdate } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";

/** Limits the server enforces (`cso.domain.workspace`); the form shows them before a save. */
export const NAME_MAX = 48;
export const TAGLINE_MAX = 120;
export const PARAGRAPH_MAX = 400;
export const LOGO_MAX_BYTES = 32 * 1024;
export const LABEL_MAX = 80;

/** `If-Match` value for a settings version: `W/"<version>"`. */
export function settingsIfMatch(version: number): string {
  return `W/"${Math.max(0, Math.trunc(version))}"`;
}

export type SettingsEdit = Pick<
  WorkspaceSettings,
  "name" | "tagline" | "accent_hex" | "community_paragraph" | "logo_svg" | "osm_signin_enabled"
>;

/** The body of a save: the server's current values with `patch` laid over them. */
export function buildUpdate(
  current: SettingsEdit,
  patch: Partial<SettingsEdit> = {},
): WorkspaceUpdate {
  const merged = { ...current, ...patch };
  return {
    name: merged.name,
    tagline: merged.tagline,
    accent_hex: merged.accent_hex,
    community_paragraph: merged.community_paragraph,
    logo_svg: merged.logo_svg ?? null,
    osm_signin_enabled: merged.osm_signin_enabled,
  };
}

export function isDirty(current: SettingsEdit, draft: SettingsEdit): boolean {
  return (
    current.name !== draft.name ||
    current.tagline !== draft.tagline ||
    current.accent_hex.toUpperCase() !== draft.accent_hex.toUpperCase() ||
    current.community_paragraph !== draft.community_paragraph ||
    (current.logo_svg ?? null) !== (draft.logo_svg ?? null)
  );
}

export type SaveOutcome =
  | { kind: "conflict" }
  | { kind: "invalid"; fields: Record<string, string[]> }
  | { kind: "other"; status: number | null };

function problemOf(error: unknown): Partial<Problem> & { status?: number } {
  return typeof error === "object" && error !== null ? (error as Partial<Problem>) : {};
}

/** Sort a failed save into the three cases the form handles itself. */
export function classifySave(error: unknown): SaveOutcome {
  const problem = problemOf(error);
  if (problem.status === 412) return { kind: "conflict" };
  if (problem.status === 422 && Array.isArray(problem.errors)) {
    const fields: Record<string, string[]> = {};
    for (const item of problem.errors) {
      const field = String(item.loc[item.loc.length - 1] ?? "");
      (fields[field] ??= []).push(item.msg);
    }
    return { kind: "invalid", fields };
  }
  return { kind: "other", status: typeof problem.status === "number" ? problem.status : null };
}

/** The label for a field name the server reported, for the summary above the form. */
export function fieldLabel(field: string): string {
  const key = `settings.field.${field}` as MessageKey;
  const label = t(key);
  return label === key ? field : label;
}

export type LogoRead =
  { ok: true; svg: string } | { ok: false; reason: "notSvg" | "tooBig" | "unreadable" };

/** Read a chosen file as logo text; the server still parses and cleans it. */
export async function readLogoFile(file: File): Promise<LogoRead> {
  if (!file.name.toLowerCase().endsWith(".svg")) return { ok: false, reason: "notSvg" };
  if (file.size > LOGO_MAX_BYTES) return { ok: false, reason: "tooBig" };
  try {
    return { ok: true, svg: await file.text() };
  } catch {
    return { ok: false, reason: "unreadable" };
  }
}

/** An SVG as an `img` source: shown through `img`, nothing inside it can run. */
export function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** The text of the exported file: the editable settings and the version, never a secret. */
export function exportJson(settings: WorkspaceSettings): string {
  return `${JSON.stringify(
    {
      name: settings.name,
      tagline: settings.tagline,
      accent_hex: settings.accent_hex,
      accent_dark_hex: settings.accent_dark_hex,
      community_paragraph: settings.community_paragraph,
      logo_svg: settings.logo_svg ?? null,
      osm_signin_enabled: settings.osm_signin_enabled,
      active_pack: settings.active_pack ?? null,
      calibration_version: settings.calibration_version ?? null,
      version: settings.version,
      updated_at: settings.updated_at,
    },
    null,
    2,
  )}\n`;
}

/** What an invite's use count reads like in the table. */
export function usesLabel(used: number, max: number | null | undefined): string {
  return max == null
    ? t("settings.access.usesOpen", { used })
    : t("settings.access.uses", { used, max });
}
