import { Link } from "@tanstack/react-router";
import { useMemo, useState, type ReactNode } from "react";

import type { Response } from "../../api/types.gen";
import { t } from "../../i18n";
import { canMutate as mayMutate } from "../../lib/roles";
import { useMe } from "../../lib/useMe";
import { draftResponses } from "../case/caseModel";
import { failureFromError } from "../case/failure";
import { SectionSkeleton } from "../case/Section";
import { Untrusted } from "../case/Untrusted";
import {
  optionLookup,
  isTerminal,
  useAnalysisJob,
  useCaseDetail,
  useConfig,
  useEvidence,
} from "../case/useCaseData";
import { NotFoundPage } from "../shell/ErrorPages";
import { useAnnounce } from "../shell/Announcer";
import { controlClass } from "../queue/QueueDialog";
import type { ToneRules } from "./draftChecks";
import { joinParts } from "./draftChecks";
import { DraftEditor } from "./DraftEditor";
import { draftFailureMessage } from "./draftModel";
import { startDraft, useDraft } from "./useDraftData";

/**
 * `/cases/$id/draft`: choose the kind of comment, request a draft (a background job, polled every
 * two seconds), then edit and approve it. The page never posts anywhere.
 */
export function DraftScreen({ id }: { id: string }) {
  const announce = useAnnounce();
  const { me, isPending: mePending } = useMe();
  const caseQuery = useCaseDetail(id);
  const config = useConfig();
  const [jobId, setJobId] = useState<string | null>(null);
  const [regenerated, setRegenerated] = useState(false);
  const [chooser, setChooser] = useState(false);
  const [chosen, setChosen] = useState<Response | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const job = useAnalysisJob(jobId);
  const jobStatus = job.data?.status;
  const generatedDraftId =
    jobStatus === "succeeded" ? (job.data?.result_ref?.draft_id ?? null) : null;
  const generated = useDraft(generatedDraftId);

  const detail = caseQuery.data;
  // The evidence text, so the lines a draft cites can be shown beside it (a failed load just
  // leaves the ids without their lines).
  const evidence = useEvidence(id, detail?.latest_snapshot_id);
  const evidenceText = evidence.data?.rendered_text;
  const run = detail?.latest_run ?? null;
  const recommended = detail?.response ?? null;
  const existing =
    detail?.latest_draft && run && detail.latest_draft.run_id === run.id
      ? detail.latest_draft
      : null;
  // The server says which kinds of comment the latest analysis allows.
  const kinds: Response[] = draftResponses(detail);
  const kind: Response =
    chosen ??
    existing?.response_type ??
    (recommended !== null && kinds.includes(recommended)
      ? recommended
      : (kinds[0] ?? "welcome_and_tips"));
  const canMutate = mayMutate(me?.role);

  const tone: ToneRules | null = useMemo(() => {
    const source = config.data?.tone;
    return source
      ? {
          bannedWords: source.banned_words,
          allowedLinks: source.allowed_links,
          languagePolicy: source.language_policy,
        }
      : null;
  }, [config.data?.tone]);

  async function request(regenerate: boolean) {
    if (requesting) return;
    setRequesting(true);
    setRequestError(null);
    const result = await startDraft(id, kind, regenerate);
    setRequesting(false);
    if (result.ok) {
      setJobId(result.jobId);
      setChooser(false);
      if (regenerate) setRegenerated(true);
      announce(t("draft.generating.status"));
    } else {
      setRequestError(result.message);
      announce(result.message);
    }
  }

  const back = (
    <Link
      to="/cases/$id"
      params={{ id }}
      className="inline-flex min-h-8 items-center underline"
      data-testid="draft-back"
    >
      {t("draft.back")} <kbd className="ml-2 font-mono text-xs">Esc</kbd>
    </Link>
  );
  const heading = (
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
      <h1 id="draft-title" className="text-xl font-semibold">
        {detail ? t("draft.title", { changeset: detail.changeset_id }) : t("draft.title.loading")}
      </h1>
      {back}
    </header>
  );
  const shell = (body: ReactNode) => (
    <section aria-labelledby="draft-title" className="cso-page" data-testid="draft-screen">
      {heading}
      <div className="mt-4">{body}</div>
    </section>
  );

  if (caseQuery.isPending || mePending) {
    return shell(<SectionSkeleton label={t("draft.loading")} />);
  }
  if (caseQuery.isError || !detail) {
    const failure = failureFromError(caseQuery.error);
    if (failure.kind === "not_found") return <NotFoundPage />;
    return shell(
      <p role="alert" data-testid="draft-load-error">
        {failure.message}
      </p>,
    );
  }

  const canDraftNow = run?.status === "succeeded";

  // A viewer may read the latest draft but not change anything.
  if (!canMutate) {
    return shell(
      <div data-testid="draft-viewer">
        <p className="text-sm">{t("draft.viewer")}</p>
        {existing ? (
          <>
            <h2 className="mt-3 text-sm font-semibold">{t("draft.label.editor")}</h2>
            <Untrusted
              block
              value={joinParts(existing)}
              className="mt-1 rounded border border-border p-2 text-sm"
            />
          </>
        ) : null}
        <p className="mt-3 text-xs text-text-muted">{t("draft.notice")}</p>
      </div>,
    );
  }

  if (!canDraftNow) {
    return shell(
      <p data-testid="draft-no-run">{run ? t("case.draft.runFailed") : t("case.draft.noRun")}</p>,
    );
  }
  if (config.isPending) return shell(<SectionSkeleton label={t("draft.loading")} />);
  if (!tone) {
    return shell(
      <div role="alert" data-testid="draft-tone-error">
        <p>{t("draft.tone.error")}</p>
        <button
          type="button"
          onClick={() => void config.refetch()}
          className={`${controlClass} mt-2`}
        >
          {t("app.retry")}
        </button>
      </div>,
    );
  }

  const options = optionLookup(config.data?.option_sets.response);
  const generating =
    jobId !== null &&
    (job.isPending ||
      (job.data !== undefined && !isTerminal(job.data.status)) ||
      (generatedDraftId !== null && generated.isPending));
  const jobEnded = job.data !== undefined && isTerminal(job.data.status);
  const jobFailed = jobEnded && jobStatus !== "succeeded";
  const draftError = generatedDraftId !== null && generated.isError;

  if (chooser || (jobId === null && !existing)) {
    const canRequest = kinds.includes(kind);
    return shell(
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void request(false);
        }}
        aria-labelledby="draft-choose-title"
        data-testid="draft-chooser"
      >
        <h2 id="draft-choose-title" className="text-base font-semibold">
          {t("draft.choose.title")}
        </h2>
        <p className="mt-1 text-sm text-text-muted">{t("draft.choose.hint")}</p>
        {kinds.length === 0 ? (
          <p className="mt-2 text-sm" data-testid="draft-not-comment">
            {detail.stale ? t("case.draft.stale") : t("case.draft.notComment")}
          </p>
        ) : null}
        <fieldset className="mt-3">
          <legend className="sr-only">{t("draft.choose.title")}</legend>
          <div className="space-y-2">
            {kinds.map((code) => {
              const option = options.get(code);
              return (
                <label key={code} className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="draft-kind"
                    value={code}
                    checked={kind === code}
                    onChange={() => setChosen(code)}
                    className="mt-1"
                    data-testid={`kind-${code}`}
                  />
                  <span>
                    <span className="font-medium">{option?.label ?? code}</span>
                    {code === recommended ? (
                      <span className="ml-2 rounded border border-border px-1 text-xs">
                        {t("draft.choose.recommended")}
                      </span>
                    ) : null}
                    {option?.description ? (
                      <span className="block text-text-muted">{option.description}</span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
        {requestError ? (
          <p role="alert" className="mt-3 text-sm" data-testid="draft-request-error">
            {requestError}
          </p>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={requesting || !canRequest}
            className={controlClass}
            data-testid="draft-request"
          >
            {requesting ? t("draft.requesting") : t("draft.request")}
          </button>
          {existing ? (
            <button type="button" onClick={() => setChooser(false)} className={controlClass}>
              {t("outcome.cancel")}
            </button>
          ) : null}
        </div>
        <p className="mt-4 text-sm text-text-muted">{t("draft.notice")}</p>
      </form>,
    );
  }

  if (generating) {
    return shell(
      <div role="status" aria-busy="true" data-testid="draft-generating">
        <p className="font-medium">{t("draft.generating")}</p>
        <textarea
          readOnly
          disabled
          rows={6}
          value=""
          aria-label={t("draft.label.editor")}
          className="mt-2 block w-full rounded border border-border bg-bg p-2"
        />
      </div>,
    );
  }

  const failureNote = jobFailed
    ? draftFailureMessage(job.data?.error)
    : draftError
      ? t("draft.fail.unknown")
      : null;

  if (jobFailed || draftError) {
    return shell(
      <DraftEditor
        key="manual"
        detail={detail}
        draft={null}
        responseType={kind}
        tone={tone}
        canRegenerate={!regenerated}
        regenerating={requesting}
        failureNote={failureNote}
        onRegenerate={() => void request(true)}
        onChooseOther={() => setChooser(true)}
      />,
    );
  }

  const draft = generatedDraftId !== null ? (generated.data ?? null) : existing;
  return shell(
    <>
      <DraftEditor
        key={draft?.id ?? "manual"}
        evidenceText={evidenceText}
        detail={detail}
        draft={draft}
        responseType={draft?.response_type ?? kind}
        tone={tone}
        canRegenerate={!regenerated}
        regenerating={requesting}
        failureNote={null}
        onRegenerate={() => void request(true)}
        onChooseOther={() => setChooser(true)}
      />
      {requestError ? (
        <p role="alert" className="mt-3 text-sm" data-testid="draft-request-error">
          {requestError}
        </p>
      ) : null}
    </>,
  );
}
