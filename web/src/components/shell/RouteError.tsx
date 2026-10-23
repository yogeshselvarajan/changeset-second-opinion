import { t } from "../../i18n";

/** The router's fallback when a route throws or its code fails to load: a sentence and a reload. */
export function RouteError() {
  return (
    <section aria-labelledby="route-error-title" role="alert" className="mx-auto max-w-xl p-6">
      <h1 id="route-error-title" className="text-xl font-semibold">
        {t("error.boundary.title")}
      </h1>
      <p className="mt-2 text-text-muted">{t("error.boundary.body")}</p>
      <button
        type="button"
        className="mt-4 min-h-8 rounded border border-border bg-surface px-3"
        onClick={() => window.location.reload()}
      >
        {t("error.boundary.reload")}
      </button>
    </section>
  );
}
