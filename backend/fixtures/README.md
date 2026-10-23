# Fixtures

Replay fixtures for evidence collection, the policy gate and evaluation. Layout and validation rules: [`schema.md`](schema.md). Load one with `cso.domain.fixtures.load_case(path)`.

## Licensing

- **Synthetic fixtures** (changeset ids ≥ 900000000000, anonymized names such as `mapper_A`) are original test data released under **CC0 1.0**.
- **Fixtures recorded from the live OpenStreetMap API** (via `cso record`) contain OpenStreetMap data and are **© OpenStreetMap contributors, available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/)**; see <https://www.openstreetmap.org/copyright>. They are not covered by the Apache-2.0 code license.
- Evaluation labels are CC0.

## Demo set (`demo/cases`)

Fifteen real changesets recorded on 20 October 2026 with `cso record`, for a queue that looks like the real thing: `uv run cso seed --fixtures fixtures/demo`. Mapper names and ids are anonymized by the recorder; changeset ids and map data are real, so this set is ODbL. Each `expected.json` carries a `place_label` (looked up once by hand from the changeset's bounding box, and marked "wide area" where the box is very large) and a real run of the Strands Decider 2B on a GPU, with the receipt stored so no model is needed to view it. Seeding needs no network. They span India (Bengaluru, Pune, Kolkata, Mumbai, Kollam, Karnataka), Kenya (Nairobi, including a partial revert of a flagged changeset), Germany, Mexico and two worldwide boxes, and include two edits that touch ways from MapRoulette challenge 56160 (unconnected crosswalks).

## Cases

| Case | What it covers |
|---|---|
| `01-legitimate` | Experienced mapper adds `surface=*` (StreetComplete style); all prior versions present |
| `02-good-faith-mistake` | New mapper renames a residential road to a shop name; v-1 shows the original name; one discussion comment |
| `03-insufficient-evidence` | 300 modified ways, the fetch budget covers 40, two prior versions redacted (403) |
| `04-large-deletion` | Six deleted ways (one a named school with a long history) and 120 tagless deleted nodes |
| `05-conflicting-discussion` | Four comments in which two mappers disagree and the author cites a survey |
| `06-history-gap` | Six modified ways whose prior versions are all redacted |
| `07-provider-timeout` | Sixteen modified ways with three prior-version timeouts and a user-profile timeout |
| `08-adversarial-text` | Shaped like case 02, with instruction-like text and markup in the comment, discussion and name tags (inert evidence) |
