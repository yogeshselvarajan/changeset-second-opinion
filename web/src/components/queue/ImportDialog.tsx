import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Input, Label, TextField } from "react-aria-components";

import { importCases } from "../../api/sdk.gen";
import { t } from "../../i18n";
import { useAnnounce } from "../shell/Announcer";
import { QueueDialog, controlClass } from "./QueueDialog";
import { callApi, failureMessage, refreshQueue } from "./queueQueries";

const inputClass =
  "mt-1 block min-h-8 w-full rounded border border-control-border bg-bg px-2 text-text";

function wholeNumber(text: string): number | null {
  return /^\d{1,9}$/.test(text.trim()) ? Number(text.trim()) : null;
}

/** "Import from MapRoulette": a challenge id and a count in, `POST /cases/import` out. */
export function ImportDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [challenge, setChallenge] = useState("");
  const [limit, setLimit] = useState("50");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const challengeId = wholeNumber(challenge);
    const count = wholeNumber(limit);
    setDone(null);
    if (challengeId === null || challengeId < 1 || count === null || count < 1 || count > 100) {
      setError(t("queue.import.invalid"));
      return;
    }
    setError(null);
    setBusy(true);
    const outcome = await callApi(() =>
      importCases({
        body: { source: "maproulette", challenge_id: challengeId, limit: count },
        throwOnError: false,
      }),
    );
    setBusy(false);
    if (!outcome.ok) {
      const { failure } = outcome;
      if (failure.status === 400) setError(t("queue.import.notLive"));
      else if (failure.status === 502) setError(t("queue.import.unreachable"));
      else setError(failureMessage(failure, outcome.code));
      return;
    }
    const message = t("queue.import.done", {
      created: outcome.data.created,
      existing: outcome.data.existing,
    });
    setDone(message);
    announce(message);
    await refreshQueue(queryClient);
  }

  return (
    <QueueDialog
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={t("queue.import.title")}
    >
      <form onSubmit={submit} noValidate className="mt-3 flex flex-col gap-3">
        <TextField value={challenge} onChange={setChallenge} isInvalid={error !== null}>
          <Label>{t("queue.import.challenge")}</Label>
          {/* eslint-disable-next-line jsx-a11y/no-autofocus -- first field of a modal dialog */}
          <Input inputMode="numeric" autoComplete="off" autoFocus className={inputClass} />
        </TextField>
        <TextField value={limit} onChange={setLimit} isInvalid={error !== null}>
          <Label>{t("queue.import.limit")}</Label>
          <Input inputMode="numeric" autoComplete="off" className={inputClass} />
        </TextField>
        {error ? (
          <p role="alert" className="text-text">
            {error}
          </p>
        ) : null}
        {done ? (
          <p role="status" data-testid="import-result" className="text-text">
            {done}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          {/* After a successful import the first button reads "Close" and takes focus, so Enter
              dismisses the dialog; "Import" stays for another challenge. */}
          <button
            type="button"
            className={controlClass}
            onClick={() => onClose()}
            ref={(element) => {
              if (done) element?.focus();
            }}
          >
            {done ? t("app.close") : t("queue.add.cancel")}
          </button>
          <button type="submit" disabled={busy} className={controlClass}>
            {t("queue.import.submit")}
          </button>
        </div>
      </form>
    </QueueDialog>
  );
}
