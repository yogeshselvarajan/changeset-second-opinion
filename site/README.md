# Docs site

The user documentation for Changeset Second Opinion, built with [Starlight](https://starlight.astro.build/) (Astro). It is served as part of the product website at `/docs/`.

```sh
cd site
npm ci
npm run dev        # serves http://localhost:4321/docs/
npm run build      # builds the site and checks internal links and anchors
npm run check:prose
```

The generated reference pages are committed. After a change to the code they read, run `npm run generate` (it runs `uv run python -m cso.tools.export_docs` in `../backend`, so install the backend first with `cd ../backend && uv sync --frozen`) and commit the result. CI fails when they differ from the code.

## Layout

| Path | What |
|---|---|
| `src/content/docs/` | The pages, one folder per section. Every page is a tutorial, how-to, reference or explanation, and its first line says who it is for |
| `src/content/docs/reference/` | `command-line`, `settings`, `roles-and-permissions`, `community-pack-schema`, `receipt-schema` are generated and committed; `errors` is written by hand. The REST API reference is drawn from `../backend/openapi/v1.json` by `starlight-openapi` |
| `src/components/`, `src/styles/` | The footer, the screenshot component and the theme |
| `scripts/generate.mjs` | Writes the generated pages from the code |
| `scripts/check-generated.mjs` | Fails when the committed generated pages differ from the code |
| `scripts/screenshots.mjs` | Takes the screenshots in `src/assets/screens/` from the app in replay mode, light and dark |
| `scripts/prose-lint.mjs`, `.vale/` | The prose rules: no em dashes, none of the words the product never uses, sentence case headings |
| `scripts/axe.mjs` | Accessibility check of every built page, light and dark |
| `scripts/run-tested-commands.mjs` | Runs the shell blocks marked `sh test`, nightly |

## Write a page

1. Pick the type first. A tutorial teaches by doing, a how-to gets one task done, reference is complete and dry, an explanation says why. One type per page.
2. Add the file under the right section and its slug to the sidebar in `astro.config.mjs`.
3. Title and description in the front matter, then a first line such as `*For reviewers. How-to.*`.
4. Link to other pages with relative paths and a trailing slash, for example `../read-a-receipt/`.
5. Screenshots: `<ThemedShot name="queue" alt="..." />` (the page must be `.mdx`).
6. Run `npm run check:prose && npm run build` before you push.

Commands that are quick and work offline can be marked as tested by writing the fence as `sh test`; a nightly job runs them.

## Settings

`DOCS_SITE`, `DOCS_BASE` and `DOCS_REPO` set the public address, the base path (default `/docs`) and the edit links.
