import { Link } from "@tanstack/react-router";

import { t } from "../../i18n";

export type OutcomeAction = "agree" | "needs_survey" | "disagree_with_model";

const OUTCOMES: readonly { shortcut: string; disposition: OutcomeAction }[] = [
  { shortcut: "a", disposition: "agree" },
  { shortcut: "s", disposition: "needs_survey" },
  { shortcut: "x", disposition: "disagree_with_model" },
];

const OUTCOME_LABEL = {
  agree: "case.actions.agree",
  needs_survey: "case.actions.needsSurvey",
  disagree_with_model: "case.actions.disagree",
} as const;

/**
 * The reviewer's actions, pinned to the bottom of the screen. Drafting opens the draft screen and is
 * only on offer when the recommended response is a comment. Recording an outcome (agree, needs survey,
 * disagree) arrives with the draft and outcome screen, so those buttons say so and do nothing yet:
 * `onOutcome` is the one hook that screen fills in.
 */
export function ActionBar({
  caseId,
  canDraft,
  draftReason,
  onOutcome,
}: {
  caseId: string;
  canDraft: boolean;
  /** Why drafting is unavailable, when it is. */
  draftReason: string | null;
  onOutcome?: (disposition: OutcomeAction) => void;
}) {
  const enabled = Boolean(onOutcome);
  const outcomeButton = (entry: (typeof OUTCOMES)[number]) => (
    <button
      key={entry.disposition}
      type="button"
      aria-disabled={enabled ? undefined : "true"}
      onClick={() => onOutcome?.(entry.disposition)}
      className={`cso-ghostbtn text-sm ${enabled ? "" : "opacity-60"}`}
      data-testid={`action-${entry.disposition}`}
    >
      {t(OUTCOME_LABEL[entry.disposition])}{" "}
      <kbd className="ml-1 font-mono text-xs">{entry.shortcut}</kbd>
    </button>
  );
  const [agree, survey, disagree] = OUTCOMES;
  return (
    <div
      role="toolbar"
      aria-label={t("case.actions.label")}
      data-testid="action-bar"
      data-sticky-bottom
      className="cso-dock sticky bottom-0 z-30 mt-6 px-4 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        {agree ? outcomeButton(agree) : null}
        {canDraft ? (
          <Link
            to="/cases/$id/draft"
            params={{ id: caseId }}
            className="btn btn-primary min-h-8! px-4! text-sm!"
            data-testid="action-draft"
          >
            {t("case.actions.draft")} <kbd className="ml-2 font-mono text-xs">d</kbd>
          </Link>
        ) : (
          <button
            type="button"
            aria-disabled="true"
            className="cso-ghostbtn text-sm opacity-60"
            data-testid="action-draft"
          >
            {t("case.actions.draft")} <kbd className="ml-2 font-mono text-xs">d</kbd>
          </button>
        )}
        {survey ? outcomeButton(survey) : null}
        {disagree ? outcomeButton(disagree) : null}
      </div>
      {!canDraft && draftReason ? (
        <p className="mt-1 text-xs text-text-muted" data-testid="draft-reason">
          {draftReason}
        </p>
      ) : null}
      {!enabled ? (
        <p className="mt-1 text-xs text-text-muted" data-testid="outcome-later">
          {t("case.actions.outcomeLater")}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-text-muted" data-testid="key-hint">
        {t("case.keys.hint")}
      </p>
    </div>
  );
}
