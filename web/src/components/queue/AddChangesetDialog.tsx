import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { Input, Label, Text, TextField } from "react-aria-components";

import { createCase } from "../../api/sdk.gen";
import { t } from "../../i18n";
import { useAnnounce } from "../shell/Announcer";
import { QueueDialog, controlClass } from "./QueueDialog";
import { callApi, failureMessage, refreshQueue } from "./queueQueries";
import { parseChangesetInput } from "./search";

interface Added {
  id: number;
  created: boolean;
  caseId: string;
}

/** "Add changeset": a number or an openstreetmap.org link in, `POST /cases` out (201 new, 200 existing). */
export function AddChangesetDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState<Added | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const id = parseChangesetInput(value);
    setAdded(null);
    if (id === null) {
      setError(t("queue.add.invalid"));
      return;
    }
    setError(null);
    setBusy(true);
    const outcome = await callApi(() =>
      createCase({ body: { changeset_id: id, source: "manual" }, throwOnError: false }),
    );
    setBusy(false);
    if (!outcome.ok) {
      setError(failureMessage(outcome.failure, outcome.code));
      return;
    }
    const created = outcome.status === 201;
    setAdded({ id, created, caseId: outcome.data.case.id });
    setValue("");
    announce(t(created ? "queue.add.created" : "queue.add.existing", { id }));
    await refreshQueue(queryClient);
  }

  return (
    <QueueDialog
      isOpen
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={t("queue.add.title")}
    >
      <form onSubmit={submit} noValidate className="mt-3 flex flex-col gap-3">
        <TextField value={value} onChange={setValue} isInvalid={error !== null}>
          <Label>{t("queue.add.label")}</Label>
          <Input
            inputMode="url"
            autoComplete="off"
            // eslint-disable-next-line jsx-a11y/no-autofocus -- first field of a modal dialog
            autoFocus
            className="mt-1 block min-h-8 w-full rounded border border-control-border bg-bg px-2 text-text"
          />
          <Text slot="description" className="mt-1 block text-text-muted">
            {t("queue.add.hint")}
          </Text>
        </TextField>
        {error ? (
          <p role="alert" className="text-text">
            {error}
          </p>
        ) : null}
        {added ? (
          <p role="status" data-testid="add-result" className="text-text">
            {t(added.created ? "queue.add.created" : "queue.add.existing", { id: added.id })}{" "}
            <Link
              to="/cases/$id"
              params={{ id: added.caseId }}
              onClick={() => onClose()}
              className="underline underline-offset-4"
            >
              {t("queue.add.open")}
            </Link>
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" className={controlClass} onClick={() => onClose()}>
            {t("queue.add.cancel")}
          </button>
          <button type="submit" disabled={busy} className={controlClass}>
            {t("queue.add.submit")}
          </button>
        </div>
      </form>
    </QueueDialog>
  );
}
