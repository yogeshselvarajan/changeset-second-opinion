import { motion } from "motion/react";
import { useEffect, useState } from "react";

import type { TagDiff } from "../../api/types.gen";
import { t } from "../../i18n";
import { Untrusted } from "../case/Untrusted";
import { easeEnter } from "../motion/tokens";
import { useReducedMotionSafe } from "../motion/useReducedMotionSafe";

/** The strip's own sample, used where no case is available (every value is a constant). */
export const SAMPLE_DIFFS: TagDiff[] = [
  {
    osm_type: "way",
    osm_id: 1,
    key: "name",
    change: "changed",
    before: "Ikeja Rd",
    after: "Ikeja Road",
  },
  { osm_type: "way", osm_id: 1, key: "old_name", change: "added", after: "Ikeja Street" },
  { osm_type: "way", osm_id: 1, key: "surface", change: "removed", before: "unpaved" },
];

const LOOP_MS = 6000;
const MAX_ROWS = 3;

/** A document that is hidden should not keep animating. */
function useDocumentVisible(): boolean {
  // `document` does not exist when the page is rendered to static HTML at build time.
  const [visible, setVisible] = useState(() => typeof document === "undefined" || !document.hidden);
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

function Row({ diff }: { diff: TagDiff }) {
  return (
    <div className="flex min-w-0 items-center gap-2 font-mono text-[12px] leading-6">
      <span className="shrink-0 text-ink-2">
        <Untrusted value={diff.key} />
      </span>
      {diff.change !== "added" ? (
        <span
          className="max-w-[16ch] truncate rounded-[var(--radius-control)] px-1.5 text-ink line-through"
          style={{ background: "var(--color-diff-removed)" }}
        >
          <Untrusted value={diff.before ?? ""} />
        </span>
      ) : null}
      {diff.change === "changed" ? (
        <span aria-hidden="true" className="text-ink-2">
          →
        </span>
      ) : null}
      {diff.change !== "removed" ? (
        <span
          className="max-w-[16ch] truncate rounded-[var(--radius-control)] px-1.5 text-ink"
          style={{
            background:
              diff.change === "added" ? "var(--color-diff-added)" : "var(--color-diff-changed)",
          }}
        >
          <Untrusted value={diff.after ?? ""} />
        </span>
      ) : null}
    </div>
  );
}

/**
 * The product's one illustration: up to three tag changes as key, before, after. `loop` replays the
 * entrance every six seconds (sign-in page only), pausing when the tab is hidden and never moving
 * under reduced motion; `static` is a still frame for headers and empty states. Presentational: the
 * values come from evidence and go through the same escaping as everywhere else.
 */
export function EvidenceStrip({
  diffs,
  loop = false,
  muted = false,
  label,
}: {
  diffs: readonly TagDiff[];
  loop?: boolean;
  /** Greyed, for empty states. */
  muted?: boolean;
  label?: string;
}) {
  const reduced = useReducedMotionSafe();
  const visible = useDocumentVisible();
  const [cycle, setCycle] = useState(0);
  const animate = loop && !reduced;

  useEffect(() => {
    if (!animate || !visible) return;
    const timer = setInterval(() => setCycle((value) => value + 1), LOOP_MS);
    return () => clearInterval(timer);
  }, [animate, visible]);

  const rows = diffs.slice(0, MAX_ROWS);
  if (rows.length === 0) return null;

  return (
    <div
      role="group"
      aria-label={label ?? t("evidence.strip")}
      data-testid="evidence-strip"
      data-animated={animate ? "true" : "false"}
      className={`rounded-[var(--radius-pane)] border border-line bg-surface p-3 ${muted ? "grayscale" : ""}`}
    >
      <motion.div key={cycle} className="flex flex-col">
        {rows.map((diff, index) => (
          <motion.div
            key={`${diff.osm_type}-${diff.osm_id}-${diff.key}-${index}`}
            initial={animate ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.22,
              ease: easeEnter,
              delay: animate ? 0.5 + index * 0.45 : 0,
            }}
          >
            <Row diff={diff} />
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
}
