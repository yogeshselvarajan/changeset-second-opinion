---
title: Settings reference
description: Every environment variable the backend reads, with its type, default and meaning.
---

*For operators and contributors. Reference.*

:::note[Generated page]
This page is written by `site/scripts/generate.mjs` from the `Settings` class in `backend/src/cso/settings.py`. Do not edit it by hand; change the code and rebuild.
:::

Set these in the environment, or in `backend/.env` (the `.env` file next to where you start the app). Names start with `CSO_`. A value that is not valid halts the app at start with a message that names the variable, so a typo never opens something up quietly.

## Main settings

| Variable | Type | Default | What it does |
| --- | --- | --- | --- |
| `CSO_MODE` | one of replay, live | `replay` | replay serves saved changesets and never calls OpenStreetMap, the Decider or Amazon Bedrock. live fetches from OpenStreetMap (GET only) and needs a real CSO_USER_AGENT. |
| `CSO_DATABASE_URL` | text | `sqlite+aiosqlite:///./cso.db` | SQLAlchemy URL of the database. SQLite by default, one file next to the app. |
| `CSO_DECIDER_URL` | text, optional | `not set` | Address of the Strands Decider server, for example http://127.0.0.1:8099. Without it a case is shown with its evidence and rules only, in the Rules only lane. |
| `CSO_DECIDER_DEVICE_CLASS` | one of gpu, cpu | `gpu` | The hardware the Decider runs on. It sets the call timeout: 45 s for gpu and 90 s for cpu. |
| `CSO_BEDROCK_REGION` | text | `us-east-1` | AWS region used for Amazon Bedrock draft calls. |
| `CSO_BEDROCK_MODEL_ID` | text | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model or inference profile id that writes draft comments (Claude Haiku 4.5). |
| `CSO_USER_AGENT` | text | `ChangesetSecondOpinion/0.1 (+<REPO_URL>; <CONTACT_EMAIL>)` | The User-Agent sent to OpenStreetMap and MapRoulette. The OpenStreetMap usage policy asks for a real repository address and a contact email. Live mode refuses to start while the placeholders are still in it. |
| `CSO_JOBS_WORKER_ENABLED` | yes or no | `true` | Run the background worker inside the API process. Turn off when cso worker runs on its own. |
| `CSO_LOG_LEVEL` | one of DEBUG, INFO, WARNING, ERROR | `INFO` | Log verbosity. |
| `CSO_LOG_FORMAT` | one of auto, json, console | `auto` | auto writes JSON in live mode and a readable console format in replay mode. |
| `CSO_DAILY_ANALYSIS_CAP` | whole number | `200` | Most analyses per UTC day, counted from the jobs table so a restart does not reset it. 0 allows none (fail closed). A negative value turns the cap off. |
| `CSO_DAILY_DRAFT_CAP` | whole number | `100` | Most drafts per UTC day. 0 allows none. A negative value turns the cap off. |
| `CSO_BEDROCK_DAILY_USD_CAP` | number | `10.0` | Estimated Bedrock spend allowed per UTC day, in US dollars. Calls past it are refused. |
| `CSO_BEDROCK_INPUT_USD_PER_MTOK` | number, optional | `not set` | Override of the estimated input price, in US dollars per million tokens. Empty uses the built-in estimate, which you should check against current Bedrock pricing. |
| `CSO_BEDROCK_OUTPUT_USD_PER_MTOK` | number, optional | `not set` | Override of the estimated output price, in US dollars per million tokens. |
| `CSO_OSM_OAUTH_CLIENT_ID` | text, optional | `not set` | Client id of the OpenStreetMap OAuth application. Sign in with OpenStreetMap is on only when this, the secret and the redirect URL are all set. |
| `CSO_OSM_OAUTH_CLIENT_SECRET` | secret text, optional | secret, never shown | Client secret of the OpenStreetMap OAuth application. It is shown once when you register the app. It is never logged or shown, and never written to the web bundle. |
| `CSO_OSM_OAUTH_REDIRECT_URL` | text, optional | `not set` | Where OpenStreetMap sends the browser after sign-in, ending in /api/v1/auth/osm/callback. It has to be https, or http on a loopback address such as 127.0.0.1. |
| `CSO_OSM_SIGNIN_ALLOWED_UIDS` | text | `empty` | Optional. Comma-separated OpenStreetMap user ids. When set, only these accounts can sign in with OpenStreetMap. Empty lets every account in. |
| `CSO_BOOTSTRAP_ADMIN_OSM_UIDS` | text | `empty` | Comma-separated OpenStreetMap user ids that may become the workspace admin. It says who, so it is not a secret: OpenStreetMap proves who is signing in. Only a listed account can claim a fresh workspace. Empty means nobody can claim it from the web, and an admin invite made with cso auth create-invite --role admin is the way in. |
| `CSO_WEB_BASE_URL` | text | `empty` | Where the browser goes after sign-in. Empty keeps it on the API's own origin (the hosted layout, where one proxy serves both). Set it when the web app runs on another port, for example http://127.0.0.1:5173. No trailing slash. |

## Other variables

These are read in other places in the code and are not part of the `Settings` class.

| Variable | Type | Default | What it does |
| --- | --- | --- | --- |
| `CSO_AUTH_SESSION_HOURS` | number | 12 | How long a sign-in lasts, in hours. |
| `CSO_AUTH_IDLE_MINUTES` | number | 120 | A sign-in ends after this many idle minutes. |
| `CSO_COOKIE_SECURE` | one of auto, true, false | auto | Whether the session cookie is marked secure. auto marks it secure on https. |
| `CSO_TRUST_PROXY` | yes or no | false | Trust the X-Forwarded-For header for the visitor's address. Turn it on only behind a proxy that overwrites the header. The Compose files and the bootstrap script set it for you. |
| `CSO_LIVE_ANON_READ` | yes or no | false | Let someone who is not signed in read the queue in live mode. In replay mode reading is always open. |
| `CSO_LIVE_BEDROCK` | 1 to allow | not set | The second gate on real Amazon Bedrock calls. They happen only in live mode and only when this is 1. Otherwise drafts come from the offline drafter. |
| `CSO_DRAFT_DAILY_CALLS` | whole number | 200 | Most Bedrock draft calls per day. |
| `CSO_DRAFT_DAILY_TOKENS` | whole number | 200000 | Most Bedrock tokens per day. |
| `CSO_COMMUNITY_CONFIG` | file path | config/communities/default.yaml | The community pack file to load at start. |
| `CSO_FIXTURES_DIR` | folder path | backend/fixtures/demo | The saved changesets that replay mode serves. The Docker image sets it to /app/fixtures/demo. |
| `CSO_EVAL_DIR` | folder path | evaluation | Where cso eval reads labels and writes results. |

## Related pages

- [Register the OpenStreetMap sign-in app](../../self-host/register-the-osm-app/)
- [Set up the first admin](../../administer/first-admin/)
- [Replay mode and live mode](../../self-host/replay-and-live/)
