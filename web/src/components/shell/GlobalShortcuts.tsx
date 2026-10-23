import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo } from "react";

import { createSequenceMatcher, isTypingTarget } from "../../lib/hotkeys";

const BINDINGS: Record<string, string> = {
  "?": "help",
  "g q": "queue",
  "g h": "history",
  "g c": "config",
};

/** Global keys: `?` opens the sheet; `g` then `q`, `h` or `c` navigates. Quiet while typing. */
export function GlobalShortcuts({ onHelp }: { onHelp: () => void }) {
  const navigate = useNavigate();
  const matcher = useMemo(() => createSequenceMatcher(BINDINGS), []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      const action = matcher.press(event.key, event.timeStamp);
      if (action === "help") {
        event.preventDefault();
        onHelp();
      } else if (action === "queue") void navigate({ to: "/queue" });
      else if (action === "history") void navigate({ to: "/history" });
      else if (action === "config") void navigate({ to: "/config" });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [matcher, navigate, onHelp]);

  return null;
}
