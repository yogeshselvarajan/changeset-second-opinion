import type { ChangedElement } from "../../api/types.gen";
import { t } from "../../i18n";
import {
  ACTION_GLYPH,
  ACTION_LABEL,
  AGE_BUCKET_LABEL,
  ageBucket,
  elementKey,
  formatAge,
} from "./caseModel";
import { ScrollRegion } from "./ScrollRegion";
import { Section } from "./Section";

function geometryText(object: ChangedElement): string | null {
  const g = object.geometry_change;
  if (!g) return null;
  const parts: string[] = [];
  if (g.node_moved_m !== null && g.node_moved_m !== undefined) {
    parts.push(t("case.objects.moved", { m: Math.round(g.node_moved_m) }));
  }
  if (g.way_node_delta !== null && g.way_node_delta !== undefined && g.way_node_delta !== 0) {
    parts.push(t("case.objects.nodeDelta", { n: g.way_node_delta }));
  }
  return parts.length > 0 ? parts.join(", ") : null;
}

/** The elements with details, in the order the API gave, each with its evidence id when known. */
export function ChangedObjectsList({
  elements,
  idLabels,
  total,
}: {
  elements: readonly ChangedElement[];
  idLabels: ReadonlyMap<string, string>;
  total: number;
}) {
  return (
    <Section
      id="objects"
      title={t("case.objects.title", { shown: elements.length, total })}
      testId="objects"
    >
      {elements.length === 0 ? (
        <p className="text-sm text-text-muted">{t("case.objects.empty")}</p>
      ) : (
        <ScrollRegion label={t("case.objects.caption")}>
          <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
            <caption className="sr-only">{t("case.objects.caption")}</caption>
            <thead>
              <tr className="border-b border-border">
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.objects.colId")}
                </th>
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.objects.colElement")}
                </th>
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.objects.colAction")}
                </th>
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.objects.colVersions")}
                </th>
                <th scope="col" className="px-2 py-1 font-semibold">
                  {t("case.objects.colAge")}
                </th>
              </tr>
            </thead>
            <tbody>
              {elements.map((object) => {
                const key = elementKey(object.osm_type, object.osm_id);
                const geometry = geometryText(object);
                return (
                  <tr key={key} className="border-t border-border" data-action={object.action}>
                    <td className="px-2 py-1 font-mono text-xs">{idLabels.get(key) ?? ""}</td>
                    <th scope="row" className="px-2 py-1 font-mono text-xs font-normal">
                      {key}
                      {geometry ? (
                        <span className="ml-2 font-sans text-text-muted">{geometry}</span>
                      ) : null}
                    </th>
                    <td className="whitespace-nowrap px-2 py-1">
                      <span aria-hidden="true" className="mr-1 font-mono">
                        {ACTION_GLYPH[object.action]}
                      </span>
                      {t(ACTION_LABEL[object.action])}
                    </td>
                    <td className="px-2 py-1 font-mono text-xs">
                      {object.version_before === null || object.version_before === undefined
                        ? t("case.objects.versionNew", { after: object.version_after })
                        : t("case.objects.versions", {
                            before: object.version_before,
                            after: object.version_after,
                          })}
                    </td>
                    <td className="px-2 py-1">
                      {formatAge(object.age_days)}
                      {object.action === "delete" ? (
                        <span className="ml-1 text-xs text-text-muted">
                          ({t(AGE_BUCKET_LABEL[ageBucket(object.age_days)])})
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollRegion>
      )}
    </Section>
  );
}
