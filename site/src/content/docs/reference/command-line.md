---
title: Command line reference
description: Every cso command and its arguments.
---

*For operators and contributors. Reference.*

:::note[Generated page]
This page is written by `site/scripts/generate.mjs` from the argument parser in `backend/src/cso/cli.py`. Do not edit it by hand; change the code and rebuild.
:::

The `cso` command is installed with the backend. Run it from the `backend` folder with `uv run cso <command>`. Add `--help` to any command to see the same text in your terminal.

## Commands

| Command | What it does |
| --- | --- |
| `cso calibrate` | refit probe cut points from reviewers' decisions (dry run by default) |
| `cso api` | run the HTTP API |
| `cso worker` | run the job worker |
| `cso record` | record an anonymized replay fixture from the live OSM API (GET only) |
| `cso db` | database maintenance |
| `cso seed` | load fixture cases and snapshots for replay mode |
| `cso auth` | reviewer access |
| `cso eval` | evaluation harness and Day-1 spike |

## Arguments

### `cso calibrate`

refit probe cut points from reviewers' decisions (dry run by default)

| Argument | What it does | Details |
| --- | --- | --- |
| `--pack` | pack id (default: the active pack) |  |
| `--dry-run` | report only (the default) | default False |
| `--apply` | store and activate the result | default False |

### `cso api`

run the HTTP API

| Argument | What it does | Details |
| --- | --- | --- |
| `--host` |  | default 127.0.0.1 |
| `--port` |  | default 8000 |

### `cso worker`

run the job worker

| Argument | What it does | Details |
| --- | --- | --- |
| `--once` | process due jobs, then exit | default False |
| `--fixture` | replay demo: enqueue this fixture (e.g. 02-good-faith-mistake) and run it |  |
| `--concurrency` | jobs in flight at once | default 2 |

### `cso record`

record an anonymized replay fixture from the live OSM API (GET only)

| Argument | What it does | Details |
| --- | --- | --- |
| `changeset_id` |  |  |
| `--out` | new directory, e.g. fixtures/cases/09-name | required |

#### `cso db upgrade`

apply migrations (default: head)

| Argument | What it does | Details |
| --- | --- | --- |
| `--revision` |  | default head |

### `cso seed`

load fixture cases and snapshots for replay mode

| Argument | What it does | Details |
| --- | --- | --- |
| `--fixtures` | directory containing cases/ (default: the recorded demo set) | default fixtures/demo |

#### `cso auth create-invite`

create an invite code (printed once, stored only as a hash)

| Argument | What it does | Details |
| --- | --- | --- |
| `--role` |  | one of reviewer, admin; default reviewer |
| `--label` | who the code is for (not secret) | default |
| `--max-uses` | logins allowed; default no limit |  |
| `--ttl-hours` | hours until the code expires; default never |  |

#### `cso eval candidates`

collect up to 200 candidate changesets (read-only GETs, polite)

| Argument | What it does | Details |
| --- | --- | --- |
| `--limit` |  | default 200 |
| `--max-minutes` |  | default 25.0 |

#### `cso eval split`

freeze the dev/held-out split (written once)

| Argument | What it does | Details |
| --- | --- | --- |
| `--dev` |  | default 60 |
| `--heldout` |  | default 120 |
| `--dry-run` | show sizes and hash without freezing anything | default False |

#### `cso eval label`

label items from rendered evidence (no model output)

| Argument | What it does | Details |
| --- | --- | --- |
| `--set` |  | one of dev, heldout; default dev |
| `--labeller` |  | required |
| `--session` |  | required |
| `--limit` |  |  |
| `--legacy` | schema version 1: nature and response only, no probes | default False |

#### `cso eval adjudicate`

merge two labelling sessions

| Argument | What it does | Details |
| --- | --- | --- |
| `--set` |  | one of dev, heldout; default dev |
| `--a` |  | required |
| `--b` |  | required |
| `--adjudicator` |  | required |

#### `cso eval spike`

Day-1 go/no-go on the 60 dev items

| Argument | What it does | Details |
| --- | --- | --- |
| `--contract` |  | one of panel, permutation; default panel |

#### `cso eval panel-diagnostic`

run the fact panel over items without labels (not a verdict)

| Argument | What it does | Details |
| --- | --- | --- |
| `--set` |  | one of all, dev, heldout; default all |
| `--profile` |  | one of compact, full; default compact |
| `--include-heldout` | required for --set heldout, and for --set all once the split is frozen: sends the held-out ids through the Decider (no labels read) and says so in the report | default False |
| `--tag` | suffix for the output names, e.g. -v2 | default |
| `--compare-with` | append a before/after section for new_account_first_edits against this run |  |

#### `cso eval ablate-model`

ask a second Decider server the same panel questions and compare (dev set only)

| Argument | What it does | Details |
| --- | --- | --- |
| `--set` |  | one of dev; default dev |
| `--decider-url` | second server, on this machine | required |
| `--label` | short model name used in file names | required |
| `--baseline-label` | name for the default server's run | default 2B |
| `--baseline-json` | reuse a saved run (a results .json) instead of asking the default server again |  |

#### `cso eval backfill-counts`

patch cached snapshots with the edit-time changeset count

No arguments.

#### `cso eval run`

run all systems; heldout needs --released

| Argument | What it does | Details |
| --- | --- | --- |
| `--set` |  | one of dev, heldout, fixtures; default dev |
| `--released` | required for heldout, after the freeze commit; use for the one final run | default False |
| `--contract` |  | one of panel, permutation; default panel |
| `--confirm-freeze` | heldout only: the commit hash that froze evaluation/splits/ (verified against git) |  |
| `--ablations` | heldout only: also run the without-cues and three paraphrase ablations | default False |
| `--authorize-bedrock-usd` | heldout only: dollar ceiling that allows the Haiku baselines (also needs CSO_MODE=live and CSO_LIVE_BEDROCK=1); without it they are reported as not run |  |
| `--hobson-url` | heldout only: a second Decider server running hobson-v21 for that ablation |  |
| `--expect-config-version` | heldout only: refuse unless the community config version starts with this |  |

#### `cso eval report`

render one markdown report from the latest results files (runs nothing)

| Argument | What it does | Details |
| --- | --- | --- |
| `--latest` |  | default False; required |
| `--out` | write here instead of stdout |  |
