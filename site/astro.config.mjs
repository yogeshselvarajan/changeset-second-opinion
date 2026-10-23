// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import { copyFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import starlightLinksValidator from "starlight-links-validator";
import starlightLlmsTxt from "starlight-llms-txt";
import starlightOpenAPI, { openAPISidebarGroups } from "starlight-openapi";

// The OpenAPI parser percent-encodes a space in a folder name and then cannot open the file (this
// repository sits in a folder with spaces on the author's machine). Where the path has a space, use a
// copy in the temp folder; CI has no space and reads the committed file directly.
const openapiSource = fileURLToPath(new URL("../backend/openapi/v1.json", import.meta.url));
let openapiPath = openapiSource;
if (openapiSource.includes(" ")) {
  openapiPath = join(tmpdir(), "cso-docs-openapi-v1.json");
  copyFileSync(openapiSource, openapiPath);
}

// The docs are served by the web app at /docs/ on the same origin as the home page. The origin comes
// from CSO_PUBLIC_ORIGIN, the variable the web build reads (same fallback). Override these three
// when the repository or the host differs. The default repository address is the one in `git remote -v`.
const repo = process.env.DOCS_REPO ?? "https://github.com/yogeshselvarajan/changeset-second-opinion";
const site =
  process.env.DOCS_SITE ??
  ((process.env.CSO_PUBLIC_ORIGIN ?? "").trim().replace(/\/+$/, "") || "http://localhost:5173");
const base = process.env.DOCS_BASE ?? "/docs";

export default defineConfig({
  site,
  base,
  integrations: [
    starlight({
      title: "Changeset Second Opinion",
      description:
        "Documentation for Changeset Second Opinion: a second opinion on flagged OpenStreetMap edits. Evidence first; a human posts.",
      favicon: "/favicon.svg",
      logo: { src: "./src/assets/mark.svg", alt: "" },
      customCss: ["./src/styles/fonts.css", "./src/styles/custom.css"],
      social: [{ icon: "github", label: "GitHub", href: repo }],
      editLink: { baseUrl: `${repo}/edit/main/site/` },
      // A scrollable code block or table has to take focus, or a keyboard reader cannot scroll it.
      head: [
        {
          tag: "script",
          content:
            "document.addEventListener('DOMContentLoaded',function(){document.querySelectorAll('.sl-markdown-content *, .expressive-code *').forEach(function(el){var o=getComputedStyle(el).overflowX;if((o==='auto'||o==='scroll')&&!el.hasAttribute('tabindex')&&!el.matches('a,button,input,textarea,select')){el.setAttribute('tabindex','0');}});});",
        },
      ],
      lastUpdated: true,
      components: { Footer: "./src/components/Footer.astro" },
      plugins: [
        // Pages link to each other with relative paths (../page/), which keep working under any
        // base path, including the /docs/ path this site is served under.
        // The how-to pages link to http://127.0.0.1 addresses on the reader's own machine on purpose.
        starlightLinksValidator({ errorOnRelativeLinks: false, errorOnLocalLinks: false }),
        starlightLlmsTxt({
          projectName: "Changeset Second Opinion",
          description:
            "A second opinion on flagged OpenStreetMap edits. It collects the public evidence for one changeset, asks the Strands Decider 2B ten yes or no questions, shows every probability, suggests a lane that only orders the queue, and drafts a kind comment with Claude Haiku 4.5 on Amazon Bedrock. It never writes to OpenStreetMap, and a person decides and posts.",
          details:
            "Pages are sorted into tutorials, how-to guides, reference and explanation (Diataxis). The reference pages for the API, command line, settings, roles and schemas are generated from the code.",
        }),
        starlightOpenAPI([
          { base: "api", label: "REST API", schema: openapiPath },
        ]),
      ],
      sidebar: [
        {
          label: "Start here",
          items: ["start/what-it-is", "start/quickstart", "start/glossary"],
        },
        {
          label: "Review",
          items: [
            "review/first-changeset",
            "review/work-the-queue",
            "review/read-the-evidence",
            "review/read-a-receipt",
            "review/draft-and-send-a-comment",
            "review/record-and-correct-an-outcome",
            "review/import-changesets",
            "review/display-and-accessibility",
          ],
        },
        {
          label: "Administer",
          items: [
            "administer/sign-in",
            "administer/first-admin",
            "administer/invite-and-remove-reviewers",
            "administer/privacy",
            "administer/brand-the-workspace",
            "administer/tune-to-your-community",
            "administer/calibration",
          ],
        },
        {
          label: "Self-host",
          items: [
            "self-host/requirements",
            "self-host/docker-compose",
            "self-host/register-the-osm-app",
            "self-host/replay-and-live",
            "self-host/monitor-and-troubleshoot",
            "self-host/run-the-decider",
            "self-host/connect-bedrock",
            "self-host/deployment-options",
            "self-host/deploy-on-aws",
            "self-host/backup-upgrade-migrate",
          ],
        },
        {
          label: "Concepts",
          items: [
            "concepts/how-a-verdict-is-made",
            "concepts/why-lanes-only-order-the-queue",
            "concepts/what-it-cannot-do",
            "concepts/responsible-use",
            "concepts/architecture",
          ],
        },
        {
          label: "Reference",
          items: [
            "reference/command-line",
            "reference/settings",
            "reference/roles-and-permissions",
            "reference/community-pack-schema",
            "reference/receipt-schema",
            "reference/errors",
          ],
        },
        ...openAPISidebarGroups,
        {
          label: "Contribute",
          items: [
            "contribute/dev-setup",
            "contribute/repo-tour",
            "contribute/tests",
            "contribute/add-a-question",
            "contribute/write-docs",
            "contribute/releases",
            "contribute/ci-and-releases",
            "contribute/branding",
          ],
        },
        {
          label: "Project",
          items: [
            "project/faq",
            "project/roadmap",
            "project/changelog",
            "project/licence-and-notices",
          ],
        },
      ],
    }),
  ],
});
