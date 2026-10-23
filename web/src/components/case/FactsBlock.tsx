import type { CaseDetail, ChangedElement } from "../../api/types.gen";
import { t } from "../../i18n";
import {
  AGE_BUCKET_LABEL,
  bboxText,
  changesetCountText,
  deletionAges,
  formatAge,
  formatDateTime,
  osmChangesetUrl,
  type AgeBucket,
} from "./caseModel";
import { Fact, Section } from "./Section";
import { Untrusted } from "./Untrusted";

const BUCKET_ORDER: readonly AgeBucket[] = ["recent", "year", "older", "unknown"];

/**
 * The plain facts about the changeset and the account, as the API reports them. Mapper-written
 * fields are shown as quoted text; nothing here is interpreted or linked.
 */
export function FactsBlock({
  detail,
  elements,
  mapOpen,
  onToggleMap,
}: {
  detail: CaseDetail;
  elements: readonly ChangedElement[] | undefined;
  mapOpen: boolean;
  onToggleMap: () => void;
}) {
  const changeset = detail.changeset;
  const user = changeset?.user;
  const counts = detail.element_counts;
  const bbox = bboxText(changeset?.bbox);
  const osmUrl = osmChangesetUrl(detail.changeset_id);
  const ages = deletionAges(elements);
  const flags = detail.flags ?? [];
  return (
    <>
      <Section id="facts" title={t("case.facts.title")} testId="facts">
        <dl className="space-y-1">
          <Fact label={t("case.facts.comment")}>
            {changeset?.comment ? (
              <q>
                <Untrusted value={changeset.comment} />
              </q>
            ) : (
              <span className="text-text-muted">{t("case.facts.noComment")}</span>
            )}
          </Fact>
          <Fact label={t("case.facts.editor")}>
            {changeset?.created_by ? (
              <Untrusted value={changeset.created_by} className="font-mono" />
            ) : (
              t("case.unknown")
            )}
          </Fact>
          {changeset?.source ? (
            <Fact label={t("case.facts.source")}>
              <Untrusted value={changeset.source} />
            </Fact>
          ) : null}
          <Fact label={t("case.facts.opened")}>{formatDateTime(changeset?.created_at)}</Fact>
          {changeset?.closed_at ? (
            <Fact label={t("case.facts.closed")}>{formatDateTime(changeset.closed_at)}</Fact>
          ) : changeset?.open ? (
            <Fact label={t("case.facts.closed")}>{t("case.facts.stillOpen")}</Fact>
          ) : null}
          {changeset?.review_requested ? (
            <Fact label={t("case.facts.reviewRequested")}>{t("case.yes")}</Fact>
          ) : null}
          <Fact label={t("case.facts.counts")}>
            <span data-testid="counts">
              {t("case.facts.countsText", {
                create: counts.create ?? 0,
                modify: counts.modify ?? 0,
                delete: counts.delete ?? 0,
              })}
            </span>
          </Fact>
          {flags.length > 0 ? (
            <Fact label={t("case.facts.flags")}>
              <ul className="flex flex-wrap gap-1" data-testid="flags">
                {flags.map((flag) => (
                  <li key={flag} className="rounded border border-border px-2 py-0.5 text-xs">
                    <Untrusted value={flag} />
                  </li>
                ))}
              </ul>
            </Fact>
          ) : null}
        </dl>

        <h4 className="mt-4 text-sm font-semibold">{t("case.user.title")}</h4>
        {user ? (
          <dl className="mt-1 space-y-1" data-testid="user-facts">
            <Fact label={t("case.user.name")}>
              {user.display_name ? <Untrusted value={user.display_name} /> : t("case.unknown")}
            </Fact>
            <Fact label={t("case.user.age")}>
              {user.account_age_days === null || user.account_age_days === undefined
                ? t("case.unknown")
                : t("case.user.ageAtEdit", { age: formatAge(user.account_age_days) })}
            </Fact>
            <Fact label={t("case.user.changesets")}>
              <span data-testid="user-changesets">{changesetCountText(user)}</span>
            </Fact>
            <Fact label={t("case.user.blocks")}>
              {user.blocks_active === null || user.blocks_active === undefined
                ? t("case.unknown")
                : user.blocks_active}
            </Fact>
          </dl>
        ) : (
          <p className="mt-1 text-sm text-text-muted" data-testid="user-missing">
            {t("case.user.missing")}
          </p>
        )}

        <h4 className="mt-4 text-sm font-semibold">{t("case.place.title")}</h4>
        <dl className="mt-1 space-y-1">
          {detail.place_label ? (
            <Fact label={t("case.place.label")}>
              <Untrusted value={detail.place_label} />
            </Fact>
          ) : null}
          <Fact label={t("case.place.bbox")}>
            {bbox ? <span className="font-mono">{bbox}</span> : t("case.place.noBbox")}
            {changeset?.bbox_wraps ? (
              <span className="ml-2 text-text-muted">{t("case.place.wraps")}</span>
            ) : null}
          </Fact>
        </dl>
        <div className="mt-2 flex flex-wrap gap-2">
          {osmUrl ? (
            <a
              href={osmUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-8 items-center rounded border border-control-border px-3 text-sm underline"
            >
              {t("case.place.openOsm")}
            </a>
          ) : null}
          {bbox ? (
            <button
              type="button"
              aria-pressed={mapOpen}
              onClick={onToggleMap}
              className="inline-flex min-h-8 items-center rounded border border-control-border px-3 text-sm"
            >
              {mapOpen ? t("case.place.hideMap") : t("case.place.showMap")}
            </button>
          ) : null}
        </div>

        {ages.total > 0 ? (
          <div className="mt-4" data-testid="deletion-ages">
            <h4 className="text-sm font-semibold">
              {t("case.deletions.title", { n: ages.total })}
            </h4>
            <ul className="mt-1 space-y-0.5 text-sm">
              {BUCKET_ORDER.map((bucket) => (
                <li key={bucket} data-bucket={bucket}>
                  {t(AGE_BUCKET_LABEL[bucket])}: {ages.buckets[bucket]}
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-text-muted">{t("case.deletions.note")}</p>
          </div>
        ) : null}
      </Section>
    </>
  );
}
