import { useNavigate, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { requestAnalysis } from "../../api/sdk.gen";
import { t } from "../../i18n";
import { failureFromResponse, networkFailure } from "../../lib/problem";
import { neighbour, queuePosition, readQueueContext } from "../../lib/queueContext";
import { canMutate as roleCanMutate } from "../../lib/roles";
import { useMe } from "../../lib/useMe";
import { copyText } from "../draft/clipboard";
import { ResizablePanes } from "../layout/ResizablePanes";
import { PaneBoundary } from "../shell/PaneBoundary";
import { ForbiddenPage } from "../shell/ErrorPages";
import { useAnnounce } from "../shell/Announcer";
import { OutcomeDialog } from "../draft/OutcomeDialog";
import { ActionBar, type OutcomeAction } from "./ActionBar";
import { draftResponses } from "./caseModel";
import { CaseHeader, type Notice } from "./CaseHeader";
import { EvidencePane, type EvidenceState } from "./EvidencePane";
import { failureFromError } from "./failure";
import { RecommendationPane } from "./RecommendationPane";
import { SectionSkeleton } from "./Section";
import { useCaseKeys, jumpToSection } from "./useCaseKeys";
import { useStickyScrollPadding } from "./useStickyScrollPadding";
import {
  isTerminal,
  useAnalysisJob,
  useCaseDetail,
  useConfig,
  useEvidence,
  useInvalidateCase,
  useRunDetail,
  useRuns,
} from "./useCaseData";
import { useDiffMode } from "./useDiffMode";

function Message({ title, body, children }: { title: string; body: string; children?: ReactNode }) {
  return (
    <section
      aria-labelledby="case-title"
      className="mx-auto max-w-xl p-6"
      data-testid="case-message"
    >
      <h1 id="case-title" className="text-xl font-semibold">
        {title}
      </h1>
      <p className="mt-2 text-text-muted">{body}</p>
      <div className="mt-4 flex flex-wrap gap-3">{children}</div>
    </section>
  );
}

/** The case screen: evidence on one side, the recommendation on the other, actions at the bottom. */
export function CaseDetailView({ id }: { id: string }) {
  const navigate = useNavigate();
  const announce = useAnnounce();
  const { me } = useMe();
  const canMutate = roleCanMutate(me?.role);

  const caseQuery = useCaseDetail(id);
  const detail = caseQuery.data;
  const snapshotId = detail?.latest_snapshot_id;
  const evidenceQuery = useEvidence(id, snapshotId);
  const runsQuery = useRuns(id);
  const runDetailQuery = useRunDetail(detail?.latest_run?.id);
  const configQuery = useConfig();
  const invalidate = useInvalidateCase(id);

  const [jobId, setJobId] = useState<string | null>(null);
  const jobQuery = useAnalysisJob(jobId);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  const [outcomeAction, setOutcomeAction] = useState<OutcomeAction | null>(null);
  const [diffMode, setDiffMode] = useDiffMode();

  // ---------------------------------------------------------------- queue neighbours
  // The screen is keyed by case id, so it remounts (and re-reads this) when next or previous moves.
  const queueIds = useMemo(() => readQueueContext(), []);
  const here = queuePosition(queueIds, id);
  const previous = neighbour(queueIds, id, -1);
  const next = neighbour(queueIds, id, 1);
  const neighbours = here
    ? {
        position: here.index + 1,
        total: here.total,
        previous: previous?.id ?? null,
        next: next?.id ?? null,
      }
    : null;

  // ---------------------------------------------------------------- analysis progress
  const jobStatus = jobQuery.data?.status;
  const jobEnded = Boolean(jobId) && isTerminal(jobStatus);
  const jobNotice: Notice | null = jobEnded
    ? jobStatus === "succeeded"
      ? { tone: "info", text: t("case.job.done") }
      : { tone: "error", text: t("case.job.didNotFinish") }
    : null;
  // Once per job: say how it ended and pick up the new run and evidence.
  const handledJob = useRef<string | null>(null);
  useEffect(() => {
    if (!jobId || !jobEnded || handledJob.current === jobId) return;
    handledJob.current = jobId;
    announce(jobStatus === "succeeded" ? t("case.job.done") : t("case.job.didNotFinish"));
    void invalidate();
  }, [jobId, jobEnded, jobStatus, announce, invalidate]);

  // The band and the rules reveal only when this screen watches a case go from analyzing to
  // analyzed; a plain load shows them without any motion.
  const [watched, setWatched] = useState(detail?.status);
  const [reveal, setReveal] = useState(false);
  if (detail?.status !== watched) {
    setWatched(detail?.status);
    setReveal(watched === "analyzing" && detail?.status === "analyzed");
  }

  // When the server itself reports that an analysis ended, pick up the new run and evidence.
  const previousStatus = useRef(detail?.status);
  useEffect(() => {
    const before = previousStatus.current;
    previousStatus.current = detail?.status;
    if (before === "analyzing" && detail && detail.status !== "analyzing") void invalidate();
  }, [detail, invalidate]);

  const reanalyze = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await requestAnalysis({ path: { id }, body: {}, throwOnError: false });
      const response = result.response;
      if (!response) {
        setNotice({ tone: "error", text: networkFailure().message });
        return;
      }
      if (response.status === 202 && result.data && "job_id" in result.data) {
        setJobId(result.data.job_id);
        setNotice({ tone: "info", text: t("case.reanalyze.started") });
        announce(t("case.reanalyze.started"));
        void invalidate();
        return;
      }
      if (response.status === 200) {
        setNotice({ tone: "info", text: t("case.reanalyze.current") });
        announce(t("case.reanalyze.current"));
        return;
      }
      const failure = failureFromResponse(
        response.status,
        result.error,
        response.headers.get("Retry-After"),
      );
      const running =
        typeof result.error === "object" && result.error !== null && "job_id" in result.error
          ? (result.error as { job_id?: unknown }).job_id
          : undefined;
      if (response.status === 409 && typeof running === "string") {
        setJobId(running);
        setNotice({ tone: "info", text: t("case.reanalyze.alreadyRunning") });
      } else {
        setNotice({ tone: "error", text: failure.message });
      }
    } catch {
      setNotice({ tone: "error", text: networkFailure().message });
    } finally {
      setBusy(false);
    }
  }, [announce, busy, id, invalidate]);

  // ---------------------------------------------------------------- what the screen may offer
  const run = detail?.latest_run;
  const draftable = draftResponses(detail);
  const canDraft = canMutate && draftable.length > 0;
  const draftReason = !run
    ? t("case.draft.noRun")
    : run.status === "failed"
      ? t("case.draft.runFailed")
      : draftable.length > 0
        ? null
        : detail?.stale
          ? t("case.draft.stale")
          : t("case.draft.notComment");
  const hasMap = Boolean(detail?.changeset?.bbox);

  // The receipt link is the public page of the latest run; it uses the origin this page is on.
  const receiptRunId = run?.id ?? null;
  const copyReceiptLink = useCallback(async () => {
    if (!receiptRunId) {
      announce(t("case.receipt.noRun"));
      return;
    }
    const ok = await copyText(`${window.location.origin}/r/${receiptRunId}`);
    announce(ok ? t("case.receipt.copied") : t("case.receipt.copyFailed"));
  }, [announce, receiptRunId]);

  const goToNeighbour = useCallback(
    (target: ReturnType<typeof neighbour>) => {
      if (!target) {
        announce(t("case.neighbours.none"));
        return;
      }
      announce(t("case.neighbours.selected", { n: target.position, total: target.total }));
      void navigate({ to: "/cases/$id", params: { id: target.id } });
    },
    [announce, navigate],
  );

  const viewOnly = useCallback(() => announce(t("case.keys.viewOnly")), [announce]);
  const openOutcome = useCallback(
    (action: OutcomeAction) => {
      if (!canMutate) return viewOnly();
      // An outcome is recorded against a run the reviewer saw, so a case with no run cannot take one.
      if (!detail?.latest_run) return announce(t("case.draft.noRun"));
      setOutcomeAction(action);
    },
    [announce, canMutate, detail?.latest_run, viewOnly],
  );

  useCaseKeys({
    j: () => announce(jumpToSection(1) ?? ""),
    k: () => announce(jumpToSection(-1) ?? ""),
    n: () => goToNeighbour(next),
    "]": () => goToNeighbour(next),
    p: () => goToNeighbour(previous),
    "[": () => goToNeighbour(previous),
    t: () => {
      const target = diffMode === "side" ? "unified" : "side";
      setDiffMode(target);
      announce(t(target === "side" ? "case.diff.modeSide" : "case.diff.modeUnified"));
    },
    u: () => void navigate({ to: "/queue" }),
    l: () => void copyReceiptLink(),
    m: () => {
      if (!hasMap) {
        announce(t("case.map.none"));
        return;
      }
      setMapOpen((open) => !open);
    },
    d: () => {
      if (!canMutate) return viewOnly();
      if (!canDraft) return announce(draftReason ?? "");
      void navigate({ to: "/cases/$id/draft", params: { id } });
    },
    a: () => openOutcome("agree"),
    s: () => openOutcome("needs_survey"),
    x: () => openOutcome("disagree_with_model"),
  });

  useStickyScrollPadding(`${canMutate}:${detail?.id ?? ""}`);

  // ---------------------------------------------------------------- states
  if (caseQuery.isPending) {
    return (
      <section aria-labelledby="case-title" className="mx-auto max-w-3xl p-6" aria-busy="true">
        <h1 id="case-title" className="text-xl font-semibold">
          {t("case.loading.title")}
        </h1>
        <div className="mt-4">
          <SectionSkeleton label={t("case.loading.case")} />
        </div>
      </section>
    );
  }

  if (caseQuery.isError || !detail) {
    const failure = failureFromError(caseQuery.error);
    if (failure.kind === "forbidden") return <ForbiddenPage />;
    if (failure.kind === "not_found") {
      return (
        <Message title={t("case.error.notFound.title")} body={t("case.error.notFound.body")}>
          <Link to="/queue" className="underline">
            {t("error.backToQueue")}
          </Link>
        </Message>
      );
    }
    if (failure.kind === "unauthorized") {
      return (
        <Message title={t("case.error.signIn.title")} body={t("case.error.signIn.body")}>
          <Link
            to="/login"
            search={{ redirect: `/cases/${id}` }}
            className="inline-flex min-h-8 items-center rounded border border-control-border px-3"
          >
            {t("case.error.signIn.action")}
          </Link>
        </Message>
      );
    }
    return (
      <Message title={t("case.error.generic.title")} body={failure.message}>
        <button
          type="button"
          onClick={() => void caseQuery.refetch()}
          className="min-h-8 rounded border border-control-border px-3"
        >
          {t("app.retry")}
        </button>
      </Message>
    );
  }

  const evidenceState: EvidenceState = !snapshotId
    ? { kind: "none" }
    : evidenceQuery.isError
      ? { kind: "error", failure: failureFromError(evidenceQuery.error) }
      : evidenceQuery.data
        ? { kind: "ready", evidence: evidenceQuery.data }
        : { kind: "loading" };

  return (
    <div className="cso-page cso-page-wide" data-testid="case-view" data-case-id={id}>
      <CaseHeader
        detail={detail}
        canMutate={canMutate}
        neighbours={neighbours}
        busy={busy}
        notice={jobNotice ?? notice}
        onReanalyze={() => void reanalyze()}
        onCopyReceipt={receiptRunId ? () => void copyReceiptLink() : undefined}
        diffs={evidenceState.kind === "ready" ? (evidenceState.evidence.tag_diffs ?? []) : []}
      />
      <div className="mt-4">
        <ResizablePanes
          start={
            <PaneBoundary name="evidence">
              <EvidencePane
                detail={detail}
                state={evidenceState}
                onRetry={() => void evidenceQuery.refetch()}
                mapOpen={mapOpen}
                onToggleMap={() => setMapOpen((open) => !open)}
                diffMode={diffMode}
                onDiffMode={setDiffMode}
              />
            </PaneBoundary>
          }
          end={
            <PaneBoundary name="verdict">
              <RecommendationPane
                detail={detail}
                runDetail={runDetailQuery.data}
                config={configQuery.data}
                runs={runsQuery.data?.items}
                runsFailure={runsQuery.isError ? failureFromError(runsQuery.error) : null}
                job={jobQuery.data}
                reveal={reveal}
              />
            </PaneBoundary>
          }
        />
      </div>
      {canMutate ? (
        <ActionBar
          caseId={id}
          canDraft={canDraft}
          draftReason={draftReason}
          onOutcome={openOutcome}
        />
      ) : null}
      {outcomeAction && detail ? (
        <OutcomeDialog
          detail={detail}
          disposition={outcomeAction}
          onClose={() => setOutcomeAction(null)}
        />
      ) : null}
    </div>
  );
}
