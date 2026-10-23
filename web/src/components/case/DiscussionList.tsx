import type { DiscussionEntry, FetchStatus } from "../../api/types.gen";
import { t } from "../../i18n";
import { formatDateTime } from "./caseModel";
import { Section } from "./Section";
import { Untrusted } from "./Untrusted";

/**
 * What mappers wrote on the changeset. The text is data: it is shown as plain text, so an instruction
 * in it is just words on the screen, and any link in it is not a link.
 */
export function DiscussionList({
  entries,
  status,
}: {
  entries: readonly DiscussionEntry[];
  status: FetchStatus | undefined;
}) {
  return (
    <Section
      id="discussion"
      title={t("case.discussion.title", { n: entries.length })}
      testId="discussion"
    >
      {status === "failed" ? (
        <p role="note" className="text-sm">
          {t("case.discussion.failed")}
        </p>
      ) : null}
      {entries.length === 0 ? (
        <p className="text-sm text-text-muted">{t("case.discussion.empty")}</p>
      ) : (
        <ol className="space-y-3">
          {entries.map((entry) => (
            <li key={entry.id} className="rounded border border-border p-2" data-entry={entry.id}>
              <p className="text-xs text-text-muted">
                <Untrusted value={entry.author_display} /> · {formatDateTime(entry.date)}
              </p>
              <Untrusted value={entry.text} block className="mt-1 text-sm" />
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
