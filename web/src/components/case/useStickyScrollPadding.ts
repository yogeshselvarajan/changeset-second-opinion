import { useEffect } from "react";

/**
 * Keep focused elements out from under the sticky bars (WCAG 2.4.11). The top bar and the action bar
 * change height with the screen width, so the page's scroll padding is set from their measured
 * heights instead of a fixed number. This also covers plain Tab navigation, not just the section keys.
 * `watch` changes when a bar appears or disappears, so the padding is measured again.
 */
export function useStickyScrollPadding(watch: string): void {
  useEffect(() => {
    const root = document.documentElement;
    // The first <header> on the page is the application's sticky top bar.
    const topBar = document.querySelector("header");
    const actionBar = document.querySelector<HTMLElement>('[role="toolbar"][data-sticky-bottom]');
    const measure = () => {
      const top = topBar?.getBoundingClientRect().height ?? 0;
      const bottom = actionBar?.offsetHeight ?? 0;
      root.style.scrollPaddingTop = `${Math.ceil(top) + 8}px`;
      root.style.scrollPaddingBottom = `${Math.ceil(bottom) + 8}px`;
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (topBar) observer.observe(topBar);
    if (actionBar) observer.observe(actionBar);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      root.style.removeProperty("scroll-padding-top");
      root.style.removeProperty("scroll-padding-bottom");
    };
  }, [watch]);
}
