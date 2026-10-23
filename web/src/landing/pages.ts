import { copy, REPO_URL } from "./copy";

export interface PageMeta {
  /** The address the page lives at (the 404 page is written as `/404`). */
  path: "/" | "/about" | "/privacy" | "/404";
  title: string;
  description: string;
  /** Search engines are asked to skip the page. */
  noindex?: boolean;
  /** JSON-LD for the page, if any. */
  jsonLd?: Record<string, unknown>;
}

/** The home page title: the name once, then what the tool is for (53 characters, no dashes). */
export const HOME_TITLE = `${copy.name}: flagged OpenStreetMap edits`;

export const SOFTWARE_LD = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: copy.name,
  applicationCategory: "DeveloperApplication",
  operatingSystem: "Web",
  description: copy.description,
  license: "https://spdx.org/licenses/Apache-2.0.html",
  codeRepository: REPO_URL,
  offers: { "@type": "Offer", price: "0" },
} as const;

/** The static pages, in the order they are written to disk and listed in the sitemap. */
export const PAGES: readonly PageMeta[] = [
  { path: "/", title: HOME_TITLE, description: copy.description, jsonLd: SOFTWARE_LD },
  { path: "/about", title: copy.about.title, description: copy.about.description },
  { path: "/privacy", title: copy.privacy.title, description: copy.privacy.description },
  {
    path: "/404",
    title: copy.notFound.title,
    description: copy.notFound.description,
    noindex: true,
  },
];

export function pageFor(path: PageMeta["path"]): PageMeta {
  const page = PAGES.find((candidate) => candidate.path === path);
  if (!page) throw new Error(`no page for ${path}`);
  return page;
}
