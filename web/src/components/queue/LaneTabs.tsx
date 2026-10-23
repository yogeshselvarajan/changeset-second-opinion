import type { ReactNode } from "react";
import { Tab, TabList, TabPanel, Tabs } from "react-aria-components";

import type { Lane } from "../../api/types.gen";
import { t } from "../../i18n";
import { LANES } from "../../lib/lanes";
import type { LaneTotals } from "./search";

const tabClass =
  "inline-flex min-h-7 cursor-pointer items-center gap-1 rounded-[var(--radius-chip)] border border-transparent px-3 text-ink-2 outline-none " +
  "data-hovered:text-ink data-selected:border-line data-selected:bg-surface data-selected:font-medium data-selected:text-ink";

/**
 * One tab per lane plus "All lanes", each with its count (`totals` is null until the first load).
 * The counts of the five lanes always add up to the "All lanes" count: lanes order the queue, they
 * never hide a case.
 */
export function LaneTabs({
  lane,
  totals,
  onLane,
  children,
}: {
  lane: Lane | undefined;
  totals: LaneTotals | null;
  onLane: (lane: Lane | undefined) => void;
  children: ReactNode;
}) {
  const selected = lane ?? "all";
  const count = (value: number | undefined): string => (value === undefined ? "" : ` (${value})`);
  return (
    <Tabs
      selectedKey={selected}
      onSelectionChange={(key) => onLane(key === "all" ? undefined : (key as Lane))}
    >
      <TabList
        aria-label={t("queue.lanesLabel")}
        className="cso-lanetabs flex w-fit max-w-full flex-wrap gap-1 p-1"
      >
        <Tab id="all" className={tabClass} data-testid="lane-tab-all">
          <span>{t("queue.tab.all")}</span>
          <span data-testid="lane-count-all">{count(totals?.total).trim()}</span>
        </Tab>
        {LANES.map((meta) => {
          const entry = totals?.entries.find((candidate) => candidate.lane === meta.lane);
          return (
            <Tab
              key={meta.lane}
              id={meta.lane}
              className={tabClass}
              data-testid={`lane-tab-${meta.lane}`}
            >
              <span aria-hidden="true">{meta.glyph}</span>
              <span>{t(meta.label)}</span>
              <span data-testid={`lane-count-${meta.lane}`}>{count(entry?.count).trim()}</span>
            </Tab>
          );
        })}
      </TabList>
      <TabPanel id={selected} className="outline-none">
        {children}
      </TabPanel>
    </Tabs>
  );
}
