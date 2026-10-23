import type { ReactNode } from "react";

import { t } from "../../i18n";
import { useMe } from "../../lib/useMe";
import { ClaimBanner } from "./ClaimBanner";
import { ModeBanner } from "./ModeBanner";
import { Rail } from "./Rail";
import { TopStrip } from "./TopStrip";

/**
 * Three zones: a rail on the left, a quiet strip on top, the content below it. The skip link and
 * the `<main>` landmark live here so every route keeps them.
 */
export function AppFrame({ onHelp, children }: { onHelp: () => void; children: ReactNode }) {
  const { me } = useMe();
  return (
    <div className="cso-frame bg-canvas text-ink">
      <a href="#main" className="skip-link">
        {t("app.skipToMain")}
      </a>
      <Rail onHelp={onHelp} />
      <div className="cso-column">
        <TopStrip />
        <ClaimBanner />
        <ModeBanner mode={me?.mode} />
        <main id="main" tabIndex={-1} className="cso-main min-h-[60vh] outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}
