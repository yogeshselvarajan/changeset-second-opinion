import { Info } from "lucide-react";

import { t } from "../../i18n";
import { isHostedDemo, SELF_HOST_GUIDE_PATH } from "../../landing/site";

export type Mode = "replay" | "live" | undefined;

/** Short mode badge for the top bar: glyph plus text, never colour alone. */
export function ModeBadge({ mode }: { mode: Mode }) {
  if (!mode) {
    return (
      <span className="cso-pill">
        <span aria-hidden="true">? </span>
        {t("mode.unknown")}
      </span>
    );
  }
  const glyph = mode === "replay" ? "◐" : "●";
  return (
    <span className="cso-pill" data-testid="mode-badge">
      <span aria-hidden="true">{glyph} </span>
      {mode === "replay" ? t("mode.replay") : t("mode.live")}
    </span>
  );
}

/** One plain sentence for the hosted demo, with a link to the self host guide. */
export function HostedViewOnly() {
  return (
    <>
      {" "}
      <span data-testid="hosted-view-only">{t("mode.hostedViewOnly")}</span>{" "}
      <a href={SELF_HOST_GUIDE_PATH} className="underline underline-offset-4">
        {t("mode.hostedGuide")}
      </a>
    </>
  );
}

/** Demo mode explains itself on every page: sample cases, nothing fetched, nothing posted. */
export function ModeBanner({ mode }: { mode: Mode }) {
  if (mode !== "replay") return null;
  return (
    <div
      role="note"
      data-testid="replay-banner"
      className="cso-note flex items-center gap-2 border-b border-line px-4 py-2 text-ink"
    >
      <Info aria-hidden="true" size={16} strokeWidth={1.9} className="shrink-0 text-accent" />
      <span>
        {t("mode.replayBanner")}
        {isHostedDemo() ? <HostedViewOnly /> : null}
      </span>
    </div>
  );
}
