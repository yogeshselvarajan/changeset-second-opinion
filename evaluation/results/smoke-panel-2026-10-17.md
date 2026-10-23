# Pipeline smoke test, fact panel (2026-10-17)

**PIPELINE SMOKE TEST - SYNTHETIC - NOT A VERDICT**

- Config version: `sha256:01ae6fdd985091161326815b8c3f73b8f3f00c285fe77db6d1987512fc60656e`; model: `strands-decider-2B-qwen3.5-v1-2610 (cuda)`
- Decision contract (ADR-009): ten yes/no probes read as no, unknown or yes at 0.35 and 0.65; the composed nature and response come from a fixed table over those readings plus the parsed rules; the four-way nature the model also answers is advisory and never used for lanes.

## Data

- Labelled items (probe labels): 6; scored for nature (non-ambiguous, Decider answered): 6; Decider failures: 0
- Ambiguous rate among labelled: 0/6 = 0.00 [0.00, 0.39]
- Labels here are synthetic hints from the fixtures' expected.json, not hand labels.

## Per-probe accuracy (gold yes or no only; gold unknown excluded)

| Probe | Gold n | Panel unknown | Accuracy when decided | Strict accuracy |
|---|---|---|---|---|
| mature_feature_deleted | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| nonsense_or_offensive_values | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| comment_matches_changes | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| conventions_followed | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| new_account_first_edits | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| real_world_change_claimed | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| discussion_cites_source | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| mass_retag_single_key | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |
| evidence_sufficient | 0 | n/a (n=0) | n/a (n=0) | n/a (n=0) |

Pooled accuracy when decided: n/a (n=0)

Strict accuracy counts an unknown reading as wrong; `unknown` is the cautious reading, so it costs coverage and never raises a lane.

## Nature (composed from the panel versus baselines)

| System | Macro-F1 | Accuracy (Wilson 95%) |
|---|---|---|
| Rule baseline v1 (policy rules) | 0.190 | 2/6 = 0.33 [0.10, 0.70] |
| Panel composed (decision input) | 0.822 | 5/6 = 0.83 [0.44, 0.97] |
| Model advisory nature (not used for lanes) | 0.556 | 4/6 = 0.67 [0.30, 0.90] |

Macro-F1 averages the classes that occur in the gold labels (support > 0).

## Input size and latency

- Input tokens: p50 1580, p95 1856
- End to end: p50 1135 ms, p95 1185 ms (n=6)
- Server side: p50 630 ms, p95 668 ms
