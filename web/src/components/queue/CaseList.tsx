import { useState } from "react";
import { Checkbox, GridList, GridListItem, type Selection } from "react-aria-components";

import type { Band, CaseSummary } from "../../api/types.gen";
import { t } from "../../i18n";
import { laneMeta } from "../../lib/lanes";
import { Untrusted } from "../case/Untrusted";
import { CountMeter } from "../evidence/CountMeter";
import { bandText, formatAge, outcomeText, rowLabel, statusText } from "./search";

const BAND_GLYPH: Record<Band, string> = { confident: "●", unsure: "◐", cannot_tell: "○" };

/** Lane glyph, id, editor and place, counts, band, age: the six columns of a row from 800 px up. */
const COLUMNS =
  "min-[800px]:grid min-[800px]:grid-cols-[24px_110px_minmax(0,1fr)_120px_140px_56px] min-[800px]:items-center min-[800px]:gap-3";

/** One row: every value is a text node, so evidence-derived text is escaped, never parsed as HTML. */
function CaseRow({ item, now, fresh }: { item: CaseSummary; now: number; fresh: boolean }) {
  const label = rowLabel(item, now);
  const age = formatAge(item.created_at, now);
  const lane = laneMeta(item.lane);
  return (
    <GridListItem
      id={item.id}
      textValue={label}
      aria-label={label}
      data-case-id={item.id}
      data-testid="case-row"
      style={{ minHeight: "var(--row-h)" }}
      className={`${fresh ? "cso-row-in " : ""}group flex cursor-pointer items-start gap-3 border-b border-line bg-surface px-4 py-1.5 text-ink outline-none data-hovered:bg-surface-2 data-selected:border-l-4 data-selected:border-l-accent data-focus-visible:bg-surface-2`}
    >
      <Checkbox
        slot="selection"
        className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-control-border bg-canvas"
      >
        {({ isSelected }) => (
          <span aria-hidden="true" className="text-xs">
            {isSelected ? "✓" : ""}
          </span>
        )}
      </Checkbox>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className={`flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 ${COLUMNS}`}>
          <span
            data-lane={item.lane}
            aria-hidden="true"
            title={t(lane.label)}
            className="grid size-6 place-items-center rounded-[var(--radius-control)] text-xs"
            style={{ background: lane.bg, color: lane.fg }}
          >
            {lane.glyph}
          </span>
          <span className="font-mono">#{item.changeset_id}</span>
          <span className="flex min-w-0 flex-wrap gap-x-2 min-[800px]:flex-nowrap">
            <span className="min-w-0 truncate">
              {item.editor ? (
                <Untrusted value={item.editor} />
              ) : (
                <span className="text-ink-2">{t("queue.editor.unknown")}</span>
              )}
            </span>
            <span aria-hidden="true" className="text-ink-2">
              ·
            </span>
            <span className={`min-w-0 truncate ${item.place_label ? "" : "text-ink-2"}`}>
              {item.place_label ? <Untrusted value={item.place_label} /> : t("queue.place.unknown")}
            </span>
          </span>
          <CountMeter counts={item.element_counts} />
          <span className="whitespace-nowrap">
            <span aria-hidden="true">{item.band ? BAND_GLYPH[item.band] : "-"} </span>
            {bandText(item.band)}
          </span>
          <time dateTime={item.created_at} className="text-ink-2 min-[800px]:text-right">
            {age.short}
          </time>
        </div>
        {item.comment ? (
          <p data-testid="row-comment" className="m-0 truncate pt-0.5 text-sm text-ink">
            <span className="text-ink-2">{t("queue.row.said")} </span>
            <Untrusted value={item.comment} />
          </p>
        ) : null}
        <div
          data-testid="row-detail"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-xs text-ink-2"
        >
          {item.flags && item.flags.length > 0 ? (
            <span className="font-mono">
              {item.flags.map((flag, index) => (
                <span key={`${index}-${flag}`}>
                  {index > 0 ? ", " : ""}
                  <Untrusted value={flag} />
                </span>
              ))}
            </span>
          ) : null}
          <span>{statusText(item.status)}</span>
          {item.latest_outcome ? <span>{outcomeText(item.latest_outcome)}</span> : null}
          {item.stale ? (
            <span
              title={t("queue.stale.hint")}
              className="rounded-[var(--radius-chip)] border border-control-border px-1.5 text-ink"
            >
              {t("queue.stale")}
            </span>
          ) : null}
        </div>
      </div>
    </GridListItem>
  );
}

/**
 * The queue rows. Arrow keys move between rows, Enter or a click opens the case, Space or the box
 * marks it. j, k, o and x are added by the screen; marking only highlights, it never acts.
 */
export function CaseList({
  items,
  now,
  marked,
  onMarkedChange,
  onOpen,
}: {
  items: CaseSummary[];
  now: number;
  marked: ReadonlySet<string>;
  onMarkedChange: (next: Set<string>) => void;
  onOpen: (id: string) => void;
}) {
  // Rows that were not in the previous list slide in; the first list and unchanged rows do not move.
  const ids = items.map((item) => item.id);
  const key = ids.join("|");
  const [seen, setSeen] = useState(() => ({ key, set: new Set(ids), fresh: new Set<string>() }));
  if (seen.key !== key) {
    setSeen({ key, set: new Set(ids), fresh: new Set(ids.filter((id) => !seen.set.has(id))) });
  }
  return (
    <GridList
      aria-label={t("queue.listLabel")}
      selectionMode="multiple"
      selectedKeys={marked}
      onSelectionChange={(selection: Selection) => {
        onMarkedChange(
          selection === "all"
            ? new Set(items.map((item) => item.id))
            : new Set([...selection].map(String)),
        );
      }}
      onAction={(key) => onOpen(String(key))}
    >
      {items.map((item) => (
        <CaseRow key={item.id} item={item} now={now} fresh={seen.fresh.has(item.id)} />
      ))}
    </GridList>
  );
}
