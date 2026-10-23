/** True when a key press came from somewhere the user is typing; shortcuts stay quiet there. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export interface SequenceMatcher {
  /** Feed one key; returns the action id when a sequence completes, else null. */
  press(key: string, now: number): string | null;
}

/**
 * Match one-key shortcuts and `g` + key sequences (for example `g h`).
 * `bindings` maps "?" or "g h" to an action id. A pending `g` expires after `timeoutMs`.
 */
export function createSequenceMatcher(
  bindings: Record<string, string>,
  timeoutMs = 1000,
): SequenceMatcher {
  let pending: { key: string; at: number } | null = null;
  const prefixes = new Set(
    Object.keys(bindings)
      .filter((sequence) => sequence.includes(" "))
      .map((sequence) => sequence.split(" ")[0] as string),
  );
  return {
    press(key, now) {
      if (pending && now - pending.at <= timeoutMs) {
        const action = bindings[`${pending.key} ${key}`];
        pending = null;
        if (action) return action;
      } else {
        pending = null;
      }
      if (prefixes.has(key)) {
        pending = { key, at: now };
        return null;
      }
      return bindings[key] ?? null;
    },
  };
}
