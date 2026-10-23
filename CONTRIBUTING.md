# Contributing

Thanks for looking. This is a hackathon MVP with a settled design, so the most useful contributions are fixtures, community option sets, bug reports, and fixes that stay inside the rules below. Read the [README](README.md) first, including its limitations.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems: see [`SECURITY.md`](SECURITY.md), not a public issue.

## Rules every change keeps

CI checks the first three with scripts in [`scripts/ci/`](scripts/ci).

1. **No code path writes to OpenStreetMap.** The OSM client is GET-only and limited to `api.openstreetmap.org` and `maproulette.org`. The one exception is the sign-in POST to the OpenStreetMap token endpoint in `adapters/osm/oauth.py` (ADR-011), which asks for `read_prefs` only; a CI check allows exactly that call and nothing else. Do not add OSM write credentials, OAuth write scopes or any other non-GET call.
2. **Nothing is hidden from reviewers.** Lanes order the queue. There is no auto-close, no auto-post, and no way to filter a case out of sight.
3. **Policy rules use parsed evidence.** Gate inputs are counts, ages and coverage computed from evidence, never a model answer. A model answer may only make a lane more cautious.
4. **Records are immutable.** Snapshots, runs, drafts, outcomes and audit events are never updated or deleted. A correction is a new row.
5. **Evidence text is untrusted.** Sanitize before rendering, render it as text only, keep question text and criteria as constants, and never fetch a URL that came from evidence.
6. **Wording.** The UI and drafts avoid accusatory or alarmist words. The avoid-list lives in `config/communities/default.yaml` under `tone.banned_words`, and a CI check scans the web source and the config. Confidence is shown as every option's probability plus the backend's band, never as a single percentage.
7. **No secrets** in code, logs or the web bundle. The Decider server binds `127.0.0.1` only.

## Your first change in 15 minutes

1. **Clone and install** (3 minutes): `git clone <repo url> && cd changeset-second-opinion-plan`, then `cd backend && uv sync --frozen` and `cd ../web && npm ci`.
2. **Run it in replay mode** (3 minutes): follow "Try it in three minutes" in the [README](README.md). Replay mode needs no network, no GPU and no AWS account. The eight fixture cases are in `backend/fixtures/cases/`; they are synthetic, so you can read and change them freely.
3. **Run one test** (1 minute): `cd backend && uv run pytest tests/unit/domain -q`. It runs in seconds and shows that your setup works.
4. **Pick something small** (5 minutes). Good first changes: fix a typo in a document, tighten a message in `web/src/messages/en.json`, or add a test next to one that already exists.
5. **Check and open the pull request** (3 minutes): run the checks below that touch what you changed, and fill in the template.

## What a good pull request looks like

- It does one thing, and the title says what.
- It says how you checked it: the commands you ran and a one-line result for each.
- It adds or changes a test for the behaviour it touches.
- It keeps the rules above. If a rule gets in the way, open an issue first.
- It includes a screenshot when it changes what a person sees.
- It names what you could not check, for example a live Bedrock call or a browser you do not have.
- It says when an assistant wrote most of it.

## Setup

You need Python 3.13 with [`uv`](https://docs.astral.sh/uv/), and Node with npm. Docker is optional.

```sh
cd backend && uv sync --frozen
cd web && npm ci
```

Replay mode needs no network or GPU. The steps are in the README's quickstart.

## Checks to run before opening a pull request

```sh
# backend
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy src/cso && uv run pytest -q
uv run python ../scripts/ci/run_all.py            # the invariant checks

# web
cd web
npm run lint && npx tsc --noEmit && npm run build && npx vitest run
npx playwright test                               # browser tests; set PW_CHANNEL=chrome to use installed Chrome
```

Notes:

- The full backend suite takes several minutes and the browser suite uses a built bundle; run one worker (`--workers=1`) on a small machine.
- `mypy` runs strict on `cso.domain`, `cso.persistence` and `cso.adapters`.
- On Windows, set `PYTHONUTF8=1` when a script prints non-ASCII characters.
- Tests use fakes for the Decider and Bedrock and need no network. Live checks are opt-in: `CSO_LIVE_TESTS=1` for the OSM test, and a Bedrock test that needs both `CSO_MODE=live` and `CSO_LIVE_BEDROCK=1` and bills your AWS account. Do not run those on someone else's account.

## Shared contracts

These change only through the maintainer, because other work depends on them: `backend/openapi/v1.json`, `backend/pyproject.toml` and `backend/uv.lock`, `web/package.json` and `web/package-lock.json`, and the generated client in `web/src/api`. If your change needs one, say so in the pull request.

- After an API change: `cd backend && uv run python -m cso.tools.export_openapi`, then `cd web && npm run generate:api`. CI fails when either is out of date.
- After a dependency change: regenerate the lockfile and update [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Git and pull requests

- Branches: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`. One topic per pull request.
- Commits follow Conventional Commits with a scope from this list: `osm`, `decider`, `policy`, `draft`, `persistence`, `jobs`, `api`, `auth`, `web`, `obs`, `infra`, `ci`, `eval`, `docs`. Example: `fix(jobs): re-queue on lease expiry`.
- Fill in the pull request template: what changed, how you verified it (commands and a one-line result each), screenshots for UI changes, and the checklist.
- Required checks and branch settings: [`.github/REQUIRED_CHECKS.md`](.github/REQUIRED_CHECKS.md).
- Add tests for what you change. A check that did not run is not a passing check; say so in the pull request.
- Do not add a dependency without a note on why.

## Adding a fixture

Fixtures are replayable cases in `backend/fixtures/cases/`; the layout and validation rules are in [`backend/fixtures/schema.md`](backend/fixtures/schema.md).

1. Record: `cd backend && uv run cso record <changeset_id> --out fixtures/cases/<NN-name>`. It makes read-only GET requests (at most 50 calls, two at a time) with your `CSO_USER_AGENT`, which needs a real contact in live use.
2. It anonymizes people (`mapper_A`, fake uids) and removes emails and URLs from changeset tags and comments. It does **not** anonymize tags on the map elements themselves (for example a `website` or `phone`), so read the output and clean those by hand.
3. Fill in `expected.json` (the rules and the conclusion are left blank on purpose).
4. Check it loads: `uv run pytest tests/unit/domain -q`.

Recorded data is OpenStreetMap data (© OpenStreetMap contributors, ODbL 1.0). Only record what you may redistribute under that licence, and do not use real mapper names. Synthetic fixtures (ids from 900000000000) are CC0.

## Adding a community option set

Option sets, bands, rule parameters and tone live in [`config/communities/default.yaml`](config/communities). Copy it, edit the option codes, labels and descriptions, and run `uv run pytest tests/unit/domain -q`: the loader validates the file and computes a version hash that changes whenever the content changes. Keep description text free of accusatory wording. Changing rule parameters or bands changes behaviour, so describe the effect in your pull request and include evidence.

## Writing docs

The user docs live in [`site/`](site) (Starlight). Every page is one of four kinds, tutorial, how-to, reference or explanation ([Diataxis](https://diataxis.fr/)), and its first line says who it is for. The pages for the API, the command line, the settings, the roles and the schemas are generated from the code: change the code (for settings, the field's `description`), not the page. A change a user can see needs its docs page and a line in [`CHANGELOG.md`](CHANGELOG.md) in the same pull request. Run `cd site && npm ci && npm run check:prose && npm run build` before you push. No em dashes, and none of the words the product never uses.
## Reporting a problem

Use the issue templates in [`.github/ISSUE_TEMPLATE`](.github/ISSUE_TEMPLATE): bug report, idea, fixture proposal, option-set proposal, docs problem.

## AI-assisted contributions

AI coding assistants helped write this repository's code, and a person set the scope and made every decision (see the README's disclosure). AI-assisted contributions are welcome under the same rules: you are responsible for what you submit, the checks above apply, and please say in the pull request when an assistant wrote most of it.
