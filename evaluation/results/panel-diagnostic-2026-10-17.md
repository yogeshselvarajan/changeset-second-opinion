# Fact-panel diagnostic (2026-10-17)

**PANEL DIAGNOSTIC - NO LABELS - NOT A VERDICT**

No labels are read or written here. Held-out ids appear only in these label-free statistics; thresholds (0.35 and 0.65) and the composition table were fixed before this run, and nothing is tuned on these numbers.

> **Correction added at the final review (2026-10-17).** This run sent all 102 held-out ids (and the 60 dev ids) through the Decider and committed the per-item answers (`panel-diagnostic-2026-10-17.json`, `receipts/`). It read no labels and nothing was tuned on these numbers, but it means the held-out items were seen by the model before any held-out evaluation: they are not an untouched set. The composition table was fixed at the time of this run; ADR-009 Amendment 1 changed it afterwards (commit 60e90e9). The config version hash covers the YAML only, so it does not distinguish the code before and after that amendment.

- Config version: `sha256:01ae6fdd985091161326815b8c3f73b8f3f00c285fe77db6d1987512fc60656e`; model: `strands-decider-2B-qwen3.5-v1-2610 (cuda)`; evidence profile: `compact`
- Split: not frozen yet; all candidate items are used
- Decision contract (ADR-009): ten yes/no probes read as no, unknown or yes at 0.35 and 0.65; the composed nature and response come from a fixed table over those readings plus the parsed rules; the four-way nature the model also answers is advisory and never used for lanes.

## Data

- Items: 162; answered: 162; Decider failures: 0

## Probe probabilities

Histogram counts are for ten equal bins from 0.0 to 1.0 (the last includes 1.0). `near 0.5` is a probability from 0.40 to 0.60; `unknown` is 0.35 to 0.65.

| Probe | n | Histogram (0.0 ... 1.0) | Near 0.5 | Unknown | Yes | No |
|---|---|---|---|---|---|---|
| mature_feature_deleted | 162 | 0 86 21 8 6 10 15 14 2 0 | 16/162 = 0.10 [0.06, 0.15] | 25/162 = 0.15 [0.11, 0.22] | 25/162 = 0.15 [0.11, 0.22] | 112/162 = 0.69 [0.62, 0.76] |
| nonsense_or_offensive_values | 162 | 0 115 40 5 1 1 0 0 0 0 | 2/162 = 0.01 [0.00, 0.04] | 5/162 = 0.03 [0.01, 0.07] | 0/162 = 0.00 [0.00, 0.02] | 157/162 = 0.97 [0.93, 0.99] |
| comment_matches_changes | 162 | 0 0 1 3 16 14 44 79 5 0 | 30/162 = 0.19 [0.13, 0.25] | 48/162 = 0.30 [0.23, 0.37] | 112/162 = 0.69 [0.62, 0.76] | 2/162 = 0.01 [0.00, 0.04] |
| conventions_followed | 162 | 0 0 28 14 16 26 70 8 0 0 | 42/162 = 0.26 [0.20, 0.33] | 81/162 = 0.50 [0.42, 0.58] | 46/162 = 0.28 [0.22, 0.36] | 35/162 = 0.22 [0.16, 0.29] |
| new_account_first_edits | 162 | 19 36 4 3 3 14 11 27 45 0 | 17/162 = 0.10 [0.07, 0.16] | 23/162 = 0.14 [0.10, 0.20] | 77/162 = 0.48 [0.40, 0.55] | 62/162 = 0.38 [0.31, 0.46] |
| deleted_own_recent_additions | 162 | 0 71 82 7 1 1 0 0 0 0 | 2/162 = 0.01 [0.00, 0.04] | 5/162 = 0.03 [0.01, 0.07] | 0/162 = 0.00 [0.00, 0.02] | 157/162 = 0.97 [0.93, 0.99] |
| real_world_change_claimed | 162 | 0 53 50 32 21 6 0 0 0 0 | 27/162 = 0.17 [0.12, 0.23] | 47/162 = 0.29 [0.23, 0.36] | 0/162 = 0.00 [0.00, 0.02] | 115/162 = 0.71 [0.64, 0.77] |
| discussion_cites_source | 162 | 89 68 5 0 0 0 0 0 0 0 | 0/162 = 0.00 [0.00, 0.02] | 0/162 = 0.00 [0.00, 0.02] | 0/162 = 0.00 [0.00, 0.02] | 162/162 = 1.00 [0.98, 1.00] |
| mass_retag_single_key | 162 | 2 133 12 6 2 5 1 1 0 0 | 7/162 = 0.04 [0.02, 0.09] | 11/162 = 0.07 [0.04, 0.12] | 2/162 = 0.01 [0.00, 0.04] | 149/162 = 0.92 [0.87, 0.95] |
| evidence_sufficient | 162 | 0 0 17 61 36 14 17 17 0 0 | 50/162 = 0.31 [0.24, 0.38] | 93/162 = 0.57 [0.50, 0.65] | 27/162 = 0.17 [0.12, 0.23] | 42/162 = 0.26 [0.20, 0.33] |

## Agreement with facts computed from parsed evidence

Informational: the policy rules decide, and these facts are exact for the question as worded (`mass_retag_single_key` is counted over the elements with details). Agreement is over items where the panel said yes or no.

| Probe | Agree | Disagree | Unknown | Not applicable | Agreement (Wilson 95%) |
|---|---|---|---|---|---|
| mature_feature_deleted | 136 | 1 | 25 | 0 | 136/137 = 0.99 [0.96, 1.00] |
| new_account_first_edits | 121 | 17 | 23 | 1 | 121/138 = 0.88 [0.81, 0.92] |
| mass_retag_single_key | 151 | 0 | 11 | 0 | 151/151 = 1.00 [0.98, 1.00] |
| evidence_sufficient | 35 | 34 | 93 | 0 | 35/69 = 0.51 [0.39, 0.62] |

## Composition (no labels, so these are counts and not accuracy)

- Nature: consistent_edit=11, likely_good_faith_mistake=76, needs_local_knowledge=64, possible_deliberate_damage=11
- Response: ask_source_question=37, escalate_to_experienced_reviewer=38, no_action_suggested=11, welcome_and_tips=76
- Lane: insufficient_evidence=17, looks_consistent=11, needs_local_knowledge=51, review_suggested=83
- Band: cannot_tell=11, confident=94, unsure=57
- Table rows (nature/response): N1/P1=11, N2/P1=27, N3/P4=76, N4/P5=11, N5/P6=37
- Advisory nature, top probability p50: 0.32

## Input size and latency

- Input tokens: p50 1501, p95 1926
- End to end: p50 1140 ms, p95 1215 ms (n=162)
- Server side: p50 622 ms, p95 692 ms
