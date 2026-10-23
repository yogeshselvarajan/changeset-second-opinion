# Changelog

User-visible changes, newest first. Dates are when the change landed on `main`. There is no tagged release yet; version numbers will start with the first one. A pull request that changes what a user sees adds a line here.

## 2026-10-20

- **Demo data.** The demo is now fifteen real OpenStreetMap changesets (India, Kenya, Germany, Mexico and more) recorded on 20 October 2026, each read by the Strands Decider 2B, with a place name and the mapper's own comment on its queue row. `cso seed` loads them by default.
- **Admin.** A fresh workspace can be claimed only by an OpenStreetMap account named in `CSO_BOOTSTRAP_ADMIN_OSM_UIDS`. With the setting empty, an admin invite code is the way in.
- **Home page.** A decision model section with readings from a real run, the path of one edit, how to use it in the browser or on the command line, scroll motion with a "Less motion" switch, and a street map backdrop.
- **App.** One look across the queue, case, draft, history, config and settings screens. A claim banner for the named admin. Fixes for the dropdown focus ring and the case map in the dev server.
- **Docs.** A user documentation site (`site/`), with the API, command line, settings, roles and schema references generated from the code.

## 2026-10-19

- **Sign in with OpenStreetMap**, read-only scope. Invite codes still work.
- **Shareable decision receipts** and community packs, with calibration from reviewers' decisions.
- **Settings page** for admins: workspace name, tagline, accent colour, logo, invites and the sign-in switch.
- **Public home, About and Privacy pages**, a front door with icons, a manifest and search engine files.
- **Operations.** Continuous backup, secrets read at boot, alarms and a safe deploy for the single AWS host.
- **Evidence desk redesign** of the app: a rail, a command menu, a queue grid and a timeline.

## 2026-10-17 and 2026-10-18

- First working version: collect the evidence for a changeset, ask the Strands Decider 2B ten questions, apply the rules, order the queue in lanes, draft a comment with Claude Haiku 4.5 on Amazon Bedrock, record the outcome.
- Evaluation tooling and the first measured results, stated with the fact that the answer key was written by an AI.
- Security and honesty fixes found in a review pass.
