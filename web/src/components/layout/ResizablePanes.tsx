import {
  useCallback,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { t } from "../../i18n";

const KEY = "cso.panes";
const MIN = 30;
const MAX = 75;
const DEFAULT = 60;
const STEP = 2;

function clamp(value: number): number {
  return Math.min(MAX, Math.max(MIN, Math.round(value)));
}

function readSplit(): number {
  try {
    const stored = Number(localStorage.getItem(KEY));
    return Number.isFinite(stored) && stored > 0 ? clamp(stored) : DEFAULT;
  } catch {
    return DEFAULT; // blocked storage: the default split still works
  }
}

function writeSplit(value: number): void {
  try {
    localStorage.setItem(KEY, String(value));
  } catch {
    // The layout works without storage; the choice just does not survive a reload.
  }
}

/**
 * Two panes side by side from 1024 px with a draggable, keyboard-resizable divider (the left pane
 * takes `split` percent; arrow keys move it by two points, Home and End go to the limits). Below
 * 1024 px the panes stack with `end` first, as before, and the divider is not shown. The split is
 * remembered in this browser only.
 */
export function ResizablePanes({ start, end }: { start: ReactNode; end: ReactNode }) {
  const [split, setSplit] = useState(readSplit);
  const container = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const commit = useCallback((value: number) => {
    const next = clamp(value);
    setSplit(next);
    writeSplit(next);
  }, []);

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!dragging.current || !container.current) return;
    const box = container.current.getBoundingClientRect();
    if (box.width <= 0) return;
    setSplit(clamp(((event.clientX - box.left) / box.width) * 100));
  }
  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (!dragging.current) return;
    dragging.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
    writeSplit(split);
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") commit(split - STEP);
    else if (event.key === "ArrowRight") commit(split + STEP);
    else if (event.key === "Home") commit(MIN);
    else if (event.key === "End") commit(MAX);
    else return;
    event.preventDefault();
  }

  return (
    <div
      ref={container}
      className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,var(--pane-a))_12px_minmax(0,var(--pane-b))] lg:gap-0"
      style={{ ["--pane-a" as string]: `${split}fr`, ["--pane-b" as string]: `${100 - split}fr` }}
      data-testid="panes"
    >
      <div className="order-2 min-w-0 lg:order-1 lg:pr-4">{start}</div>
      {/* A focusable separator is the WAI-ARIA "window splitter": it is interactive, which the
          lint rules cannot tell from the role. */}
      {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      <div
        role="separator"
        tabIndex={0}
        aria-orientation="vertical"
        aria-label={t("panes.divider")}
        aria-valuemin={MIN}
        aria-valuemax={MAX}
        aria-valuenow={split}
        aria-valuetext={t("panes.value", { evidence: split, verdict: 100 - split })}
        data-testid="pane-divider"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKeyDown}
        className="group relative order-3 hidden cursor-col-resize touch-none justify-center lg:order-2 lg:flex"
      >
        <span
          aria-hidden="true"
          className="h-full w-px bg-line group-hover:w-0.5 group-hover:bg-accent group-focus-visible:w-0.5 group-focus-visible:bg-accent"
        />
      </div>
      {/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      <div className="order-1 min-w-0 lg:order-3 lg:pl-4">{end}</div>
    </div>
  );
}
