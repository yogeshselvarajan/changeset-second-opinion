import { Link } from "@tanstack/react-router";

import type { WorkspaceSettings } from "../../api/types.gen";
import { t } from "../../i18n";
import { Panel } from "./parts";

/**
 * Which pack and calibration are in force. Switching a pack and refitting cut points happen on the
 * Config page, which lists every setting that would change before anything is applied; the cut
 * points never go below the floor set by parsed facts, so they have no slider here.
 */
export function ReviewTab({ settings }: { settings: WorkspaceSettings }) {
  return (
    <Panel id="settings-review" title={t("settings.tab.review")}>
      <dl className="mt-3 grid max-w-xl grid-cols-[max-content_1fr] gap-x-4 gap-y-2">
        <dt className="font-medium">{t("settings.review.pack")}</dt>
        <dd className="m-0 font-mono" data-testid="review-pack">
          {settings.active_pack ?? "-"}
        </dd>
        <dt className="font-medium">{t("settings.review.calibration")}</dt>
        <dd className="m-0" data-testid="review-calibration">
          {settings.calibration_version ?? t("settings.review.calibration.none")}
        </dd>
      </dl>
      <p className="mt-3 mb-0 max-w-xl text-ink-2">{t("settings.review.pack.note")}</p>
      <p className="mt-2 mb-0">
        <Link
          to="/config"
          className="underline underline-offset-4"
          data-testid="review-open-config"
        >
          {t("settings.review.pack.open")}
        </Link>
      </p>
      <h3 className="mt-5 mb-0 text-base font-semibold">{t("settings.review.thresholds")}</h3>
      <p className="mt-1 mb-0 max-w-xl text-ink-2">{t("settings.review.thresholds.note")}</p>
    </Panel>
  );
}
