import { t } from "../i18n";

/**
 * The page title for an app address: the screen name, with a short case id where there is one.
 * Unknown addresses have no screen name, so the page keeps the plain site title.
 */
export function routeTitle(pathname: string): string | undefined {
  if (pathname.startsWith("/cases/")) {
    const parts = pathname.split("/").filter(Boolean);
    const id = (parts[1] ?? "").slice(0, 8);
    return parts[2] === "draft" ? t("seo.draft", { id }) : t("seo.case", { id });
  }
  if (pathname === "/" || pathname.startsWith("/queue")) return t("nav.queue");
  if (pathname.startsWith("/history")) return t("nav.history");
  if (pathname.startsWith("/config")) return t("nav.config");
  if (pathname.startsWith("/settings")) return t("nav.settings");
  if (pathname.startsWith("/login")) return t("nav.signIn");
  return undefined;
}
