import type { CaseDetail } from "../../api/types.gen";
import { t } from "../../i18n";

/**
 * "© OpenStreetMap contributors" for the evidence on screen. It is always shown in the case view, not
 * only while the map is open: tags, comments and counts shown here come from OpenStreetMap. The
 * server's own text wins when it sent one; otherwise the constant below stands in.
 */
export function OsmAttribution({ attribution }: { attribution: CaseDetail["attribution"] }) {
  const text = attribution?.copyright || attribution?.attribution || t("case.attribution.default");
  const license =
    attribution?.license ||
    (attribution?.copyright || attribution?.attribution ? "" : t("case.attribution.license"));
  return (
    <p className="mt-6 text-xs text-text-muted" data-testid="attribution">
      {text}
      {license ? ` · ${license}` : ""}
    </p>
  );
}
