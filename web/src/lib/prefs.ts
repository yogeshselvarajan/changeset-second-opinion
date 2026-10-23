export type Theme = "system" | "light" | "dark";
export type Density = "comfortable" | "compact";

export interface Prefs {
  theme: Theme;
  density: Density;
}

export const THEME_KEY = "cso.theme";
export const DENSITY_KEY = "cso.density";
export const DEFAULT_PREFS: Prefs = { theme: "system", density: "comfortable" };

/** Minimal Storage shape so tests can pass a stub; real code passes `localStorage`. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // blocked storage (private window, site data off)
  }
}

export function readPrefs(storage: StorageLike | null = browserStorage()): Prefs {
  try {
    const theme = storage?.getItem(THEME_KEY);
    const density = storage?.getItem(DENSITY_KEY);
    return {
      theme: theme === "light" || theme === "dark" || theme === "system" ? theme : "system",
      density: density === "compact" || density === "comfortable" ? density : "comfortable",
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function writePrefs(prefs: Prefs, storage: StorageLike | null = browserStorage()): void {
  try {
    storage?.setItem(THEME_KEY, prefs.theme);
    storage?.setItem(DENSITY_KEY, prefs.density);
  } catch {
    // The page works without storage; the choice just does not survive a reload.
  }
}

/** Reflect the preferences on <html>: no data-theme means "follow the system". */
export function applyPrefs(prefs: Prefs, root: HTMLElement = document.documentElement): void {
  if (prefs.theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", prefs.theme);
  root.setAttribute("data-density", prefs.density);
}
