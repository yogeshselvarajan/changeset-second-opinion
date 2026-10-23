import { useEffect, useState, type Ref } from "react";
import { Button, Input, Label, SearchField } from "react-aria-components";

import type { CaseStatus } from "../../api/types.gen";
import { t, type MessageKey } from "../../i18n";
import { controlClass } from "./QueueDialog";
import { STATUSES, activeFilterCount, type QueueSearch } from "./search";

const DEBOUNCE_MS = 300;

/** A text value that follows the URL but only writes back after a short pause (or on Enter). */
function useDraft(value: string | undefined, commit: (next: string | undefined) => void) {
  const [draft, setDraft] = useState(value ?? "");
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    // The URL changed (back button, "Clear filters"): follow it. Setting state while rendering,
    // guarded like this, is the supported way to adjust state when a prop changes.
    setSeen(value);
    setDraft(value ?? "");
  }
  useEffect(() => {
    if (draft.trim() === (value ?? "")) return;
    const timer = setTimeout(() => commit(draft.trim() || undefined), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [draft, value, commit]);
  return {
    draft,
    setDraft,
    flush: () => commit(draft.trim() || undefined),
  };
}

/**
 * Search, status, editor and stale filters. Below 800 px they sit behind a "Filters" button; the
 * button and the fields are real controls, so the whole bar works from the keyboard.
 */
export function FilterBar({
  search,
  onChange,
  searchRef,
}: {
  search: QueueSearch;
  onChange: (patch: Partial<QueueSearch>) => void;
  searchRef: Ref<HTMLInputElement>;
}) {
  const [open, setOpen] = useState(false);
  const q = useDraft(search.q, (next) => onChange({ q: next }));
  const editor = useDraft(search.editor, (next) => onChange({ editor: next }));
  const active = activeFilterCount(search);
  const fieldsClass = open ? "flex" : "hidden min-[800px]:flex";

  return (
    <div className="flex flex-col gap-2 border-b border-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={q.draft}
          onChange={q.setDraft}
          onSubmit={q.flush}
          onClear={() => onChange({ q: undefined })}
          className="flex min-w-48 flex-1 items-center gap-2"
        >
          <Label className="shrink-0">{t("queue.search.label")}</Label>
          <Input
            ref={searchRef}
            placeholder={t("queue.search.placeholder")}
            aria-keyshortcuts="/"
            className="min-h-8 min-w-0 flex-1 rounded border border-control-border bg-bg px-2 text-text"
          />
          <Button
            aria-label={t("queue.search.clear")}
            className={`${controlClass} px-2 [[data-empty]_&]:hidden`}
          >
            <span aria-hidden="true">×</span>
          </Button>
        </SearchField>
        <button
          type="button"
          aria-expanded={open}
          aria-controls="queue-filter-fields"
          onClick={() => setOpen((value) => !value)}
          className={`${controlClass} min-[800px]:hidden`}
        >
          {active > 0 ? t("queue.filters.toggleCount", { n: active }) : t("queue.filters.toggle")}
        </button>
      </div>

      <div id="queue-filter-fields" className={`${fieldsClass} flex-wrap items-center gap-3`}>
        <label className="flex items-center gap-2">
          <span>{t("queue.filter.status")}</span>
          <select
            value={search.status ?? ""}
            onChange={(event) =>
              onChange({ status: (event.target.value || undefined) as CaseStatus | undefined })
            }
            className="min-h-8 rounded border border-control-border bg-bg px-2 text-text"
          >
            <option value="">{t("queue.filter.statusAny")}</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {t(`queue.status.${status}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span>{t("queue.filter.editor")}</span>
          <input
            type="text"
            value={editor.draft}
            onChange={(event) => editor.setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") editor.flush();
            }}
            className="min-h-8 w-40 rounded border border-control-border bg-bg px-2 text-text"
          />
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={search.stale === true}
            onChange={(event) => onChange({ stale: event.target.checked ? true : undefined })}
          />
          <span>{t("queue.filter.stale")}</span>
        </label>
        {active > 0 ? (
          <button
            type="button"
            onClick={() =>
              onChange({ status: undefined, editor: undefined, q: undefined, stale: undefined })
            }
            className={controlClass}
          >
            {t("queue.filter.clear")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
