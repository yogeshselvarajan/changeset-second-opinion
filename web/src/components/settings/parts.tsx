import type { ReactNode } from "react";

import { t } from "../../i18n";
import { controlClass } from "../queue/QueueDialog";

export const inputClass =
  "mt-1 block min-h-9 w-full rounded-[var(--radius-control)] border border-control-border bg-surface px-3 text-ink";

interface ControlProps {
  id: string;
  "aria-describedby": string;
  "aria-invalid"?: true;
}

/** A labelled control with a hint under it and the server's messages for it, if there are any. */
export function Field({
  id,
  label,
  hint,
  errors,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  errors?: readonly string[];
  children: (props: ControlProps) => ReactNode;
}) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const failed = (errors?.length ?? 0) > 0;
  const describedBy = [hint ? hintId : null, failed ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="mt-4" data-field={id}>
      <label htmlFor={id} className="block font-medium text-ink">
        {label}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        ...(failed ? { "aria-invalid": true as const } : {}),
      })}
      {hint ? (
        <p id={hintId} className="mt-1 mb-0 text-xs text-ink-2">
          {hint}
        </p>
      ) : null}
      {failed ? (
        <ul
          id={errorId}
          className="mt-1 mb-0 list-none space-y-0.5 p-0 text-sm text-ink"
          data-testid={`${id}-error`}
        >
          {errors?.map((message) => (
            <li key={message}>
              <span aria-hidden="true">⚠ </span>
              {message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Shown when a save met a newer version: nothing was saved, and reloading shows the other one. */
export function ConflictNotice({ onReload }: { onReload: () => void }) {
  return (
    <div
      role="alert"
      className="mt-4 rounded-[var(--radius-pane)] border border-control-border bg-surface p-3"
      data-testid="settings-conflict"
    >
      <p className="m-0">
        <span aria-hidden="true">⚠ </span>
        {t("settings.conflict")}
      </p>
      <button
        type="button"
        className={`${controlClass} mt-2`}
        onClick={onReload}
        data-testid="settings-reload"
      >
        {t("settings.conflict.reload")}
      </button>
    </div>
  );
}

export function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-title`} className="cso-card mt-4" data-testid={id}>
      <h2 id={`${id}-title`} className="m-0 text-lg font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}
