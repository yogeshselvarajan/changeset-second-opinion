# Required checks

One check gates merging into `main`: **`ci-passed`**, the last job of `.github/workflows/ci.yml`. It
needs every other job in that file and fails when any of them failed or was cancelled. A job that a
path filter skipped counts as passed, so a docs-only change does not wait for the Playwright run.
Branch protection names only `ci-passed` (plus the pull request title check, see
[`RULESETS.md`](RULESETS.md)), so adding or renaming a job never needs a settings change.

| Job name | Runs when | What it runs |
|---|---|---|
| `changes` | always | Decides which paths changed (`.github/scripts/changed_paths.sh`). Anything unclear turns every filter on |
| `backend` | backend, config or CI script changes | `uv lock --check`; ruff check and format; mypy; `alembic upgrade head` and `alembic check` on SQLite; pytest (the live and slow tests are not in the default run) |
| `contract` | backend or web changes | OpenAPI document equals the app; the CI scripts' lint and tests; generated TypeScript client equals the committed one |
| `invariants` | always | `scripts/ci/run_all.py` (no OSM writes, no auto actions, policy inputs, banned words, no dashes, document links); the security policy cross check |
| `secrets` | always | gitleaks over the full history of the branch |
| `web` | web, site or OpenAPI changes | prettier; eslint; tsc; vitest; `npm run build` (includes the docs site and the prerender); bundle size budget |
| `e2e` | web, site or OpenAPI changes | Playwright `@shell`, `@landing`, `@seo`, `@auth` and `@docs` specs against the built bundle, API mocked |
| `docs-site` | site, web, backend source or doc changes | prose rules; Vale; site build with internal link validation; generated reference pages equal the code; axe in light and dark |
| `infra` | infra, scripts or backend packaging changes | cfn-lint on every template; hadolint; `docker compose config` for every supported combination; Caddyfile validation; `bash -n` and shellcheck |
| `workflows` | any change under `.github/` | actionlint; zizmor (medium severity and above) |
| `package` | backend changes | `uv build`; `twine check --strict`; wheel contents (migrations, demo fixtures, licence, no tests or secrets); clean-venv install and `cso --help` |
| `licenses` | backend or lock file changes | runtime dependencies carry no GPL or AGPL licence (allow list: `.github/license-allowlist.txt`, empty) |
| `audit` | lock file changes | `pip-audit`; `npm audit --audit-level=high` for `web/` and `site/` |
| `ci-passed` | always | The aggregate described above |

Other workflows (not part of `ci-passed`):

| Workflow | Purpose |
|---|---|
| `pr hygiene` (`pr-title`) | Pull request title is a Conventional Commit with a repository scope. Required in the ruleset |
| `codeql` | Python and JavaScript/TypeScript analysis. Needs a public repository or `ENABLE_ADVANCED_SECURITY=true` |
| `dependency review` | Blocks new dependencies with high severity advisories or GPL and AGPL licences. Same condition as CodeQL |
| `scorecard` | OpenSSF Scorecard, weekly. Starts once the repository is public |
| `postgres` | Migrations and repository tests on Postgres 17: nightly, on demand, or with the `postgres` label |
| `docs commands still work`, `docs external links` | Nightly and weekly checks of the documented commands and outside links |
| `release-please`, `release`, `deploy demo` | Release and deployment, see [`site/src/content/docs/contribute/ci-and-releases.mdx`](../site/src/content/docs/contribute/ci-and-releases.mdx) |
| `labeler`, `stale` | Housekeeping |

## Running the checks locally

```sh
uv run --project backend python scripts/ci/run_all.py              # the invariant checks
uv run --project backend python -m pytest scripts/ci -q            # their tests
uv run --project backend python -m cso.tools.export_openapi --check
bash .github/scripts/package_check.sh backend /tmp/cso-dist        # build and inspect the distribution
bash .github/scripts/check_security_policy.sh
uvx --from actionlint-py actionlint && uvx zizmor --min-severity medium .github
```
