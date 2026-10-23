## Scope

Work package: WP-__ (one package per branch; the id is also in the PR title)

## What changed

<!-- A short list of the behaviour or files changed. -->

## How it was verified

<!-- Commands you ran and a one-line result for each. A check that did not run is not passing. -->

```text
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src/cso && uv run pytest -q
cd web && npm run lint && npx tsc --noEmit && npx vitest run && npm run build
```

## Screenshots

<!-- For UI changes: light and dark, wide and narrow. Remove this section otherwise. -->

## Checklist

- [ ] Tests cover the change and pass locally
- [ ] Contract regenerated if the API changed (`uv run python -m cso.tools.export_openapi`, then `npm run generate:api`) and docs updated
- [ ] User-visible change? Docs updated (the page under `site/` and a line in `CHANGELOG.md`)
- [ ] No secrets, tokens or personal data in code, logs, fixtures or the web bundle
- [ ] No new dependency without a note explaining why
- [ ] **No code path writes to OpenStreetMap** (no non-GET calls, no OSM write scopes)
- [ ] Nothing is hidden from reviewers and nothing posts or closes automatically
- [ ] UI copy and drafts avoid the banned words and show confidence as all option probabilities plus a band
- [ ] Commit messages follow Conventional Commits with a scope from the repository layout
