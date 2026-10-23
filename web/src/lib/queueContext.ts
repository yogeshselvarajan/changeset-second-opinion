/*
 * The ids of the cases in the list the reviewer is working through, kept for the session so the case
 * screen can offer next and previous. The queue screen saves it when it loads a page; a case opened
 * from a shared link has no context and simply shows no next or previous.
 */

const KEY = "cso.queue.context";

export interface Neighbour {
  id: string;
  /** 1-based position of the case that was asked for. */
  position: number;
  total: number;
}

/** Remember the case ids of the current list, in the order shown. Storage failures are ignored. */
export function saveQueueContext(ids: readonly string[]): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(ids.filter((id) => typeof id === "string")));
  } catch {
    // Private windows and blocked storage: next and previous just stay unavailable.
  }
}

export function readQueueContext(): string[] {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

/** Position of `currentId` in the saved list, or null when there is no list or it is not in it. */
export function queuePosition(
  ids: readonly string[],
  currentId: string,
): { index: number; total: number } | null {
  const index = ids.indexOf(currentId);
  return index === -1 ? null : { index, total: ids.length };
}

/** The case `delta` places away (1 is next, -1 is previous), or null at either end. */
export function neighbour(
  ids: readonly string[],
  currentId: string,
  delta: 1 | -1,
): Neighbour | null {
  const here = queuePosition(ids, currentId);
  if (!here) return null;
  const target = here.index + delta;
  const id = ids[target];
  if (id === undefined) return null;
  return { id, position: target + 1, total: here.total };
}
