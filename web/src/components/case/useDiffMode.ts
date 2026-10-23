import { useCallback, useState } from "react";

import type { DiffMode } from "./TagDiffTable";

const KEY = "cso.diffMode";

/** Side-by-side or unified tag diff, remembered in this browser. Storage failures are ignored. */
export function useDiffMode(): [DiffMode, (mode: DiffMode) => void] {
  const [mode, setMode] = useState<DiffMode>(() => {
    try {
      return window.localStorage.getItem(KEY) === "unified" ? "unified" : "side";
    } catch {
      return "side";
    }
  });
  const update = useCallback((next: DiffMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Private windows and blocked storage: the choice just lasts until the page closes.
    }
  }, []);
  return [mode, update];
}
