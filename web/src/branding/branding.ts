import { useEffect, useSyncExternalStore } from "react";

import type { PublicBranding } from "../api/types.gen";
import { t } from "../i18n";
import { DEFAULT_ACCENT, isHexColour } from "./contrast";

/**
 * The workspace's public branding (name, tagline, accent, logo flag, community paragraph).
 *
 * One small store shared by the app and the public pages, so the public bundle needs no query
 * client. A value is fresh for five minutes; the settings screen replaces it the moment a save
 * succeeds. Until a value arrives, every reader falls back to the built-in wording, which is also
 * what the prerendered pages contain, so hydration never mismatches.
 */

export const BRANDING_URL = "/api/v1/public/branding";
export const LOGO_URL = "/api/v1/public/branding/logo.svg";
export const FRESH_MS = 5 * 60_000;
const STYLE_ID = "cso-branding";

let current: PublicBranding | null = null;
let fetchedAt = 0;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Shape check for what the server sent; anything odd is ignored rather than applied. */
export function isBranding(value: unknown): value is PublicBranding {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.name === "string" &&
    typeof v.tagline === "string" &&
    typeof v.community_paragraph === "string" &&
    typeof v.has_logo === "boolean" &&
    typeof v.osm_signin_enabled === "boolean" &&
    typeof v.accent_hex === "string" &&
    isHexColour(v.accent_hex) &&
    typeof v.accent_dark_hex === "string" &&
    isHexColour(v.accent_dark_hex)
  );
}

/** CSS that sets the accent for both themes, or null when it is the built-in colour. */
export function accentCss(branding: PublicBranding): string | null {
  if (branding.accent_hex.toUpperCase() === DEFAULT_ACCENT) return null;
  const light = branding.accent_hex;
  const dark = branding.accent_dark_hex;
  // Both values passed `isHexColour`, so nothing else can reach the stylesheet.
  const vars = (accent: string, fg: string) =>
    `--color-accent:${accent};--color-focus:${accent};--color-accent-fg:${fg};`;
  return [
    `:root{${vars(light, "#ffffff")}}`,
    `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){${vars(dark, "#0f1012")}}}`,
    `:root[data-theme="dark"]{${vars(dark, "#0f1012")}}`,
  ].join("");
}

function applyAccent(branding: PublicBranding): void {
  if (typeof document === "undefined") return;
  const css = accentCss(branding);
  let style = document.getElementById(STYLE_ID);
  if (css === null) {
    style?.remove();
    return;
  }
  if (!style) {
    style = document.createElement("style");
    style.id = STYLE_ID;
    document.head.appendChild(style);
  }
  style.textContent = css;
}

export function getBranding(): PublicBranding | null {
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Use this value now (after a save, or when the server's answer arrives). */
export function setBranding(next: PublicBranding): void {
  current = next;
  fetchedAt = Date.now();
  applyAccent(next);
  emit();
}

/** Fetch the branding unless a fresh copy is held. Failures leave the built-in wording in place. */
export function loadBranding(force = false): Promise<void> {
  if (!force && current && Date.now() - fetchedAt < FRESH_MS) return Promise.resolve();
  if (typeof fetch === "undefined") return Promise.resolve();
  inflight ??= (async () => {
    try {
      const response = await fetch(BRANDING_URL, {
        credentials: "omit",
        headers: { accept: "application/json" },
      });
      if (!response.ok) return;
      const body: unknown = await response.json();
      if (isBranding(body)) setBranding(body);
    } catch {
      // Offline or no API (the static build): keep the built-in wording.
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** For tests: forget everything held. */
export function resetBranding(): void {
  current = null;
  fetchedAt = 0;
  inflight = null;
  if (typeof document !== "undefined") document.getElementById(STYLE_ID)?.remove();
  emit();
}

/** The workspace's name, or the built-in one until the server has answered. */
export function useBrandName(): string {
  return useBranding()?.name ?? t("app.name");
}

/** The branding the server holds, or null until it has been read (and always null in prerender). */
export function useBranding(): PublicBranding | null {
  const value = useSyncExternalStore(subscribe, getBranding, () => null);
  useEffect(() => {
    void loadBranding();
  }, []);
  return value;
}
