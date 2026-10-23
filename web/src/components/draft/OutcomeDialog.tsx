import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Label, TextArea, TextField } from "react-aria-components";

import { getCaseOptions, getCaseQueryKey } from "../../api/@tanstack/react-query.gen";
import type { CaseDetail } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import type { OutcomeAction } from "../case/ActionBar";
import { formatDateTime } from "../case/caseModel";
import { invalidateCase } from "../case/useCaseData";
import { QueueDialog, controlClass, fieldClass } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { ConflictPanel } from "./ConflictPanel";
import { dispositionLabel } from "./draftModel";
import { submitOutcome, versionForKeepMine, type Conflict } from "./outcomeModel";

const TITLE: Record<OutcomeAction, MessageKey> = {
  agree: "outcome.title.agree",
  needs_survey: "outcome.title.needs_survey",
  disagree_with_model: "outcome.title.disagree_with_model",
};

const HINT: Record<OutcomeAction, MessageKey> = {
  agree: "outcome.hint.agree",
  needs_survey: "outcome.hint.needs_survey",
  disagree_with_model: "outcome.hint.disagree_with_model",
};

type Probe = NonNullable<NonNullable<CaseDetail["latest_run"]>["panel"]>["probes"][number];

/**
 * "Which facts were wrong?": optional. A fact the reviewer marks gets the opposite answer by
 * default (or, for an unknown reading, a choice). These only help refit cut points later; they
 * never change this run, a rule, or the decision being recorded.
 */
function WrongFacts({
  probes,
  corrections,
  onChange,
}: {
  probes: readonly Probe[];
  corrections: Record<string, "yes" | "no">;
  onChange: (next: Record<string, "yes" | "no">) => void;
}) {
  if (probes.length === 0) return null;
  const set = (id: string, value: "yes" | "no" | null) => {
    const next = { ...corrections };
    if (value === null) delete next[id];
    else next[id] = value;
    onChange(next);
  };
  return (
    <fieldset
      className="rounded-[var(--radius-pane)] border border-line p-2"
      data-testid="wrong-facts"
    >
      <legend className="px-1 text-sm font-medium">{t("outcome.wrong.title")}</legend>
      <p className="text-xs text-text-muted">{t("outcome.wrong.hint")}</p>
      <ul className="mt-1 space-y-1">
        {probes.map((probe) => {
          const marked = probe.id in corrections;
          return (
            <li key={probe.id} className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={marked}
                  onChange={(event) => {
                    if (!event.target.checked) return set(probe.id, null);
                    set(probe.id, probe.reading === "yes" ? "no" : "yes");
                  }}
                  data-testid={`wrong-${probe.id}`}
                />
                <span>
                  {probe.label}{" "}
                  <span className="text-text-muted">
                    {t("outcome.wrong.read", { reading: t(`case.reading.${probe.reading}`) })}
                  </span>
                </span>
              </label>
              {marked && probe.reading === "unknown" ? (
                <select
                  aria-label={t("outcome.wrong.right", { label: probe.label })}
                  value={corrections[probe.id]}
                  onChange={(event) => set(probe.id, event.target.value as "yes" | "no")}
                  className="min-h-7 rounded-[var(--radius-control)] border border-control-border bg-surface px-1"
                >
                  <option value="yes">{t("case.reading.yes")}</option>
                  <option value="no">{t("case.reading.no")}</option>
                </select>
              ) : null}
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

/**
 * A small confirm dialog for recording an outcome without a draft (`a`, `s`, `x`). The record is
 * append-only; `If-Match` carries the outcome version the reviewer saw, and a 412 shows the other
 * reviewer's decision instead of overwriting it.
 */
export function OutcomeDialog({
  detail,
  disposition,
  onClose,
}: {
  detail: CaseDetail;
  disposition: OutcomeAction;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [note, setNote] = useState("");
  // Facts the reviewer marks as wrong on a disagreement, each with the answer they say is right.
  const [corrections, setCorrections] = useState<Record<string, "yes" | "no">>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ value: Conflict | null } | null>(null);
  const version = useRef<number | null | undefined>(detail.outcome_version);
  const inFlight = useRef(false);
  const run = detail.latest_run;

  async function record() {
    if (inFlight.current || !run) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    const result = await submitOutcome({
      caseId: detail.id,
      version: version.current,
      input: {
        disposition,
        response_type: disposition === "agree" ? (detail.response ?? null) : null,
        note: note.trim() === "" ? null : note.trim(),
        run_id_seen: run.id,
        ...(disposition === "disagree_with_model" && Object.keys(corrections).length > 0
          ? { probe_corrections: corrections }
          : {}),
      },
    });
    inFlight.current = false;
    setBusy(false);
    if (result.kind === "ok") {
      queryClient.setQueryData(getCaseQueryKey({ path: { id: detail.id } }), result.detail);
      void invalidateCase(queryClient, detail.id);
      announce(t("outcome.recorded", { disposition: dispositionLabel(disposition) }));
      onClose();
      return;
    }
    if (result.kind === "conflict") {
      setConflict({ value: result.conflict });
      return;
    }
    setError(result.failure.message);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void record();
  }

  async function keepMine() {
    // The reviewer has now seen the other decision, so their entry goes in after it. Without the
    // other decision's version in the 412, the latest one is fetched; resending the stale one loops.
    const next = await versionForKeepMine(conflict?.value, async () => {
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
    void record();
  }

  function acceptTheirs() {
    void invalidateCase(queryClient, detail.id);
    announce(t("outcome.conflict.accepted"));
    onClose();
  }

  const latest = detail.latest_outcome_detail;
  return (
    <QueueDialog
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={t(TITLE[disposition])}
    >
      <form
        onSubmit={onSubmit}
        noValidate
        className="mt-3 flex flex-col gap-3"
        data-testid="outcome-form"
      >
        <p className="text-sm text-text-muted">{t(HINT[disposition])}</p>
        {latest ? (
          <p className="text-sm" data-testid="outcome-latest">
            {t("outcome.latest", {
              disposition: dispositionLabel(latest.disposition),
              who: latest.reviewer_display,
              when: formatDateTime(latest.created_at),
            })}
          </p>
        ) : null}
        {disposition === "disagree_with_model" ? (
          <WrongFacts
            probes={(run?.panel?.probes ?? []).filter((probe) => probe.use === "composed")}
            corrections={corrections}
            onChange={setCorrections}
          />
        ) : null}
        <TextField value={note} onChange={setNote}>
          <Label className="text-sm font-medium">{t("outcome.note.label")}</Label>
          <TextArea rows={3} className={fieldClass} data-testid="outcome-note" />
        </TextField>
        <p className="text-xs text-text-muted">{t("outcome.appendOnly")}</p>
        {conflict ? (
          <ConflictPanel
            conflict={conflict.value}
            busy={busy}
            onKeepMine={keepMine}
            onAcceptTheirs={acceptTheirs}
          />
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-text" data-testid="outcome-error">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className={controlClass}
            data-testid="outcome-cancel"
          >
            {t("outcome.cancel")}
          </button>
          <button
            type="submit"
            disabled={busy || !run || conflict !== null}
            className={controlClass}
            data-testid="outcome-confirm"
          >
            {busy ? t("outcome.recording") : t("outcome.confirm")}
          </button>
        </div>
      </form>
    </QueueDialog>
  );
}
