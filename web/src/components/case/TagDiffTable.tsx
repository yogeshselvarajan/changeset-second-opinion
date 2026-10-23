import { t } from "../../i18n";
import { diffMeta, type DiffGroup } from "./caseModel";
import { ScrollRegion } from "./ScrollRegion";
import { Section } from "./Section";
import { Untrusted } from "./Untrusted";

export type DiffMode = "side" | "unified";

const TONE_CLASS = {
  added: "bg-[var(--color-diff-added)]",
  removed: "bg-[var(--color-diff-removed)]",
  changed: "bg-[var(--color-diff-changed)]",
} as const;

function Value({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) {
    return <span className="text-text-muted">{t("case.diff.none")}</span>;
  }
  return <Untrusted value={value} className="font-mono text-xs" />;
}

/**
 * The tag changes the API reported, per element. The table never works out a difference itself: each
 * row is one `TagDiff` as given. A row's state is a glyph and a word, so colour is never the only cue.
 */
export function TagDiffTable({
  groups,
  mode,
  onModeChange,
  idLabels,
  detailed,
  total,
}: {
  groups: readonly DiffGroup[];
  mode: DiffMode;
  onModeChange: (mode: DiffMode) => void;
  idLabels: ReadonlyMap<string, string>;
  detailed: number;
  total: number;
}) {
  const rowCount = groups.reduce((sum, group) => sum + group.rows.length, 0);
  return (
    <Section
      id="diffs"
      title={t("case.diff.title", { detailed, total })}
      testId="diffs"
      actions={
        <div role="group" aria-label={t("case.diff.modeLabel")} className="flex gap-1">
          {(["side", "unified"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={mode === option}
              onClick={() => onModeChange(option)}
              className="min-h-8 rounded border border-control-border px-2 text-xs aria-pressed:font-semibold aria-pressed:underline"
            >
              {t(option === "side" ? "case.diff.sideBySide" : "case.diff.unified")}
            </button>
          ))}
        </div>
      }
    >
      {rowCount === 0 ? (
        <p className="text-sm text-text-muted" data-testid="diff-empty">
          {t("case.diff.empty")}
        </p>
      ) : (
        <ScrollRegion label={t("case.diff.caption")}>
          <table
            className="w-full min-w-[28rem] border-collapse text-left text-sm"
            data-mode={mode}
          >
            <caption className="sr-only">{t("case.diff.caption")}</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.diff.colChange")}
                </th>
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.diff.colKey")}
                </th>
                {mode === "side" ? (
                  <>
                    <th scope="col" className="px-2 py-1 font-semibold">
                      {t("case.diff.colBefore")}
                    </th>
                    <th scope="col" className="px-2 py-1 font-semibold">
                      {t("case.diff.colAfter")}
                    </th>
                  </>
                ) : (
                  <th scope="col" className="px-2 py-1 font-semibold">
                    {t("case.diff.colLines")}
                  </th>
                )}
              </tr>
            </thead>
            {groups.map((group) => {
              const label = idLabels.get(group.key);
              return (
                <tbody key={group.key} data-element={group.key}>
                  <tr className="border-t border-border bg-surface">
                    <th
                      scope="rowgroup"
                      colSpan={mode === "side" ? 4 : 3}
                      className="px-2 py-1 font-mono text-xs"
                    >
                      {group.key}
                      {label ? (
                        <span className="ml-2 font-sans text-text-muted">{label}</span>
                      ) : null}
                    </th>
                  </tr>
                  {group.rows.map((row) => {
                    const meta = diffMeta(row.change);
                    return (
                      <tr
                        key={`${row.key}/${row.change}`}
                        className={TONE_CLASS[meta.tone]}
                        data-change={row.change}
                      >
                        <td className="whitespace-nowrap px-2 py-1">
                          <span aria-hidden="true" className="mr-1 font-mono">
                            {meta.prefix}
                          </span>
                          {t(meta.label)}
                        </td>
                        <th scope="row" className="px-2 py-1 font-mono text-xs font-normal">
                          <Untrusted value={row.key} />
                        </th>
                        {mode === "side" ? (
                          <>
                            <td className="px-2 py-1">
                              <Value value={row.before} />
                            </td>
                            <td className="px-2 py-1">
                              <Value value={row.after} />
                            </td>
                          </>
                        ) : (
                          <td className="px-2 py-1">
                            {row.before !== null && row.before !== undefined ? (
                              <div>
                                <span aria-hidden="true" className="mr-1 font-mono">
                                  −
                                </span>
                                <span className="sr-only">{t("case.diff.colBefore")}: </span>
                                <Value value={row.before} />
                              </div>
                            ) : null}
                            {row.after !== null && row.after !== undefined ? (
                              <div>
                                <span aria-hidden="true" className="mr-1 font-mono">
                                  +
                                </span>
                                <span className="sr-only">{t("case.diff.colAfter")}: </span>
                                <Value value={row.after} />
                              </div>
                            ) : null}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              );
            })}
          </table>
        </ScrollRegion>
      )}
      {total > detailed ? (
        <p className="mt-2 text-xs text-text-muted" data-testid="diff-unavailable">
          {t("case.diff.unavailable", { n: total - detailed })}
        </p>
      ) : null}
    </Section>
  );
}
