import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fireEvent, render as renderDom, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { distProblems } from "../../scripts/check-dist.mjs";
import { computeNumbers, disclosure, wilson } from "../../scripts/landing-numbers.mjs";
import { applyPage, markStatic } from "../../scripts/prerender.mjs";
import { render } from "../entry-prerender";
import { copy, fill } from "./copy";
import { Landing } from "./Landing";
import numbers from "./numbers.json";
import { PAGES } from "./pages";
import { SAMPLE_RECEIPT } from "./sample-receipt";
import { About, formatShare } from "./TextPages";

const BANNED = /\b(vandal\w*|spam\w*|illegal\w*|stop|must)\b/i;
const DASHES = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]`);

function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object") return Object.values(value).flatMap(strings);
  return [];
}

describe("the figures", () => {
  it("are the ones computed from the committed evaluation files", () => {
    expect(numbers).toEqual(computeNumbers());
  });

  it("agree with the written spike report", () => {
    const report = readFileSync(
      join(__dirname, "..", "..", "..", "evaluation", "results", "spike-2026-10-17.md"),
      "utf-8",
    );
    expect(report).toContain(
      `Pooled accuracy when decided: ${numbers.pooled_decided.k}/${numbers.pooled_decided.n}`,
    );
    expect(report).toContain(
      `| Panel composed (decision input) | 0.348 | ${numbers.nature_composed.k}/${numbers.nature_composed.n}`,
    );
    expect(report).toContain(
      `| Rule baseline v1 (policy rules) | 0.203 | ${numbers.nature_rules.k}/${numbers.nature_rules.n}`,
    );
  });

  it("use the Wilson interval the backend uses", () => {
    const { lower, upper } = wilson(353, 413);
    expect(lower).toBeCloseTo(0.8175, 3);
    expect(upper).toBeCloseTo(0.8854, 3);
    expect(wilson(0, 0)).toEqual({ k: 0, n: 0, lower: 0, upper: 1 });
  });

  it("are written with an interval and without dashes", () => {
    expect(formatShare(numbers.pooled_decided)).toBe("0.85 (0.82 to 0.89)");
    expect(formatShare({ k: 0, n: 0, lower: 0, upper: 1 })).toBe("no data");
  });

  it("say who wrote the labels: an AI unless a person took part", () => {
    expect(disclosure(60, ["claude"], [null, "claude"]).ai_only).toBe(true);
    const mixed = disclosure(60, ["claude", "Rae"], ["claude"]);
    expect(mixed.ai_only).toBe(false);
    expect(mixed.text).toContain("Rae");
    expect(numbers.labels.text).toMatch(/AI/);
  });
});

describe("the copy", () => {
  it("has no dash, no exclamation mark and none of the words the product never uses", () => {
    for (const text of strings(copy)) {
      expect(text, text).not.toMatch(DASHES);
      expect(text, text).not.toMatch(BANNED);
      expect(text, text).not.toContain("!");
    }
    for (const text of strings(numbers.labels.text)) expect(text).not.toMatch(DASHES);
  });

  it("fills placeholders and leaves unknown ones alone", () => {
    expect(fill("a {x} b {y}", { x: 1 })).toBe("a 1 b {y}");
  });

  it("the example receipt is synthetic and names no real account", () => {
    expect(SAMPLE_RECEIPT.changeset_id).toBe(900000000002);
    expect(copy.receipt.disclosure).toMatch(/invented/);
  });
});

describe("the home page", () => {
  it("has one h1 and the sections in order", () => {
    renderDom(<Landing />);
    const h1 = screen.getAllByRole("heading", { level: 1 });
    expect(h1).toHaveLength(1);
    expect(h1[0]).toHaveTextContent(copy.headline);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      copy.basics.title,
      copy.problem.title,
      copy.how.title,
      copy.decider.title,
      copy.path.title,
      copy.strip.title,
      copy.receipt.title,
      copy.promises.title,
      copy.communities.title,
      copy.engine.title,
      copy.modes.title,
      copy.different.title,
      copy.straight.title,
      copy.openSource.title,
      copy.maker.title,
      copy.cta.title,
    ]);
  });

  it("links the GitHub Sponsors page as a plain link with an icon the screen reader skips", () => {
    renderDom(<Landing />);
    const link = within(screen.getByTestId("maker-links")).getByRole("link", {
      name: copy.maker.sponsor,
    });
    expect(link).toHaveAttribute("href", "https://github.com/sponsors/yogeshselvarajan");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("keeps engineering internals off the home page and names the models with real links", () => {
    const { container } = renderDom(<Landing />);
    const text = container.textContent ?? "";
    for (const word of ["probe", "SQLite", "FastAPI", "ADR", "cuda", "evaluation/results"]) {
      expect(text, word).not.toContain(word);
    }
    expect(screen.queryByTestId("numbers-disclosure")).toBeNull();
    const engine = container.querySelector("#engine");
    expect(engine?.textContent).toContain("Strands Decider 2B");
    expect(
      container.querySelector("#engine a[href*='huggingface.co/StrandsAgents']"),
    ).not.toBeNull();
    expect(
      container.querySelector("#engine a[href*='github.com/strands-labs/strands-decider']"),
    ).not.toBeNull();
    // The decision model section shows readings from a real run, not typed-in claims.
    const decider = container.querySelector("#decider");
    expect(decider?.querySelectorAll(".flow-bar")).toHaveLength(5);
    expect(decider?.textContent).toContain("189806470");
  });

  it("draws the link arrow as an icon, never as literal entity text", () => {
    const { container } = renderDom(<Landing />);
    expect(container.textContent).not.toMatch(/&[a-z]+;/);
    expect(container.querySelectorAll("#basics svg").length).toBeGreaterThanOrEqual(3);
  });

  it("still says plainly that the answer key was written by an AI, and links to the scorecard", () => {
    renderDom(<Landing />);
    expect(screen.getByText(/written by an AI/)).toBeInTheDocument();
    expect(screen.getByTestId("scorecard-link")).toHaveAttribute("href", "/about#numbers");
  });

  it("offers the docs from the open source section", () => {
    renderDom(<Landing />);
    expect(screen.getByTestId("read-docs")).toHaveAttribute("href", "/docs/");
    expect(screen.getByTestId("read-docs")).toHaveTextContent(copy.openSource.docs);
  });

  it("switches the pack text when another pack is chosen", () => {
    renderDom(<Landing />);
    expect(screen.getByText(copy.communities.packs[0].body)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("pack-strict-review"));
    expect(screen.getByText(copy.communities.packs[2].body)).toBeInTheDocument();
  });
});

describe("the about page", () => {
  it("shows the disclosure next to the figures", () => {
    renderDom(<About />);
    expect(screen.getByTestId("numbers-disclosure")).toHaveTextContent("written by an AI");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("says once that the work can be sponsored", () => {
    renderDom(<About />);
    expect(screen.getByText(/you can sponsor the work on GitHub/)).toBeInTheDocument();
  });
});

describe("static rendering", () => {
  it("writes one h1 and the right title for every page", () => {
    for (const page of PAGES) {
      const out = render(page.path);
      expect(out.html.match(/<h1[\s>]/g), page.path).toHaveLength(1);
      expect(out.head).toContain("<title>");
      expect(out.head.includes("noindex"), page.path).toBe(Boolean(page.noindex));
      expect(out.html).not.toContain("undefined");
    }
  });

  it("puts the structured data on the home page only", () => {
    expect(render("/").head).toContain('"@type":"SoftwareApplication"');
    expect(render("/about").head).not.toContain("ld+json");
  });

  it("renders the strip as a still frame, with every row visible", () => {
    const { html } = render("/");
    expect(html).toContain('data-animated="false"');
    expect(html).not.toContain("opacity:0");
  });

  it("escapes what it writes into the head", () => {
    const text = applyPage(
      '<head><title data-static-seo>x</title><meta data-static-seo name="description" content="d"/>' +
        '<link data-static-seo rel="canonical" href="u"/><meta property="og:title" content="t"/>' +
        '<meta property="og:description" content="t"/><meta property="og:url" content="t"/>' +
        '<meta name="twitter:title" content="t"/><meta name="twitter:description" content="t"/>' +
        '</head><div id="root"></div>',
      {
        html: "<p>body</p>",
        head: "<title>T</title>",
        meta: { path: "/about", title: "T", description: 'a "quoted" <b>' },
      },
      "https://x.example",
    );
    expect(text).toContain('content="a &quot;quoted&quot; &lt;b>"');
    expect(text).toContain('<div id="root"><p>body</p></div>');
    expect(text).toContain('content="https://x.example/about"');
  });

  it("marks the replaceable head tags so the client can swap them", () => {
    expect(markStatic('<title>a</title><meta name="x"/><link rel="y"/><script type="z">')).toBe(
      '<title data-static-seo>a</title><meta data-static-seo name="x"/>' +
        '<link data-static-seo rel="y"/><script data-static-seo type="z">',
    );
  });

  it("refuses a template that is not the one it expects", () => {
    expect(() =>
      applyPage(
        "<head></head>",
        { html: "", head: "", meta: { path: "/", title: "", description: "" } },
        "https://x.example",
      ),
    ).toThrow(/static title/);
  });
});

describe("the built-page check", () => {
  const good = `<head><title>T</title></head><div id="root"><div><h1>One</h1></div></div>`;
  const base = {
    files: { "/": good },
    renderedTitles: { "/": "T" },
    sitemap: "<loc>https://x/</loc><loc>https://x/about</loc><loc>https://x/privacy</loc>",
    robots: "Sitemap: https://x/sitemap.xml",
    shell: '<div id="root"></div>',
  };

  it("passes a good build", () => {
    expect(
      distProblems({ ...base, sitemap: base.sitemap.replace("</loc><loc>", "</loc>\n<loc>") }),
    ).toEqual([]);
  });

  it("names each kind of fault", () => {
    const faults = distProblems({
      ...base,
      files: {
        "/": '<head><title>Wrong</title><title>Two</title></head><h1>a</h1><h1>b</h1><div id="root"></div> __CSO_PUBLIC_ORIGIN__ /api/v1/x',
      },
      sitemap: "/queue",
      robots: "nothing",
      shell: '<div id="root"><div>filled</div></div>',
    });
    for (const part of [
      "expected one <h1>",
      "title is",
      "more than one <title>",
      "origin placeholder",
      "root is empty",
      "mentions the API",
      "_shell.html",
      "sitemap.xml: missing /about",
      "lists an app address",
      "robots.txt",
    ]) {
      expect(faults.join("\n"), part).toContain(part);
    }
  });
});
