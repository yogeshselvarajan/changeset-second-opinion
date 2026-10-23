---
title: Roles and permissions
description: The lowest role that can call each endpoint.
---

*For admins and operators. Reference.*

:::note[Generated page]
This page is written by `site/scripts/generate.mjs` from the endpoint inventory in `backend/src/cso/api/inventory.py`, which a contract test keeps equal to the running app. Do not edit it by hand; change the code and rebuild.
:::

Roles are ordered: viewer, then reviewer, then admin. A higher role can do everything a lower one can.

## The roles

| Role | Who and what |
| --- | --- |
| no sign-in | Anyone, including the public receipt links and the sign-in redirects. |
| viewer | Someone browsing without signing in (replay mode), or any signed-in person. Can read the queue, cases, evidence, runs, config and history. Cannot change anything. |
| reviewer | Signed in with OpenStreetMap or an invite code. Can add and analyse changesets, ask for drafts and record outcomes. |
| admin | Can also see invites, versions, reliability and the decisions export, change settings, activate a community pack, calibrate and manage invites. |

In live mode, reading needs a sign-in unless the operator sets `CSO_LIVE_ANON_READ`. See [Settings reference](../settings/).

## Every endpoint

| Method | Path | Lowest role | What it does |
| --- | --- | --- | --- |
| GET | `/healthz` | no sign-in | Healthz |
| GET | `/readyz` | no sign-in | Readiness of the database and the model server |
| POST | `/api/v1/auth/login` | no sign-in | Start a reviewer session with an invite code |
| POST | `/api/v1/auth/logout` | viewer | End the current session |
| GET | `/api/v1/auth/osm/start` | no sign-in | Begin signing in with OpenStreetMap |
| GET | `/api/v1/auth/osm/callback` | no sign-in | Finish signing in with OpenStreetMap |
| GET | `/api/v1/me` | no sign-in | Current identity, role and mode |
| GET | `/api/v1/cases` | viewer | List cases in queue order |
| POST | `/api/v1/cases` | reviewer | Create a case and queue its analysis |
| POST | `/api/v1/cases/import` | reviewer | Create cases in bulk from a challenge or a list of ids |
| GET | `/api/v1/cases/{id}` | viewer | Case detail |
| GET | `/api/v1/cases/{id}/evidence` | viewer | Evidence snapshot of a case |
| GET | `/api/v1/cases/{id}/runs` | viewer | Runs of a case, newest first |
| GET | `/api/v1/runs/{id}` | viewer | A run with its decision receipt |
| GET | `/api/v1/receipts/{id}` | no sign-in |  |
| POST | `/api/v1/cases/{id}/analyses` | reviewer | Request an analysis |
| GET | `/api/v1/jobs/{id}` | viewer | Status of a background job |
| POST | `/api/v1/jobs/{id}/cancel` | reviewer | Ask for a job to end |
| POST | `/api/v1/cases/{id}/drafts` | reviewer | Request a draft comment |
| GET | `/api/v1/drafts/{id}` | viewer | A draft comment with its validation result |
| PUT | `/api/v1/cases/{id}/outcome` | reviewer | Record what the reviewer decided |
| GET | `/api/v1/cases/{id}/audit` | viewer | Audit events of a case |
| GET | `/api/v1/decisions` | viewer | Outcome history across cases |
| GET | `/api/v1/decisions/export.csv` | admin | CSV export of the outcome history |
| GET | `/api/v1/config` | viewer | The active community configuration |
| GET | `/api/v1/config/versions` | admin | Stored configuration versions |
| GET | `/api/v1/config/packs` | viewer | Community packs the server can offer |
| POST | `/api/v1/config/packs/{id}/activate` | admin |  |
| GET | `/api/v1/config/diff` | viewer | What differs between two packs |
| GET | `/api/v1/config/reliability` | admin | What reviewers' decisions say about the fact probes |
| POST | `/api/v1/config/calibrate` | admin | Refit the cut points from reviewers' decisions |
| POST | `/api/v1/workspace/claim` | reviewer | Claim an unclaimed workspace and become its admin |
| GET | `/api/v1/settings` | admin | The workspace settings (admin) |
| PUT | `/api/v1/settings` | admin | Save the workspace settings (admin, If-Match) |
| GET | `/site.webmanifest` | no sign-in | The web app manifest, following the workspace name |
| GET | `/api/v1/public/branding` | no sign-in | Name, tagline, accent and wording for the public pages (no sign-in) |
| GET | `/api/v1/public/branding/logo.svg` | no sign-in | The workspace logo (no sign-in) |
| GET | `/api/v1/invites` | admin | Every invite code, newest first (admin) |
| POST | `/api/v1/invites` | admin | Make an invite code (admin) |
| POST | `/api/v1/invites/{id}/revoke` | admin | Revoke an invite code and end the sessions it opened (admin) |
