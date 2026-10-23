import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { getCaseOptions, getCaseQueryKey } from "../../api/@tanstack/react-query.gen";
import type { CaseDetail, Draft, Response } from "../../api/types.gen";
import { t } from "../../i18n";
import { isTypingTarget } from "../../lib/hotkeys";
import { optionLookup, invalidateCase, useConfig } from "../case/useCaseData";
import { osmChangesetUrl } from "../case/caseModel";
import { useAnnounce } from "../shell/Announcer";
import { controlClass } from "../queue/QueueDialog";
import { Untrusted } from "../case/Untrusted";
import { copyText } from "./clipboard";
import { citedEvidenceLines } from "./citedLines";
import { openPendingTab, type PendingTab } from "./pendingTab";
import { ConflictPanel } from "./ConflictPanel";
import {
  CHECK_LABEL,
  DRAFT_STATUS_LABEL,
  editStorageKey,
  isTemplateDraft,
  violationMessage,
} from "./draftModel";
import { LIMITS, allOk, countWords, joinParts, runChecks, type ToneRules } from "./draftChecks";
import {
  REJECT_REASONS,
  approveDisposition,
  rejectDisposition,
  submitOutcome,
  versionForKeepMine,
  type Conflict,
  type RejectReason,
} from "./outcomeModel";
import { hasChanges, wordDiff } from "./wordDiff";

type Intent = "copy" | "open" | "reject";

function readSaved(key: string | null): string | null {
  if (!key) return null;
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSaved(key: string | null, value: string | null): void {
  if (!key) return;
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    // storage can be unavailable; the draft then simply is not kept across a reload
  }
}

/**
 * The draft as an editable text with a live checklist. Nothing here posts anywhere: approving
 * records the decision (append-only, `If-Match` sent) and copies the text, and a link opens the
 * changeset page for the reviewer to paste into themselves.
 */
export function DraftEditor({
  detail,
  draft,
  responseType,
  tone,
  canRegenerate,
  regenerating,
  failureNote,
  onRegenerate,
  onChooseOther,
  evidenceText,
}: {
  /** The evidence text the model saw; the lines a draft cites are shown beside the checklist. */
  evidenceText?: string;
  detail: CaseDetail;
  /** The generated draft, or null when the reviewer writes one by hand. */
  draft: Draft | null;
  responseType: Response;
  tone: ToneRules;
  canRegenerate: boolean;
  regenerating: boolean;
  failureNote: string | null;
  onRegenerate: () => void;
  onChooseOther: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const announce = useAnnounce();
  const config = useConfig();
  const storageKey = draft ? editStorageKey(draft.id) : null;
  const generated = useMemo(() => (draft ? joinParts(draft) : ""), [draft]);
  const [text, setText] = useState(() => readSaved(storageKey) ?? generated);
  const [showDiff, setShowDiff] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ value: Conflict | null; intent: Intent } | null>(null);
  const [recorded, setRecorded] = useState<{ copied: boolean; final: string } | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState<RejectReason | "">("");
  const [rejectNote, setRejectNote] = useState("");
  const [reasonMissing, setReasonMissing] = useState(false);
  const version = useRef<number | null | undefined>(detail.outcome_version);
  const inFlight = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const run = detail.latest_run;
  const checks = useMemo(() => runChecks(text, tone, responseType), [text, tone, responseType]);
  const checksOk = allOk(checks);
  const trimmed = text.trim();
  const diff = useMemo(() => wordDiff(generated, text), [generated, text]);
  const changed = hasChanges(diff);
  const citedLines = useMemo(
    () => citedEvidenceLines(evidenceText, draft?.cited_evidence_ids),
    [evidenceText, draft?.cited_evidence_ids],
  );
  const url = osmChangesetUrl(detail.changeset_id);
  const responseLabel =
    optionLookup(config.data?.option_sets.response).get(responseType)?.label ?? responseType;
  const locked = busy || recorded !== null || regenerating;

  function edit(next: string) {
    setText(next);
    writeSaved(storageKey, next === generated ? null : next);
  }

  async function record(intent: Intent) {
    if (inFlight.current || recorded || !run) return;
    if (intent === "reject") {
      if (reason === "") {
        setReasonMissing(true);
        announce(t("draft.reject.needReason"));
        return;
      }
    } else {
      if (trimmed === "") return announce(t("draft.error.empty"));
      if (!checksOk) {
        announce(t("draft.error.checks"));
        return;
      }
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    // Opened here, inside the click, so a popup blocker lets it through; it is pointed at the
    // changeset after the outcome is recorded and closed otherwise.
    const tab: PendingTab | null = intent === "open" && url ? openPendingTab() : null;
    const runId = draft?.run_id ?? run.id;
    const result = await submitOutcome({
      caseId: detail.id,
      version: version.current,
      input:
        intent === "reject"
          ? {
              disposition: rejectDisposition(reason as RejectReason),
              response_type: responseType,
              reason_code: reason,
              note: rejectNote.trim() === "" ? null : rejectNote.trim(),
              run_id_seen: runId,
            }
          : {
              disposition: approveDisposition(responseType, detail.response),
              response_type: responseType,
              final_text: trimmed,
              run_id_seen: runId,
            },
    });
    if (result.kind === "ok") {
      queryClient.setQueryData(getCaseQueryKey({ path: { id: detail.id } }), result.detail);
      void invalidateCase(queryClient, detail.id);
      writeSaved(storageKey, null);
      if (intent === "reject") {
        setRecorded({ copied: false, final: "" });
        announce(t("draft.rejected"));
      } else {
        const copied = await copyText(trimmed);
        if (url) tab?.go(url);
        setRecorded({ copied, final: trimmed });
        announce(t(copied ? "draft.copied" : "draft.copyFailed"));
      }
    } else if (result.kind === "conflict") {
      tab?.close();
      setConflict({ value: result.conflict, intent });
    } else {
      tab?.close();
      setError(result.failure.message);
    }
    inFlight.current = false;
    setBusy(false);
  }

  // When the editor appears, put the cursor in the text so a keyboard user can start typing.
  useEffect(() => {
    textarea.current?.focus();
  }, []);

  const latest = useRef({ record, rejectOpen, canRegenerate, locked, onRegenerate, conflict });
  useEffect(() => {
    latest.current = { record, rejectOpen, canRegenerate, locked, onRegenerate, conflict };
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const state = latest.current;
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        void state.record(event.shiftKey ? "open" : "copy");
        return;
      }
      if (event.key === "Escape") {
        if (state.rejectOpen) {
          setRejectOpen(false);
          return;
        }
        void navigate({ to: "/cases/$id", params: { id: detail.id } });
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) return;
      if (event.key === "g") {
        if (state.canRegenerate && !state.locked) state.onRegenerate();
        else announce(t("draft.regenerate.unavailable"));
      } else if (event.key === "r" && !state.locked) {
        setRejectOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [announce, detail.id, navigate]);

  async function keepMine() {
    if (!conflict) return;
    const intent = conflict.intent;
    // The reviewer has now seen the other decision, so their entry goes in after it. Without the
    // other decision's version in the 412, the latest one is fetched; resending the stale one loops.
    const next = await versionForKeepMine(conflict.value, async () => {
      const latest = await queryClient.fetchQuery({
        ...getCaseOptions({ path: { id: detail.id } }),
        staleTime: 0,
      });
      return latest.outcome_version ?? 0;
    });
    if (!next) {
      setError(t("outcome.conflict.refetchFailed"));
      return;
    }
    version.current = next.version;
    setConflict(null);
    void record(intent);
  }

  function acceptTheirs() {
    void invalidateCase(queryClient, detail.id);
    announce(t("outcome.conflict.accepted"));
    void navigate({ to: "/cases/$id", params: { id: detail.id } });
  }

  const template = draft ? isTemplateDraft(draft.status, draft.model_id) : false;
  const words = countWords(text);

  return (
    <div data-testid="draft-editor">
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="draft-provenance">
        <span className="rounded border border-border px-2 py-0.5" data-testid="draft-kind">
          {responseLabel}
        </span>
        {draft ? (
          <>
            {template ? (
              <span
                className="rounded border border-control-border bg-diff-changed px-2 py-0.5"
                data-testid="draft-badge-template"
              >
                {t("draft.badge.template")}
              </span>
            ) : (
              <span
                className="rounded border border-border px-2 py-0.5"
                data-testid="draft-badge-model"
              >
                {t("draft.badge.model")}
              </span>
            )}
            <span className="text-text-muted" data-testid="draft-model">
              {draft.model_id ?? t("draft.noModel")} · {t(DRAFT_STATUS_LABEL[draft.status])}
            </span>
          </>
        ) : (
          <span
            className="rounded border border-border px-2 py-0.5"
            data-testid="draft-badge-manual"
          >
            {t("draft.badge.manual")}
          </span>
        )}
      </div>
      {draft && template ? (
        <p className="mt-1 text-xs text-text-muted">{t("draft.badge.template.note")}</p>
      ) : null}
      {failureNote ? (
        <p role="status" className="mt-2 text-sm" data-testid="draft-failure">
          {failureNote} {t("draft.fail.manual")}
        </p>
      ) : null}

      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div>
          <label htmlFor="draft-text" className="text-sm font-medium">
            {t("draft.label.editor")}
          </label>
          <textarea
            id="draft-text"
            ref={textarea}
            value={text}
            onChange={(event) => edit(event.target.value)}
            readOnly={locked}
            rows={10}
            aria-describedby="draft-counts draft-notice"
            className="mt-1 block min-h-40 w-full rounded border border-control-border bg-bg p-2 text-text"
            data-testid="draft-text"
            spellCheck
          />
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-text-muted">
            <span id="draft-counts" data-testid="draft-counts">
              {t("draft.counts", { chars: text.length, words })}
            </span>
            <span>
              {t("draft.limits", { greeting: LIMITS.greetingChars, body: LIMITS.bodyChars })}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={locked || text === generated}
              onClick={() => edit(generated)}
              className={controlClass}
              data-testid="draft-reset"
            >
              {t("draft.reset")}
            </button>
            <button
              type="button"
              disabled={locked || !canRegenerate}
              onClick={onRegenerate}
              className={controlClass}
              data-testid="draft-regenerate"
            >
              {canRegenerate ? t("draft.regenerate") : t("draft.regenerate.used")}{" "}
              <kbd className="ml-1 font-mono text-xs">g</kbd>
            </button>
            <button
              type="button"
              disabled={locked}
              onClick={onChooseOther}
              className={controlClass}
              data-testid="draft-other-kind"
            >
              {t("draft.otherKind")}
            </button>
            {draft ? (
              <button
                type="button"
                aria-pressed={showDiff}
                onClick={() => setShowDiff((value) => !value)}
                className={controlClass}
                data-testid="draft-diff-toggle"
              >
                {showDiff ? t("draft.diff.hide") : t("draft.diff.show")}
              </button>
            ) : null}
          </div>
          {showDiff && draft ? (
            <div className="mt-2 rounded border border-border p-2 text-sm" data-testid="draft-diff">
              <h3 className="text-xs font-semibold text-text-muted">{t("draft.diff.title")}</h3>
              {changed ? (
                <p className="mt-1 whitespace-pre-wrap break-words">
                  {diff.map((run, index) =>
                    run.kind === "same" ? (
                      <span key={index}>{run.text}</span>
                    ) : run.kind === "ins" ? (
                      <ins key={index} className="bg-diff-added no-underline">
                        <span aria-hidden="true">+</span>
                        <span className="sr-only">{t("draft.diff.added")}</span>
                        {run.text}
                      </ins>
                    ) : (
                      <del key={index} className="bg-diff-removed">
                        <span aria-hidden="true">−</span>
                        <span className="sr-only">{t("draft.diff.removed")}</span>
                        {run.text}
                      </del>
                    ),
                  )}
                </p>
              ) : (
                <p className="mt-1 text-text-muted">{t("draft.diff.none")}</p>
              )}
            </div>
          ) : null}
        </div>

        <aside aria-labelledby="draft-checklist-title" data-testid="draft-checklist">
          <h2 id="draft-checklist-title" className="text-sm font-semibold">
            {t("draft.checklist.title")}
          </h2>
          <ul className="mt-1 space-y-1 text-sm">
            {checks
              .filter((check) => check.applies)
              .map((check) => (
                <li
                  key={check.id}
                  data-check={check.id}
                  data-ok={check.ok ? "true" : "false"}
                  className="flex gap-2"
                >
                  <span aria-hidden="true">{check.ok ? "✓" : "✗"}</span>
                  <span>
                    <span className="sr-only">
                      {check.ok ? t("draft.check.passed") : t("draft.check.failed")}{" "}
                    </span>
                    {t(CHECK_LABEL[check.id])}
                    {check.lines.length > 0
                      ? ` ${t("draft.check.onLines", { lines: check.lines.join(", ") })}`
                      : ""}
                  </span>
                </li>
              ))}
          </ul>
          <p
            className="mt-2 text-sm"
            role="status"
            aria-live="polite"
            data-testid="draft-checks-summary"
          >
            {checksOk ? t("draft.checks.ok") : t("draft.checks.notOk")}
          </p>
          {draft ? (
            <div className="mt-3 text-sm" data-testid="draft-server-validation">
              <h3 className="font-semibold">{t("draft.server.title")}</h3>
              {draft.validation.ok ? (
                <p>{t("draft.server.ok")}</p>
              ) : (
                <>
                  <p>{t("draft.server.notOk")}</p>
                  <ul className="list-disc pl-5">
                    {(draft.validation.violations ?? []).map((code) => (
                      <li key={code}>{violationMessage(code)}</li>
                    ))}
                  </ul>
                </>
              )}
              {draft.cited_evidence_ids && draft.cited_evidence_ids.length > 0 ? (
                <>
                  <p className="mt-1" data-testid="draft-cites">
                    {t("draft.cites", { ids: draft.cited_evidence_ids.join(", ") })}
                  </p>
                  {citedLines.length > 0 ? (
                    <ul
                      aria-label={t("draft.citedLines")}
                      className="mt-2 space-y-1.5 rounded-[var(--radius-pane)] border border-line bg-surface p-2 text-xs"
                      data-testid="draft-cited-lines"
                    >
                      {citedLines.map((cited) => (
                        <li key={cited.id} className="flex gap-2">
                          <code className="shrink-0 font-mono text-ink-2">{cited.id}</code>
                          <Untrusted value={cited.line.slice(cited.id.length + 1)} />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </aside>
      </div>

      {conflict ? (
        <ConflictPanel
          conflict={conflict.value}
          busy={busy}
          onKeepMine={keepMine}
          onAcceptTheirs={acceptTheirs}
        />
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm" data-testid="draft-error">
          {error}
        </p>
      ) : null}

      {recorded ? (
        <section
          role="status"
          aria-labelledby="draft-recorded-title"
          className="mt-4 rounded border border-control-border p-3 text-sm"
          data-testid="draft-recorded"
        >
          <h2 id="draft-recorded-title" className="font-semibold">
            {t("draft.recorded.title")}
          </h2>
          <p className="mt-1">
            {recorded.final === ""
              ? t("draft.recorded.rejected")
              : recorded.copied
                ? t("draft.copied")
                : t("draft.copyFailed")}
          </p>
          {recorded.final !== "" && !recorded.copied ? (
            <textarea
              readOnly
              rows={6}
              value={recorded.final}
              aria-label={t("draft.recorded.finalLabel")}
              className="mt-2 block w-full rounded border border-control-border bg-bg p-2"
              data-testid="draft-final-text"
              onFocus={(event) => event.currentTarget.select()}
            />
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2">
            {recorded.final !== "" ? (
              <button
                type="button"
                className={controlClass}
                onClick={async () => {
                  const ok = await copyText(recorded.final);
                  announce(t(ok ? "draft.copied" : "draft.copyFailed"));
                }}
                data-testid="draft-copy-again"
              >
                {t("draft.copyAgain")}
              </button>
            ) : null}
            {url && recorded.final !== "" ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-8 items-center rounded border border-control-border px-3 underline"
                data-testid="draft-open-link"
              >
                {t("draft.openLink")}
              </a>
            ) : null}
            <Link
              to="/cases/$id"
              params={{ id: detail.id }}
              className="inline-flex min-h-8 items-center rounded border border-control-border px-3 underline"
              data-testid="draft-back-case"
            >
              {t("draft.back")}
            </Link>
          </div>
        </section>
      ) : (
        <div className="mt-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label={t("draft.actions.label")}>
            <button
              type="button"
              disabled={locked || trimmed === ""}
              aria-disabled={!checksOk ? "true" : undefined}
              onClick={() => void record("copy")}
              className={controlClass}
              data-testid="approve-copy"
            >
              {t("draft.approveCopy")} <kbd className="ml-1 font-mono text-xs">Ctrl+Enter</kbd>
            </button>
            <button
              type="button"
              disabled={locked || trimmed === "" || !url}
              aria-disabled={!checksOk ? "true" : undefined}
              onClick={() => void record("open")}
              className={controlClass}
              data-testid="approve-open"
            >
              {t("draft.approveOpen")}{" "}
              <kbd className="ml-1 font-mono text-xs">Ctrl+Shift+Enter</kbd>
            </button>
            <button
              type="button"
              disabled={locked}
              aria-expanded={rejectOpen}
              aria-controls="draft-reject-panel"
              onClick={() => setRejectOpen((open) => !open)}
              className={controlClass}
              data-testid="reject-open"
            >
              {t("draft.reject")} <kbd className="ml-1 font-mono text-xs">r</kbd>
            </button>
          </div>
          {rejectOpen ? (
            <form
              id="draft-reject-panel"
              onSubmit={(event) => {
                event.preventDefault();
                void record("reject");
              }}
              className="mt-3 max-w-md rounded border border-border p-3 text-sm"
              data-testid="reject-panel"
            >
              <label htmlFor="reject-reason" className="font-medium">
                {t("draft.reject.reason")}
              </label>
              <select
                id="reject-reason"
                value={reason}
                aria-invalid={reasonMissing && reason === "" ? "true" : undefined}
                aria-describedby={
                  reasonMissing && reason === "" ? "reject-reason-error" : undefined
                }
                onChange={(event) => {
                  setReason(event.target.value as RejectReason | "");
                  setReasonMissing(false);
                }}
                className="mt-1 block min-h-8 w-full rounded border border-control-border bg-bg px-2"
                data-testid="reject-reason"
              >
                <option value="">{t("draft.reject.choose")}</option>
                {REJECT_REASONS.map((code) => (
                  <option key={code} value={code}>
                    {t(`draft.reject.reason.${code}`)}
                  </option>
                ))}
              </select>
              {reasonMissing && reason === "" ? (
                <p
                  id="reject-reason-error"
                  role="alert"
                  className="mt-1"
                  data-testid="reject-reason-error"
                >
                  {t("draft.reject.needReason")}
                </p>
              ) : null}
              <label htmlFor="reject-note" className="mt-2 block font-medium">
                {t("outcome.note.label")}
              </label>
              <textarea
                id="reject-note"
                value={rejectNote}
                onChange={(event) => setRejectNote(event.target.value)}
                rows={2}
                className="mt-1 block w-full rounded border border-control-border bg-bg p-2"
              />
              <div className="mt-2 flex gap-2">
                <button
                  type="submit"
                  disabled={locked}
                  className={controlClass}
                  data-testid="reject-confirm"
                >
                  {t("draft.reject.confirm")}
                </button>
                <button
                  type="button"
                  onClick={() => setRejectOpen(false)}
                  className={controlClass}
                  data-testid="reject-cancel"
                >
                  {t("outcome.cancel")}
                </button>
              </div>
            </form>
          ) : null}
        </div>
      )}
      <p
        id="draft-notice"
        className="sticky bottom-[var(--bottom-bar-h)] z-10 mt-4 border-t border-line bg-canvas py-2 text-sm text-text-muted"
        data-testid="draft-notice"
      >
        ⓘ {t("draft.notice")}
      </p>
    </div>
  );
}
