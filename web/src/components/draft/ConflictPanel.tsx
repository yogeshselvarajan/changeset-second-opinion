import { t } from "../../i18n";
import { formatDateTime } from "../case/caseModel";
import { Untrusted } from "../case/Untrusted";
import { dispositionLabel } from "./draftModel";
import type { Conflict } from "./outcomeModel";

/**
 * Shown when someone else recorded a decision first (HTTP 412). It shows that decision and lets the
 * reviewer choose: add theirs after it (a new entry; nothing is overwritten) or accept theirs.
 */
export function ConflictPanel({
  conflict,
  busy,
  onKeepMine,
  onAcceptTheirs,
}: {
  conflict: Conflict | null;
  busy: boolean;
  onKeepMine: () => void;
  onAcceptTheirs: () => void;
}) {
  const outcome = conflict?.outcome ?? null;
  return (
    <section
      role="alert"
      aria-labelledby="conflict-title"
      data-testid="outcome-conflict"
      className="mt-3 rounded border border-control-border bg-diff-changed p-3 text-sm text-text"
    >
      <h3 id="conflict-title" className="font-semibold">
        {t("outcome.conflict.title")}
      </h3>
      {outcome ? (
        <div className="mt-1" data-testid="conflict-current">
          <p>
            {t("outcome.conflict.current", {
              disposition: dispositionLabel(outcome.disposition),
              who: outcome.reviewer_display || t("case.unknown"),
              when: formatDateTime(outcome.created_at),
            })}
          </p>
          {outcome.note ? (
            <p className="mt-1">
              {t("outcome.conflict.note")} <Untrusted value={outcome.note} />
            </p>
          ) : null}
        </div>
      ) : (
        <p className="mt-1">{t("outcome.conflict.unknown")}</p>
      )}
      <p className="mt-2 text-text-muted">{t("outcome.conflict.choose")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onKeepMine}
          className="min-h-8 rounded border border-control-border bg-surface px-3"
          data-testid="conflict-keep"
        >
          {t("outcome.conflict.keep")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onAcceptTheirs}
          className="min-h-8 rounded border border-control-border bg-surface px-3"
          data-testid="conflict-accept"
        >
          {t("outcome.conflict.accept")}
        </button>
      </div>
    </section>
  );
}
