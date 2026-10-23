import { useLayoutEffect } from "react";

import { t } from "../i18n";

declare const __CSO_PUBLIC_ORIGIN__: string;

/** The site origin the build was made for (`CSO_PUBLIC_ORIGIN`, default the dev server). */
export const PUBLIC_ORIGIN: string =
  typeof __CSO_PUBLIC_ORIGIN__ === "string" ? __CSO_PUBLIC_ORIGIN__ : "http://localhost:5173";

export const SITE_NAME = "Changeset Second Opinion";

interface SeoProps {
  /** Page title; the site name is added unless this already is the site name. */
  title?: string;
  description?: string;
  /** Set for public pages that want a canonical link (a path such as `/about`). */
  canonicalPath?: string;
  /** App screens say `noindex`; public pages leave this off. */
  noindex?: boolean;
  /** An explicit robots value such as `noindex,follow`; wins over `noindex`. */
  robots?: string;
  /** Structured data for the page (a constant object, never built from evidence). */
  jsonLd?: object;
}

export function fullTitle(title?: string): string {
  if (!title || title.startsWith(SITE_NAME)) return title || SITE_NAME;
  return `${title} · ${SITE_NAME}`;
}

/**
 * Head tags for one route. React 19 hoists `<title>`, `<meta>` and `<link>` into the document
 * head, so this needs no library. Render at most one per route.
 */
export function jsonLdText(data: object): string {
  // `<` is escaped so the text cannot close the script element it sits in.
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

export function Seo({
  title,
  description,
  canonicalPath,
  noindex = false,
  robots,
  jsonLd,
}: SeoProps) {
  const robotsValue = robots ?? (noindex ? "noindex" : null);
  // index.html carries a title and description for crawlers that do not run scripts. Once a route
  // renders its own, the static pair would come first in the head and win, so drop it.
  useLayoutEffect(() => {
    document.head.querySelectorAll("[data-static-seo]").forEach((node) => node.remove());
  }, []);
  return (
    <>
      <title>{fullTitle(title)}</title>
      <meta name="description" content={description ?? t("seo.description")} />
      {canonicalPath ? <link rel="canonical" href={`${PUBLIC_ORIGIN}${canonicalPath}`} /> : null}
      {robotsValue ? <meta name="robots" content={robotsValue} /> : null}
      {jsonLd ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLdText(jsonLd) }}
        />
      ) : null}
    </>
  );
}
