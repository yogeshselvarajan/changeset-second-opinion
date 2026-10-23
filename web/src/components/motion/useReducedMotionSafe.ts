import { useReducedMotion } from "motion/react";
import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * True when the user asked for reduced motion. It is false during the first server-style render
 * and true only after hydration, so the markup never differs between the two.
 */
export function useReducedMotionSafe(): boolean {
  const hydrated = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  const reduced = useReducedMotion();
  return hydrated && Boolean(reduced);
}
