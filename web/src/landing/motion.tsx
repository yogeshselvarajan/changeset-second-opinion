import { useEffect, useRef, type CSSProperties, type ElementType, type ReactNode } from "react";

/**
 * Small motion helpers for the public pages. All of them
 *  - leave the static HTML fully visible, so a crawler or a visitor without script sees everything;
 *  - do nothing when the visitor asks for reduced motion;
 *  - change the DOM directly instead of React state, so they never cause a re-render.
 */

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Fades a block in the first time it scrolls into view. Blocks already on screen when the page
 * becomes live are left alone, so nothing flashes.
 */
export function Reveal({
  as,
  delay = 0,
  className,
  children,
}: {
  as?: ElementType;
  delay?: number;
  className?: string;
  children: ReactNode;
}) {
  const Tag = as ?? "div";
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion() || typeof IntersectionObserver === "undefined") return;
    if (el.getBoundingClientRect().top < window.innerHeight * 0.92) return;
    el.dataset.reveal = "hidden";
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          el.dataset.reveal = "shown";
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      delete el.dataset.reveal;
    };
  }, []);

  return (
    <Tag
      ref={ref}
      className={`reveal ${className ?? ""}`}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

/**
 * Writes the pointer position, from -1 to 1 across the element, to `--px` and `--py` on it, so
 * layers can drift a few pixels at different depths. Skipped for touch and reduced motion.
 */
export function usePointerParallax<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;
    if (typeof window.matchMedia === "function" && !window.matchMedia("(pointer: fine)").matches) {
      return;
    }
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = el.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
        const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
        const clamp = (value: number) => Math.max(-1, Math.min(1, value));
        el.style.setProperty("--px", clamp(x).toFixed(3));
        el.style.setProperty("--py", clamp(y).toFixed(3));
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
    };
  }, []);

  return ref;
}

/** A card with a soft light that follows the pointer (CSS reads `--mx` and `--my`). */
export function SpotlightCard({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`spotlight ${className ?? ""}`}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        event.currentTarget.style.setProperty("--mx", `${event.clientX - rect.left}px`);
        event.currentTarget.style.setProperty("--my", `${event.clientY - rect.top}px`);
      }}
    >
      {children}
    </div>
  );
}
