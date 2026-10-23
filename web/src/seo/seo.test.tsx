import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PLACEHOLDER, publicOrigin } from "../../vite.public-origin";
import { HOME_TITLE, pageFor } from "../landing/pages";
import { isHostedDemo, PUBLIC_ROUTES, sitemapXml } from "../landing/site";
import { Seo, SITE_NAME, fullTitle } from "./Seo";
import { routeTitle } from "./routeTitle";

describe("fullTitle", () => {
  it("adds the site name once", () => {
    expect(fullTitle("Queue")).toBe(`Queue · ${SITE_NAME}`);
    expect(fullTitle(SITE_NAME)).toBe(SITE_NAME);
    expect(fullTitle()).toBe(SITE_NAME);
  });

  it("does not repeat the name when the title already starts with it", () => {
    expect(HOME_TITLE).toBe(`${SITE_NAME}: flagged OpenStreetMap edits`);
    expect(HOME_TITLE.length).toBeLessThan(65);
    expect(fullTitle(HOME_TITLE)).toBe(HOME_TITLE);
    expect(pageFor("/").title).toBe(HOME_TITLE);
  });
});

describe("isHostedDemo", () => {
  it("is true only on the hosted demo host", () => {
    expect(isHostedDemo("osm.changesetreview.online")).toBe(true);
    expect(isHostedDemo("localhost")).toBe(false);
    expect(isHostedDemo("review.example.org")).toBe(false);
    expect(isHostedDemo(undefined)).toBe(false);
  });
});

describe("routeTitle", () => {
  it("names each app screen", () => {
    expect(routeTitle("/queue")).toBe("Queue");
    expect(routeTitle("/")).toBe("Queue");
    expect(routeTitle("/history")).toBe("History");
    expect(routeTitle("/config")).toBe("Config");
    expect(routeTitle("/settings")).toBe("Settings");
    expect(routeTitle("/login")).toBe("Sign in");
  });
  it("gives a case a short id and a draft its own title", () => {
    expect(routeTitle("/cases/0192ab34-0000-7000-8000-000000000001")).toBe("Case #0192ab34");
    expect(routeTitle("/cases/0192ab34-0000-7000-8000-000000000001/draft")).toBe(
      "Draft for case #0192ab34",
    );
  });
  it("has no name for an unknown address", () => {
    expect(routeTitle("/nowhere")).toBeUndefined();
  });
});

describe("Seo", () => {
  it("hoists a title, a description and a robots tag into the head", () => {
    document.head.innerHTML = "<title data-static-seo>static</title>";
    render(<Seo title="History" noindex />);
    expect(document.title).toBe(`History · ${SITE_NAME}`);
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "noindex",
    );
    expect(document.head.querySelector('meta[name="description"]')).not.toBeNull();
  });

  it("removes the static title that index.html ships so it cannot win", () => {
    document.head.innerHTML = "<title data-static-seo>static</title>";
    render(<Seo title="Config" />);
    expect(document.head.querySelectorAll("title")).toHaveLength(1);
    expect(document.head.querySelector("[data-static-seo]")).toBeNull();
  });

  it("an explicit robots value wins, and a canonical is only added when asked for", () => {
    document.head.innerHTML = "";
    const { unmount } = render(<Seo title="Receipt" robots="noindex,follow" noindex />);
    expect(document.head.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe(
      "noindex,follow",
    );
    expect(document.head.querySelector('link[rel="canonical"]')).toBeNull();
    unmount();
    render(<Seo title="About" canonicalPath="/about" />);
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute("href")).toMatch(
      /\/about$/,
    );
  });
});

describe("public origin", () => {
  it("defaults to the dev server and trims trailing slashes", () => {
    expect(publicOrigin("")).toBe("http://localhost:5173");
    expect(publicOrigin(undefined)).toBe(
      process.env.CSO_PUBLIC_ORIGIN ? publicOrigin() : "http://localhost:5173",
    );
    expect(publicOrigin("https://second-opinion.example.org//")).toBe(
      "https://second-opinion.example.org",
    );
  });

  it("lists exactly the public routes in the sitemap", () => {
    const xml = sitemapXml("https://x.example");
    expect(xml.match(/<loc>/g)).toHaveLength(PUBLIC_ROUTES.length);
    expect(xml).toContain("<loc>https://x.example/</loc>");
    expect(xml).toContain("<loc>https://x.example/about</loc>");
    expect(xml).not.toContain("/queue");
    expect(xml).not.toContain(PLACEHOLDER);
  });
});
