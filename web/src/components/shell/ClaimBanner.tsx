import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { claimWorkspaceMutation, meEndpointQueryKey } from "../../api/@tanstack/react-query.gen";
import { t } from "../../i18n";
import { useMe } from "../../lib/useMe";
import { controlClass, QueueDialog } from "../queue/QueueDialog";
import { useAnnounce } from "./Announcer";

/**
 * Shown to the first person who signs in with OpenStreetMap on a workspace nobody has claimed.
 * One confirmed step makes them the admin, so a hosted copy is managed from this app and never
 * needs a command line or a server setting. The server allows it once.
 */
export function ClaimBanner() {
  const { me } = useMe();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const claim = useMutation({
    ...claimWorkspaceMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: meEndpointQueryKey() });
      announce(t("claim.done"));
      setOpen(false);
    },
    onError: () => setError(t("claim.error")),
  });

  if (!me?.can_claim) return null;
  return (
    <section
      aria-labelledby="claim-title"
      data-testid="claim-banner"
      className="cso-claim flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line px-4 py-3"
    >
      <span className="inline-grid size-9 shrink-0 place-items-center rounded-full bg-accent text-accent-fg">
        <ShieldCheck aria-hidden="true" size={18} strokeWidth={1.9} />
      </span>
      <div className="min-w-[16rem] flex-1">
        <h2 id="claim-title" className="m-0 text-base font-semibold text-ink">
          {t("claim.title")}
        </h2>
        <p className="m-0 mt-0.5 text-ink-2">{t("claim.body")}</p>
      </div>
      <button
        type="button"
        data-testid="claim-open"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
        className="btn btn-primary"
      >
        {t("claim.button")}
      </button>
      <QueueDialog isOpen={open} onOpenChange={setOpen} title={t("claim.dialogTitle")}>
        <p className="mt-2 text-ink-2">{t("claim.dialogBody")}</p>
        {error ? (
          <p
            role="alert"
            className="mt-3 rounded-[var(--radius-control)] border border-control-border bg-surface-2 p-3"
            data-testid="claim-error"
          >
            <span aria-hidden="true">⚠ </span>
            {error}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={() => setOpen(false)} className={controlClass}>
            {t("claim.cancel")}
          </button>
          <button
            type="button"
            data-testid="claim-confirm"
            disabled={claim.isPending}
            onClick={() => {
              setError(null);
              claim.mutate({});
            }}
            className="btn btn-primary disabled:opacity-60"
          >
            {claim.isPending ? t("claim.working") : t("claim.confirm")}
          </button>
        </div>
      </QueueDialog>
    </section>
  );
}
