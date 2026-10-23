/** Pages a search engine may index; the sitemap lists exactly these. */
export const PUBLIC_ROUTES = ["/", "/about", "/privacy"] as const;

/** The one public host that runs the view only demo. Copies that people run themselves are not it. */
export const HOSTED_DEMO_HOST = "osm.changesetreview.online";

/** The docs page that explains how to run your own copy (a static page, so a plain link). */
export const SELF_HOST_GUIDE_PATH = "/docs/self-host/docker-compose/";

/** True only on the hosted demo. Reads the browser address, so it is false while prerendering. */
export function isHostedDemo(
  hostname: string | undefined = typeof window === "undefined"
    ? undefined
    : window.location.hostname,
): boolean {
  return hostname === HOSTED_DEMO_HOST;
}

export function sitemapXml(origin: string): string {
  const urls = PUBLIC_ROUTES.map((path) => `  <url><loc>${origin}${path}</loc></url>`);
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ...urls,
    "</urlset>",
    "",
  ].join("\n");
}
