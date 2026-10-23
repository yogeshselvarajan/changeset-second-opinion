# Changeset Second Opinion (backend)

The Python package behind Changeset Second Opinion, a second-opinion review tool for flagged
OpenStreetMap changesets. It collects evidence for a changeset, asks a small decision model a fixed
set of questions, applies readable rules, orders a review queue in lanes and drafts a comment that a
person edits and posts. Nothing in it writes to OpenStreetMap, and nothing is hidden from reviewers.

This is the PyPI distribution `changeset-second-opinion`. The import package is `cso` and the
command is `cso`.

```sh
pip install changeset-second-opinion
cso --help
```

It needs Python 3.13. The web app, the documentation site and the deployment files live in the
[repository](https://github.com/yogeshselvarajan/changeset-second-opinion), and the container images
are published at `ghcr.io/yogeshselvarajan/`.

## What the package contains

- The API, the worker and the command line (`cso api`, `cso worker`, `cso seed`, `cso eval`).
- The database migrations (`cso.persistence.migrations`), applied with `cso db upgrade`.
- The recorded demo cases, under `cso/_data/fixtures/demo/` inside the installed package. To run in
  replay mode from an installed copy, set `CSO_FIXTURES_DIR` to that folder.

The community configuration files (`config/communities/*.yaml` in the repository) are not part of the
package. Download the one you want and set `CSO_COMMUNITY_CONFIG` to its path.

## Documentation

Setup, settings, the API reference and the design notes are at
<https://osm.changesetreview.online/docs/>. Report problems at
<https://github.com/yogeshselvarajan/changeset-second-opinion/issues>. The change history is in
[CHANGELOG.md](https://github.com/yogeshselvarajan/changeset-second-opinion/blob/main/CHANGELOG.md).

## Licence

Apache-2.0. Third party notices are in `THIRD_PARTY_NOTICES.md` in the repository. The automated
flags (`adapters/osm/flags.py` and its suspect word list) are original code and data under the same
licence, and no GPL or AGPL package is a runtime dependency. `psycopg` stays LGPL-3.0 and is used
unmodified.

## How it is made

The code was written with the help of AI coding agents. A person reviews and approves every change
before it merges, and the checks in the repository (tests, type checks, invariant checks and
documentation rules) run on every pull request.
