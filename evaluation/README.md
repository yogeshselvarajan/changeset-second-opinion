# Evaluation

Data and results for the Day-1 feasibility spike and the later held-out evaluation. Code lives in
`backend/src/cso/evaluation/`; commands run from `backend/`.

## Layout

| Path | Contents | Committed |
|---|---|---|
| `candidates.jsonl` | Anonymised candidate changesets (mapper hash, flags, coverage, weak MapRoulette status) | yes |
| `splits/` | `dev_ids.txt`, `heldout_ids.txt`, `heldout_ids.sha256`, `reserve_ids.txt`, `split-meta.json` | yes (the commit is the freeze) |
| `labels/<set>.jsonl` | Append-only labels per labeller session (the committed dev labels are AI-produced) | yes |
| `labels/<set>.adjudicated.jsonl` | Gold labels after the adjudication step (append-only; latest row per changeset wins). For the dev set this is the AI labeller's own choice, not a second rater | yes |
| `results/` | Spike report, run summaries and per-item Decider receipts | yes |
| `.cache/` | Raw evidence snapshots (contain mapper names) | never (git-ignored) |
| `samples/` | A recorded Decider receipt | yes |

## Workflow

```sh
cd backend
uv run cso eval candidates --limit 200      # read-only GETs to OSM and MapRoulette; polite, bounded
uv run cso eval split --dev 60 --heldout 102   # writes evaluation/splits/ once; commit it (the freeze)
uv run cso eval label --set dev --labeller me --session s1     # session 1, randomized order
uv run cso eval label --set dev --labeller me --session s2     # session 2 (the design asked for 24 h or more later; the committed dev labels were 25 minutes apart)
uv run cso eval adjudicate --set dev --a me:s1 --b me:s2 --adjudicator me
CSO_DECIDER_URL=http://127.0.0.1:8099 uv run cso eval spike    # needs a running Decider
```

- Labelling shows the rendered evidence only: no model output, no rule results, no weak labels.
  Answer with the menu numbers; `s` skips an item, `q` ends the session, and a session can be
  resumed. A correction is a new row and the latest row wins.
- The design asked for two sessions by the same person at least 24 hours apart, with different
  random orders, as a disclosed bias. What was done
  for the committed dev labels is different: one AI labeller, session s1 at 08:07-08:12Z and
  session s2 at 08:34Z on 2026-10-17 (about 25 minutes apart), s2 an explicit revision of s1 after
  reading the public OpenStreetMap pages. In `dev.adjudicated.jsonl` 51 items are `agree` and 9 are
  `adjudicated` (the AI kept its web-verified pass). Model outputs for the dev ids (panel diagnostic
  receipts) were committed before s1, in the repository the labeller worked in. No person labelled.
- `spike` prints `NOT RUN: insufficient labels (n/60)` and writes no verdict until 60 dev items
  are adjudicated. Otherwise it writes `results/spike-<date>.md` with a one-line verdict.
- `uv run cso eval run --set fixtures` is a pipeline smoke test on synthetic fixtures. Its report
  is stamped `PIPELINE SMOKE TEST - SYNTHETIC - NOT A VERDICT` and is never a spike result.
- `run --set heldout` is refused without `--released`. Release it once, after the freeze commit.
  The runner re-verifies `heldout_ids.sha256` before touching the ids. These are checks in the
  command (flags and a marker file), not an access control.
- **The held-out ids are not unseen.** All 102 were sent through the Decider, label-free, by
  `panel-diagnostic` (results `panel-diagnostic-2026-10-17.json` and `-v2.json`, receipts committed).
  No labels were read or written and nothing was tuned on them. `panel-diagnostic --set heldout`
  (and `--set all` once the split is frozen) now needs `--include-heldout`, and the report header
  says the held-out ids were included.
- `ablate-model --set dev --decider-url <loopback url> --label <name>` asks a second Decider server
  the identical panel questions and writes `results/ablation-model-<label>-<date>.md` and an SVG
  chart next to the 2B run. It is limited to the dev set, refuses any server that is not on this
  machine, and repeats the label provenance. No run has been made yet.

## Rules the code enforces

- Every proportion is reported with a Wilson 95% interval; macro-F1 averages classes with support.
- Weak labels (MapRoulette status) are stored under `weak_mr_status` and never used as ground truth.
- Ambiguous items are excluded from accuracy and reported as a rate.
- The dev set is used for tuning and is never reported as validation.
- The spike gate was set after the smoke run, and its probe-accuracy condition is matched by a per-probe majority baseline (450/528 = 0.852 against the Decider's 353/413 = 0.855); see `results/spike-2026-10-17.md`.
- Committed files carry no display names, emails or evidence text; mappers are salted hashes.

The rule baseline (`baselines.py`) is v1: it reads the product policy rules (`domain/policy.py`) and no model output. The frozen split is dev 60 and held-out 102 (the candidate pool could not fill 120); see `evaluation/splits/split-meta.json`.
Fixtures and labels derived from OpenStreetMap are © OpenStreetMap contributors, ODbL 1.0.
