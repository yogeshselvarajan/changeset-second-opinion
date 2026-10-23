import { renderToStaticMarkup, renderToString } from "react-dom/server";

import { Landing } from "./landing/Landing";
import { pageFor, PAGES, type PageMeta } from "./landing/pages";
import { PublicLayout } from "./landing/PublicLayout";
import { sitemapXml } from "./landing/site";
import { About, NotFound, Privacy } from "./landing/TextPages";
import { Seo } from "./seo/Seo";

/**
 * Build-time rendering of the public pages. This entry imports the public pages only: no router,
 * no app shell, no query client, nothing that needs a browser. `scripts/prerender.mjs` calls
 * `render` for each page and writes the result into the built `index.html`.
 */
function Content({ path }: { path: PageMeta["path"] }) {
  switch (path) {
    case "/":
      return <Landing />;
    case "/about":
      return <About />;
    case "/privacy":
      return <Privacy />;
    case "/404":
      return <NotFound />;
  }
}

export interface Rendered {
  /** Markup for inside `#root`. */
  html: string;
  /** Head tags (title, description, canonical, robots, JSON-LD) for this page. */
  head: string;
  meta: PageMeta;
}

export function render(path: PageMeta["path"]): Rendered {
  const meta = pageFor(path);
  const html = renderToString(
    <PublicLayout>
      <Content path={path} />
    </PublicLayout>,
  );
  const head = renderToStaticMarkup(
    <Seo
      title={meta.title}
      description={meta.description}
      canonicalPath={meta.noindex ? undefined : path}
      noindex={meta.noindex}
      jsonLd={meta.jsonLd}
    />,
  );
  return { html, head, meta };
}

export { PAGES, sitemapXml };
