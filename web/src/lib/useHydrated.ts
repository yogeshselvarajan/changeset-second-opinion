import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * False while a page is rendered to static HTML and during the first browser render, true after.
 * Use it to start behaviour (an animation) that the static page must not contain, without setting
 * state inside an effect.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
