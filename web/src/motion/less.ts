/**
 * The "Less motion" switch. It does the same as the operating system setting for people who have
 * not changed that setting: no scroll animation, no pinned story, every element at its end state.
 * The choice is kept in localStorage; every read and write is guarded, so a private window or
 * blocked storage just means the switch is not remembered.
 */
const KEY = "cso.lessMotion";
export const LESS_MOTION_EVENT = "cso:less-motion";

export function readLessMotion(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function systemPrefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Mirrors the choice on <html> so CSS can switch its own animations off too. */
export function applyLessMotion(on: boolean): void {
  if (on) document.documentElement.dataset.lessMotion = "true";
  else delete document.documentElement.dataset.lessMotion;
}

export function setLessMotion(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(KEY, "1");
    else window.localStorage.removeItem(KEY);
  } catch {
    // not remembered; the page still changes for this visit
  }
  applyLessMotion(on);
  window.dispatchEvent(new Event(LESS_MOTION_EVENT));
}

/** Call once when the page is live so the stored choice takes effect before anything animates. */
export function restoreLessMotion(): boolean {
  const on = readLessMotion();
  applyLessMotion(on);
  return on;
}
