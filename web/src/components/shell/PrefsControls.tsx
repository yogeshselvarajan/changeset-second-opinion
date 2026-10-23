import { Rows3, SunMoon } from "lucide-react";

import { t } from "../../i18n";
import type { Density, Theme } from "../../lib/prefs";
import { usePrefs } from "./PrefsContext";

/** Theme and density selects; both persist in localStorage and are applied on <html>. */
export function PrefsControls() {
  const { prefs, setTheme, setDensity } = usePrefs();

  return (
    <div className="flex items-center gap-2">
      <label className="cso-select">
        <SunMoon aria-hidden="true" size={15} strokeWidth={1.75} />
        <span className="sr-only">{t("prefs.theme")}</span>
        <select value={prefs.theme} onChange={(event) => setTheme(event.target.value as Theme)}>
          <option value="system">{t("prefs.theme.system")}</option>
          <option value="light">{t("prefs.theme.light")}</option>
          <option value="dark">{t("prefs.theme.dark")}</option>
        </select>
      </label>
      <label className="cso-select">
        <Rows3 aria-hidden="true" size={15} strokeWidth={1.75} />
        <span className="sr-only">{t("prefs.density")}</span>
        <select
          value={prefs.density}
          onChange={(event) => setDensity(event.target.value as Density)}
        >
          <option value="comfortable">{t("prefs.density.comfortable")}</option>
          <option value="compact">{t("prefs.density.compact")}</option>
        </select>
      </label>
    </div>
  );
}
