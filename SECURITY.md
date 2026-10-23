# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue or pull request.

- Email **yogeshselvarajan@gmail.com** with the subject "Changeset Second Opinion security". Include what you found, how to reproduce it, the version or commit, and the impact you expect.
- When the repository is public you may also use GitHub's private vulnerability reporting for it, if enabled.
- You will get an acknowledgement within 3 days. There is no bounty. This is a small hackathon project, so a fix may take longer than that; we will tell you where it stands.
- **Disclosure window:** 90 days from the report, or until a fix is released if sooner. Please keep the details private until then. After that, public discussion is welcome.

Please do not include real personal data about OpenStreetMap contributors in a report.

## Scope

In scope: this repository and any instance of it that we host. That means the API, the web app, the worker, the Decider client, the evidence handling, the drafting path, authentication and sessions (invite codes and sign-in with OpenStreetMap), the workspace settings, the logo upload, and the deployment files in `infra/`.

Out of scope: OpenStreetMap, MapRoulette, AWS and Hugging Face services themselves; the Strands Decider server and Strands SDK (report those upstream); findings that need a malicious local user on the host; denial of service by raw traffic volume; and social engineering.

Please do not test against OpenStreetMap or anyone else's server, and do not run Bedrock-backed checks against an account that is not yours.

## What the design assumes

The controls are described in the [responsible use](site/src/content/docs/concepts/responsible-use.mdx) and [privacy](site/src/content/docs/administer/privacy.mdx) pages of the documentation. The short version:

- **Evidence is untrusted.** Text written by mappers is sanitized, quoted and shown as plain text. It is never treated as an instruction, rendered as HTML, or used to build a request. URLs found in evidence are never fetched.
- **No OSM write path.** The OSM client is GET-only to two allowed hosts, with one exception: the POST that trades a sign-in code for a token at the OpenStreetMap token endpoint (ADR-011). That sign-in asks for `read_prefs` only, uses the token once to read the user name and does not store it. A person posts any comment themselves.
- **The model cannot widen what the tool does.** Policy rules read parsed evidence; the drafting agent has one tool, and a hook reads the stored decision and cancels the call when the response type is not allowed. A draft is only ever text for a person to edit.
- **Uploads and branding.** The only upload is the workspace logo, an SVG that only an admin can set. It is parsed without external entities, accepted from an allow-list of shapes (no script, no style, no embedded content, no links), stored as cleaned text, and served with a sandboxing policy and shown through an image tag, so nothing in it can run.
- **Access.** Reviewers sign in with invite codes or with their OpenStreetMap account. Only an argon2 hash of a code's secret is stored. Sessions are server-side with a random token (only its hash is stored), rotation on login, idle and absolute expiry, and a CSRF token bound to the session. Unknown, wrong, spent and expired codes return the same response. Audit rows and logs never contain codes or tokens.
- **Network.** The Decider listens on `127.0.0.1` only. The deployment template has no SSH and no inbound rule except HTTPS, uses an instance role with narrow permissions, requires IMDSv2, and keeps no secrets in the template, the repository, user data or on the disk: secrets sit in SSM Parameter Store and are written to a memory-backed file at boot. The instance role can read the SSM parameters of its own deployment (including an optional git token) and every container shares the host's role credentials; see [Deploy on AWS](site/src/content/docs/self-host/deploy-on-aws.mdx).

## Known limits

Please read these before reporting them as new:

- Rate limits are in-memory token buckets for a single API process. They reset on restart and are not shared between processes; a reverse proxy limit sits in front in the deployment.
- Live mode refuses anonymous callers except login, logout and `/me` unless `CSO_LIVE_ANON_READ` is set.
- The code has not had an independent security review yet.

## Supported versions

Only the latest commit on the default branch (versions `0.y.z`).
