import { Link } from "@tanstack/react-router";
import { motion } from "motion/react";
import type { KeyboardEvent } from "react";

import type { DecisionRow } from "../../api/types.gen";
import { t } from "../../i18n";
import { humanize } from "../case/caseModel";
import { BandChip } from "../confidence/BandChip";
import { dispositionLabel } from "../draft/draftModel";
import { RollingCount } from "../motion/RollingCount";
import { easeEnter } from "../motion/tokens";
import { useReducedMotionSafe } from "../motion/useReducedMotionSafe";
import { LaneChip } from "../shell/LaneChip";
import { DecisionDetail } from "./DecisionDetail";
import { shortVersion, timeOf, type DayGroup } from "./historyModel";

function Entry({
  row,
  last,
  expanded,
  onToggle,
  reduced,
}: {
  row: DecisionRow;
  last: boolean;
  expanded: boolean;
  onToggle: () => void;
  reduced: boolean;
}) {
  return (
    <li
      className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-x-3 pb-4"
      data-testid="history-row"
      data-outcome={row.outcome_id}
    >
      <span
        aria-hidden="true"
        className="relative z-10 mt-0.5 grid size-7 place-items-center rounded-full bg-surface-2 text-xs ring-1 ring-line"
      >
        {row.disposition === "agree" ? "✓" : row.disposition === "needs_survey" ? "⌖" : "◐"}
      </span>
      {last ? null : (
        <motion.span
          aria-hidden="true"
          className="absolute bottom-0 left-[13.5px] top-8 w-px origin-top bg-line"
          initial={reduced ? false : { scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.34, ease: easeEnter }}
        />
      )}
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-medium">{row.reviewer_display}</span>
          <span data-testid="row-disposition">{dispositionLabel(row.disposition)}</span>
          <Link to="/cases/$id" params={{ id: row.case_id }} className="font-mono underline">
            {row.changeset_id}
          </Link>
          <time dateTime={row.created_at} className="ml-auto font-mono text-ink-2">
            {timeOf(row.created_at)}
          </time>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-2">
          <LaneChip lane={row.lane_at_decision} />
          <BandChip band={row.band_at_decision} />
          <span>{row.response_type ? humanize(row.response_type) : "-"}</span>
          <span className="font-mono" title={row.config_version}>
            {shortVersion(row.config_version)}
          </span>
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={`detail-${row.outcome_id}`}
            data-history-row
            onClick={onToggle}
            className="min-h-8 rounded-[var(--radius-control)] border border-control-border bg-surface px-2 text-ink"
            data-testid="row-toggle"
          >
            {expanded ? t("history.collapse") : t("history.expand")}
            <span className="sr-only"> {t("history.rowOf", { changeset: row.changeset_id })}</span>
          </button>
        </div>
        {expanded ? (
          <div
            id={`detail-${row.outcome_id}`}
            className="cso-pop mt-2 rounded-[var(--radius-pane)] border border-line bg-surface p-3"
          >
            <DecisionDetail row={row} />
          </div>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Decisions as a day-grouped timeline: one heading per day with a rolling count, one entry per
 * decision joined by a connector that draws in the first time it appears. Arrow keys move between
 * entries; Enter or Space on an entry's button opens its detail. With reduced motion there is no
 * connector animation and the counts are plain text.
 */
export function HistoryTimeline({
  groups,
  open,
  onToggle,
}: {
  groups: readonly DayGroup[];
  open: ReadonlySet<string>;
  onToggle: (id: string) => void;
}) {
  const reduced = useReducedMotionSafe();

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = [...document.querySelectorAll<HTMLElement>("[data-history-row]")];
    const index = buttons.indexOf(document.activeElement as HTMLElement);
    if (index === -1) return;
    event.preventDefault();
    const next = event.key === "ArrowDown" ? index + 1 : index - 1;
    buttons[Math.min(buttons.length - 1, Math.max(0, next))]?.focus();
  }

  return (
    // The arrow-key handler sits on the container; the focusable parts are the buttons inside.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div onKeyDown={onKeyDown}>
      {groups.map((group) => (
        <section
          key={group.day}
          aria-labelledby={`day-${group.day}`}
          className="mt-5 first:mt-0"
          data-testid="history-day"
        >
          <div className="flex items-baseline gap-2">
            <h2 id={`day-${group.day}`} className="text-base font-semibold">
              {group.day}
            </h2>
            <span className="text-ink-2" data-testid="day-count">
              <RollingCount value={group.rows.length} />
            </span>
          </div>
          <ol
            aria-label={t("history.table.caption", { day: group.day })}
            className="mt-3 list-none p-0"
          >
            {group.rows.map((row, index) => (
              <Entry
                key={row.outcome_id}
                row={row}
                last={index === group.rows.length - 1}
                expanded={open.has(row.outcome_id)}
                onToggle={() => onToggle(row.outcome_id)}
                reduced={reduced}
              />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
