# Fixture schema

One directory per case under `backend/fixtures/cases/<fixture_id>/`. `fixture_id` is the directory name (`NN-slug`).

```
<fixture_id>/
  changeset.json          GET /api/0.6/changeset/{id}.json?include_discussion=true  (verbatim shape)
  download.osc            GET /api/0.6/changeset/{id}/download                       (osmChange XML)
  prev/<type>_<id>_<v>.json   GET /api/0.6/<type>/<id>/<v>.json   one file per prior version available
  prev/<type>_<id>_<v>.__403__ | .__timeout__   marker: that prior version is redacted / times out
  user.json               GET /api/0.6/user/{uid}.json    (or user.__timeout__ / user.__403__ marker instead)
  expected.json           what replay must reproduce (below)
```

## File shapes

- **`changeset.json`** keeps the live envelope: `version, generator, copyright, attribution, license` plus `changeset` with `id, created_at, closed_at, open, uid, user, min_lat, min_lon, max_lat, max_lon, comments_count, changes_count, tags{comment, created_by, source, locale, …}, comments[{id, visible, date, uid, user, text}]`. Note the live API names the discussion `comments`; hidden comments (`visible: false`) are dropped on load. `min_lon > max_lon` means the box crosses the antimeridian.
- **`download.osc`**: well-formed `osmChange`; only `<create>`, `<modify>`, `<delete>` blocks with `node|way|relation` children. Parsed with defusedxml (DTD and entities forbidden).
- **`prev/*.json`**: live envelope with exactly one entry in `elements`; its `type`, `id`, `version` must match the file name. A key may have a data file **or** a marker, never both. The prior version of an element at version `v` is file `…_<v-1>.json`.
- **Markers** are empty files named `<type>_<id>_<v>.__403__` (redacted) or `.__timeout__` (provider failure) inside `prev/`, and `user.__timeout__` / `user.__403__` at the case root. Replay raises the matching error for that call.
- **`user.json`**: live envelope with `user{id, display_name, account_created, changesets{count}, blocks{received{count, active}}}`. Account age is measured at the changeset's `created_at` so replay is deterministic.

## `expected.json`

| Field | Type | Meaning |
|---|---|---|
| `fixture_id` | str | must equal the directory name |
| `description` | str | one line |
| `changeset_id` | int | must equal `changeset.json` id |
| `coverage` | `Coverage` | exact expected coverage record (`elements_in_changeset`, `elements_detailed`, `elements_skipped_budget`, `history_gaps[{osm_type, osm_id, reason}]`, `user_profile`, `discussion`, `snapshot_truncated`, `score`) |
| `flags` | [str] | expected osmcha reason codes |
| `rules` | [str] | expected policy rule codes (`R1`…`R6`) |
| `nature`, `response`, `lane` | enum or null | expected conclusion (hints; the model may legitimately differ, rules may not) |
| `notes` | str | free text |
| `receipt` | object or null | precomputed decision receipt for replay without a Decider server |

## Validation (`load_case`)

Files present; JSON and XML well-formed; `fixture_id` equals the directory name; `changeset_id` equals the changeset; `coverage.elements_in_changeset` equals the number of elements in `download.osc` unless `coverage.snapshot_truncated` is true; prev file contents match names; no data+marker clash. Violations raise `FixtureError` naming the file.

## Synthetic data rules

Changeset ids ≥ 900000000000; element ids and uids in the 9e8 range; names `mapper_A`, `mapper_B`, …; no real URLs, emails or personal text.
