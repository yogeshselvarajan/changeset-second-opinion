import { lazy, Suspense } from "react";

import type { CaseDetail, EvidenceSnapshot } from "../../api/types.gen";
import { t } from "../../i18n";
import type { Failure } from "../../lib/problem";
import { ChangedObjectsList } from "./ChangedObjectsList";
import { evidenceIdLabels, groupTagDiffs } from "./caseModel";
import { CoverageBlock } from "./CoverageBlock";
import { DiscussionList } from "./DiscussionList";
import { FactsBlock } from "./FactsBlock";
import { OsmAttribution } from "./OsmAttribution";
import { SectionSkeleton } from "./Section";
import { TagDiffTable, type DiffMode } from "./TagDiffTable";

// The map is its own chunk and is only fetched once the reviewer opens it.
const MapPanel = lazy(() => import("./MapPanel"));

export type EvidenceState =
  | { kind: "none" } // no snapshot yet
  | { kind: "loading" }
  | { kind: "error"; failure: Failure }
  | { kind: "ready"; evidence: EvidenceSnapshot };

/** The left pane: coverage first, then the facts, the tag changes, the objects and the discussion. */
export function EvidencePane({
  detail,
  state,
  onRetry,
  mapOpen,
  onToggleMap,
  diffMode,
  onDiffMode,
}: {
  detail: CaseDetail;
  state: EvidenceState;
  onRetry: () => void;
  mapOpen: boolean;
  onToggleMap: () => void;
  diffMode: DiffMode;
  onDiffMode: (mode: DiffMode) => void;
}) {
  const evidence = state.kind === "ready" ? state.evidence : undefined;
  const bbox = detail.changeset?.bbox;
  const wraps = detail.changeset?.bbox_wraps === true;
  const idLabels = evidenceIdLabels(evidence);

  return (
    <section aria-labelledby="pane-evidence-title" data-testid="pane-evidence">
      <h2 id="pane-evidence-title" className="text-lg font-semibold">
        {t("case.pane.evidence")}
      </h2>
      <div className="mt-3">
        {state.kind === "ready" && evidence ? (
          <CoverageBlock coverage={evidence.coverage} provisional={evidence.provisional} />
        ) : state.kind === "loading" ? (
          <SectionSkeleton label={t("case.loading.coverage")} />
        ) : state.kind === "error" ? (
          <div role="alert" className="rounded border border-control-border p-3 text-sm">
            <p>{state.failure.message}</p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 min-h-8 rounded border border-control-border px-3"
            >
              {t("app.retry")}
            </button>
          </div>
        ) : (
          <p className="text-sm text-text-muted" data-testid="no-evidence">
            {t("case.evidence.none")}
          </p>
        )}

        <FactsBlock
          detail={detail}
          elements={evidence?.elements}
          mapOpen={mapOpen && Boolean(bbox) && !wraps}
          onToggleMap={onToggleMap}
        />
        {mapOpen && bbox && !wraps ? (
          <Suspense fallback={<SectionSkeleton label={t("case.map.loading")} />}>
            <MapPanel bbox={bbox} />
          </Suspense>
        ) : null}
        {mapOpen && wraps ? (
          <p role="status" className="mt-2 text-sm text-text-muted">
            {t("case.map.wraps")}
          </p>
        ) : null}

        {evidence ? (
          <>
            <TagDiffTable
              groups={groupTagDiffs(evidence.tag_diffs)}
              mode={diffMode}
              onModeChange={onDiffMode}
              idLabels={idLabels}
              detailed={evidence.coverage.elements_detailed}
              total={evidence.coverage.elements_in_changeset}
            />
            <ChangedObjectsList
              elements={evidence.elements ?? []}
              idLabels={idLabels}
              total={evidence.coverage.elements_in_changeset}
            />
            <DiscussionList
              entries={evidence.discussion ?? []}
              status={evidence.coverage.discussion}
            />
          </>
        ) : state.kind === "loading" ? (
          <div className="mt-6">
            <SectionSkeleton label={t("case.loading.evidence")} />
          </div>
        ) : null}

        <OsmAttribution attribution={detail.attribution} />
      </div>
    </section>
  );
}
