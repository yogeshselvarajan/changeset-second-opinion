import type { WorkspaceSettings } from "../../api/types.gen";
import { t } from "../../i18n";
import { controlClass } from "../queue/QueueDialog";
import { useAnnounce } from "../shell/Announcer";
import { Panel } from "./parts";
import { exportJson } from "./settingsModel";

/** Download the settings as JSON. Built in the browser from what is on screen; no extra request. */
export function ExportTab({ settings }: { settings: WorkspaceSettings }) {
  const announce = useAnnounce();

  function download() {
    const blob = new Blob([exportJson(settings)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "settings.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    announce(t("settings.export.done"));
  }

  return (
    <Panel id="settings-export" title={t("settings.export.title")}>
      <p className="mt-2 mb-0 max-w-xl">{t("settings.export.body")}</p>
      <p className="mt-3 mb-0">
        <button type="button" className={controlClass} onClick={download} data-testid="export-run">
          {t("settings.export.action")}
        </button>
      </p>
      <p className="mt-4 mb-0 max-w-xl text-sm text-ink-2">{t("settings.export.note")}</p>
    </Panel>
  );
}
