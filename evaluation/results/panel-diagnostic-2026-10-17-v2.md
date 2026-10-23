# Fact-panel diagnostic (2026-10-17)

**PANEL DIAGNOSTIC - NO LABELS - NOT A VERDICT**

No labels are read or written here. Held-out ids appear only in these label-free statistics; thresholds (0.35 and 0.65) and the composition table were fixed before this run, and nothing is tuned on these numbers.

> **Correction added at the final review (2026-10-17).** The sentence above is not accurate for this run: the composition table was amended (ADR-009 Amendment 1, commit 60e90e9) after the first diagnostic had produced per-item output for all 102 held-out ids and before this rerun, so this run used a table changed after those outputs existed. The commit record does not show whether the first run's numbers influenced the amendment. This run again sent the held-out ids through the Decider and committed the answers; no labels were read, and the held-out items are not an untouched set. The config version hash is identical to the first run's because it covers the YAML only, not the code.

- Config version: `sha256:01ae6fdd985091161326815b8c3f73b8f3f00c285fe77db6d1987512fc60656e`; model: `strands-decider-2B-qwen3.5-v1-2610 (cuda)`; evidence profile: `compact`
- Split: frozen (dev and held-out files exist)
- Decision contract (ADR-009): ten yes/no probes read as no, unknown or yes at 0.35 and 0.65; the composed nature and response come from a fixed table over those readings plus the parsed rules; the four-way nature the model also answers is advisory and never used for lanes.

## Data

- Items: 162; answered: 162; Decider failures: 0

## Probe probabilities

Histogram counts are for ten equal bins from 0.0 to 1.0 (the last includes 1.0). `near 0.5` is a probability from 0.40 to 0.60; `unknown` is 0.35 to 0.65.

| Probe | n | Histogram (0.0 ... 1.0) | Near 0.5 | Unknown | Yes | No |
|---|---|---|---|---|---|---|
| mature_feature_deleted | 162 | 0 98 17 4 4 6 14 18 1 0 | 10/162 = 0.06 [0.03, 0.11] | 18/162 = 0.11 [0.07, 0.17] | 27/162 = 0.17 [0.12, 0.23] | 117/162 = 0.72 [0.65, 0.79] |
| nonsense_or_offensive_values | 162 | 0 111 43 6 1 1 0 0 0 0 | 2/162 = 0.01 [0.00, 0.04] | 4/162 = 0.02 [0.01, 0.06] | 0/162 = 0.00 [0.00, 0.02] | 158/162 = 0.98 [0.94, 0.99] |
| comment_matches_changes | 162 | 0 0 1 2 17 10 45 77 10 0 | 27/162 = 0.17 [0.12, 0.23] | 43/162 = 0.27 [0.20, 0.34] | 117/162 = 0.72 [0.65, 0.79] | 2/162 = 0.01 [0.00, 0.04] |
| conventions_followed | 162 | 0 0 25 17 14 27 71 8 0 0 | 41/162 = 0.25 [0.19, 0.33] | 87/162 = 0.54 [0.46, 0.61] | 41/162 = 0.25 [0.19, 0.33] | 34/162 = 0.21 [0.15, 0.28] |
| new_account_first_edits | 162 | 15 37 6 5 3 7 11 31 47 0 | 10/162 = 0.06 [0.03, 0.11] | 22/162 = 0.14 [0.09, 0.20] | 81/162 = 0.50 [0.42, 0.58] | 59/162 = 0.36 [0.29, 0.44] |
| deleted_own_recent_additions | 162 | 0 136 23 1 2 0 0 0 0 0 | 2/162 = 0.01 [0.00, 0.04] | 2/162 = 0.01 [0.00, 0.04] | 0/162 = 0.00 [0.00, 0.02] | 160/162 = 0.99 [0.96, 1.00] |
| real_world_change_claimed | 162 | 0 63 42 28 24 5 0 0 0 0 | 29/162 = 0.18 [0.13, 0.25] | 46/162 = 0.28 [0.22, 0.36] | 0/162 = 0.00 [0.00, 0.02] | 116/162 = 0.72 [0.64, 0.78] |
| discussion_cites_source | 162 | 83 73 6 0 0 0 0 0 0 0 | 0/162 = 0.00 [0.00, 0.02] | 0/162 = 0.00 [0.00, 0.02] | 0/162 = 0.00 [0.00, 0.02] | 162/162 = 1.00 [0.98, 1.00] |
| mass_retag_single_key | 162 | 3 134 8 8 3 4 0 2 0 0 | 7/162 = 0.04 [0.02, 0.09] | 12/162 = 0.07 [0.04, 0.13] | 2/162 = 0.01 [0.00, 0.04] | 148/162 = 0.91 [0.86, 0.95] |
| evidence_sufficient | 162 | 0 0 31 71 18 12 17 13 0 0 | 30/162 = 0.19 [0.13, 0.25] | 59/162 = 0.36 [0.29, 0.44] | 24/162 = 0.15 [0.10, 0.21] | 79/162 = 0.49 [0.41, 0.56] |

## Agreement with facts computed from parsed evidence

Informational: the policy rules decide, and these facts are exact for the question as worded (`mass_retag_single_key` is counted over the elements with details). Agreement is over items where the panel said yes or no.

| Probe | Agree | Disagree | Unknown | Not applicable | Agreement (Wilson 95%) |
|---|---|---|---|---|---|
| mature_feature_deleted | 144 | 0 | 18 | 0 | 144/144 = 1.00 [0.97, 1.00] |
| new_account_first_edits | 106 | 18 | 22 | 16 | 106/124 = 0.85 [0.78, 0.91] |
| mass_retag_single_key | 150 | 0 | 12 | 0 | 150/150 = 1.00 [0.98, 1.00] |
| evidence_sufficient | 35 | 68 | 59 | 0 | 35/103 = 0.34 [0.26, 0.44] |

## Composition (no labels, so these are counts and not accuracy)

- Nature: consistent_edit=8, likely_good_faith_mistake=80, needs_local_knowledge=62, possible_deliberate_damage=12
- Response: ask_source_question=36, escalate_to_experienced_reviewer=38, no_action_suggested=8, welcome_and_tips=80
- Lane: insufficient_evidence=17, looks_consistent=8, needs_local_knowledge=51, review_suggested=86
- Band: cannot_tell=16, confident=71, unsure=75
- Table rows (nature/response): N1/P1=12, N2/P1=26, N3/P4=80, N4/P5=8, N5/P6=36
- Advisory nature, top probability p50: 0.31

## Input size and latency

- Input tokens: p50 1514, p95 1949
- End to end: p50 1156 ms, p95 1238 ms (n=162)
- Server side: p50 612 ms, p95 688 ms

## Before vs after the edit-time count fix: `new_account_first_edits`

The evidence used to show the author's *current* changeset total. It now shows the
count at the time of the edit when the editor published it. Same items, same model,
same compact profile. Readings are the model's; the cross-check compares them with
the parsed fact.

Items present in both runs: 162. Reading changed: 19. Cross-check status changed: 37.

| | before | after |
|---|---|---|
| read yes | 77 | 81 |
| read unknown | 23 | 22 |
| read no | 62 | 59 |
| mean probability | 0.511 | 0.524 |
| agrees with the parsed fact | 121 | 106 |
| disagrees with the parsed fact | 17 | 18 |
| undecided (the model read unknown) | 23 | 22 |
| n/a (the parsed fact is unknown) | 1 | 16 |
| agreement among decided items | 121/138 (87.7%) | 106/124 (85.5%) |

Agreement is not accuracy: both sides come from the same evidence text. After the
fix the parsed fact is unknown for more items (n/a): a current total of 10 or more
cannot show the edit-time count was 10 or more, so those items no longer count as
agreements or disagreements. Unknown parsed facts are read cautiously in composition.

Caveat: if the two runs differ in anything besides the count (for example other
evidence-text changes made between them), the changes above cannot be attributed to
the count fix alone. Here they do differ: the first run predates Amendment 1 (the compact
summary gained a `deleted elements created by this account within 30 days` line), so the
reading changes in this section, and the movement of `evidence_sufficient` agreement from
0.51 to 0.34, mix both changes. A run with only the count reverted would separate them.
