import { useEffect } from "react";

/**
 * Keep the page's scroll padding equal to the sticky top bar's height. Every scroll-into-view,
 * including the one a focus call does, then stops below the bar, so a focused row is never hidden
 * under it (WCAG 2.4.11 Focus Not Obscured), whatever the bar's height is: it wraps onto several
 * lines on a phone.
 */
export function useTopBarOffset(): void {
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>("header");
    if (!bar) return;
    const root = document.documentElement;
    const publish = () => {
      root.style.scrollPaddingTop = `${Math.ceil(bar.getBoundingClientRect().height) + 8}px`;
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(bar);
    return () => {
      observer.disconnect();
      root.style.removeProperty("scroll-padding-top");
    };
  }, []);
}
