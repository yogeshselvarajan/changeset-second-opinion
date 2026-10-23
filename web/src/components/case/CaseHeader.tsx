import { Link } from "@tanstack/react-router";

import type { CaseDetail, TagDiff } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import { BandChip } from "../confidence/BandChip";
import { EvidenceStrip } from "../evidence/EvidenceStrip";
import { LaneChip } from "../shell/LaneChip";
import { Untrusted } from "./Untrusted";

const STATUS_LABEL: Record<CaseDetail["status"], MessageKey> = {
  new: "case.status.new",
  analyzing: "case.status.analyzing",
  analyzed: "case.status.analyzed",
  decided: "case.status.decided",
};

export interface Notice {
  tone: "info" | "error";
  text: string;
}

export interface NeighbourLinks {
  position: number;
  total: number;
  previous: string | null;
  next: string | null;
}

/** The top of the case screen: where it is in the queue, what it is, its lane, band and state. */
export function CaseHeader({
  detail,
  canMutate,
  neighbours,
  busy,
  notice,
  onReanalyze,
  onCopyReceipt,
  diffs = [],
}: {
  /** Copies the public receipt link of the latest run; absent when there is no run yet. */
  onCopyReceipt?: () => void;
  /** The top tag changes, shown as a still strip under the title. */
  diffs?: readonly TagDiff[];
  detail: CaseDetail;
  canMutate: boolean;
  neighbours: NeighbourLinks | null;
  busy: boolean;
  notice: Notice | null;
  onReanalyze: () => void;
}) {
  return (
    <header aria-labelledby="case-title" className="cso-hero" data-testid="case-header">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Link
          to="/queue"
          className="inline-flex min-h-8 items-center underline"
          data-testid="back-to-queue"
        >
          {t("case.back")}
        </Link>
        {neighbours ? (
          <nav aria-label={t("case.neighbours.label")} className="flex items-center gap-3">
            <span data-testid="queue-position">
              {t("case.neighbours.position", { n: neighbours.position, total: neighbours.total })}
            </span>
            {neighbours.previous ? (
              <Link
                to="/cases/$id"
                params={{ id: neighbours.previous }}
                className="inline-flex min-h-8 items-center underline"
              >
                {t("case.neighbours.previous")}
              </Link>
            ) : null}
            {neighbours.next ? (
              <Link
                to="/cases/$id"
                params={{ id: neighbours.next }}
                className="inline-flex min-h-8 items-center underline"
              >
                {t("case.neighbours.next")}
              </Link>
            ) : null}
          </nav>
        ) : null}
      </div>

      <h1 id="case-title" className="mt-2 text-xl font-semibold">
        {t("case.heading", { id: detail.changeset_id })}
      </h1>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <LaneChip lane={detail.lane} />
        <BandChip band={detail.band} />
        <span className="text-sm" data-testid="case-status">
          {t(STATUS_LABEL[detail.status])}
        </span>
        {onCopyReceipt ? (
          <button
            type="button"
            onClick={onCopyReceipt}
            aria-keyshortcuts="l"
            data-testid="copy-receipt"
            className="min-h-7 rounded-[var(--radius-control)] border border-control-border bg-surface px-2 text-sm text-ink"
          >
            {t("case.receipt.copy")} <kbd className="ml-1 font-mono text-xs text-ink-2">l</kbd>
          </button>
        ) : null}
        {!canMutate ? (
          <span
            className="rounded border border-border px-2 py-0.5 text-xs"
            data-testid="view-only"
          >
            {t("role.viewOnly")}
          </span>
        ) : null}
      </div>

      {detail.editor || detail.place_label ? (
        <p className="mt-1 text-sm text-text-muted">
          {detail.editor ? <Untrusted value={detail.editor} /> : null}
          {detail.editor && detail.place_label ? " · " : null}
          {detail.place_label ? <Untrusted value={detail.place_label} /> : null}
        </p>
      ) : null}

      {diffs.length > 0 ? (
        <div className="mt-3 max-w-xl">
          <EvidenceStrip diffs={diffs} />
        </div>
      ) : null}

      {detail.stale ? (
        <div
          className="mt-3 flex flex-wrap items-center gap-3 rounded border border-control-border p-2"
          data-testid="stale-banner"
        >
          <p className="text-sm">
            <strong>{t("case.stale.badge")}</strong> {t("case.stale.body")}
          </p>
          {canMutate ? (
            <button
              type="button"
              onClick={onReanalyze}
              disabled={busy}
              className="min-h-8 rounded border border-control-border px-3 text-sm"
              data-testid="reanalyze"
            >
              {busy ? t("case.reanalyze.busy") : t("case.reanalyze.action")}
            </button>
          ) : (
            <span className="text-sm text-text-muted">{t("case.stale.viewerNote")}</span>
          )}
        </div>
      ) : null}

      {notice ? (
        <p
          role={notice.tone === "error" ? "alert" : "status"}
          className="mt-2 text-sm"
          data-testid="case-notice"
        >
          {notice.text}
        </p>
      ) : null}
    </header>
  );
}
