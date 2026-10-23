import { useEffect, useRef } from "react";

import { isTypingTarget } from "../../lib/hotkeys";

export type CaseKeyHandlers = Partial<Record<string, () => void>>;

/**
 * One-key shortcuts for the case screen (j k n p [ ] t u m d a s x). They stay quiet while typing,
 * with a modifier held, or while a dialog is open. `g q` and `g h` belong to the shell and still work.
 */
export function useCaseKeys(handlers: CaseKeyHandlers): void {
  // Keep the latest handlers without re-attaching the listener on every render.
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      if (isTypingTarget(event.target)) return;
      if (document.querySelector('[role="dialog"], dialog[open]')) return;
      const handler = latest.current[event.key];
      if (!handler) return;
      event.preventDefault();
      handler();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

/**
 * Move focus to the next or previous region marked `data-case-section`, in page order, and say which
 * one it is. Returns the heading text so the caller can announce it.
 */
export function jumpToSection(delta: 1 | -1): string | null {
  const sections = Array.from(document.querySelectorAll<HTMLElement>("[data-case-section]"));
  if (sections.length === 0) return null;
  const active = document.activeElement;
  const current = sections.findIndex((node) => node === active || node.contains(active));
  const target =
    current === -1
      ? delta === 1
        ? 0
        : sections.length - 1
      : Math.min(sections.length - 1, Math.max(0, current + delta));
  const node = sections[target];
  if (!node) return null;
  node.focus();
  node.scrollIntoView({ block: "start", behavior: "auto" });
  const headingId = node.getAttribute("aria-labelledby");
  const heading = headingId ? document.getElementById(headingId) : null;
  return heading?.textContent ?? null;
}
