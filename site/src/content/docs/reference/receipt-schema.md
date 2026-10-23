---
title: Receipt schema
description: The fields of a decision receipt, with types and defaults.
---

*For operators and contributors. Reference.*

:::note[Generated page]
This page is written by `site/scripts/generate.mjs` from the `DecisionReceipt` model in `backend/src/cso/domain/receipt.py`. Do not edit it by hand; change the code and rebuild.
:::

### DecisionReceipt

Everything needed to audit or replay one decision. Immutable; corrections are new rows.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `aggregated` | map of AggregatedChoice | no |  | Aggregated |
| `band` | Band, optional | no | `null` |  |
| `case_id` | text, optional | no | `null` | Case Id |
| `config_version` | text | yes |  | Config Version |
| `coverage` | map of | yes |  | Coverage |
| `decider` | DeciderIdentity, optional | yes |  |  |
| `errors` | list of text | no |  | Errors |
| `evidence_version` | text | yes |  | Evidence Version |
| `human_outcome_ids` | list of text | no |  | Human Outcome Ids |
| `lane` | Lane, optional | no | `null` |  |
| `nouls` | map of number | no |  | Nouls |
| `panel` | FactPanel, optional | no | `null` |  |
| `panel_composition` | map of , optional | no | `null` | Panel Composition |
| `panel_cross_checks` | map of text, optional | no | `null` | Panel Cross Checks |
| `panel_questions_hash` | text, optional | no | `null` | Panel Questions Hash |
| `permutations` | list of PermutationResult | no |  | Permutations |
| `questions_hash` | text, optional | yes |  | Questions Hash |
| `receipt_version` | text | no | `"1"` | Receipt Version |
| `reconciliation` | ReconciliationRecord, optional | no | `null` |  |
| `rules_fired` | list of RuleHit | no |  | Rules Fired |
| `snapshot_id` | text, optional | no | `null` | Snapshot Id |
| `state_tokens` | whole number | no | `0` | State Tokens |
| `timing_ms` | map of whole number | no |  | Timing Ms |

### AdvisoryNature

The single-order nature choice; stored for audit and evaluation, never used for lanes.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `advisory` | `true` | no | `true` | Advisory |
| `choice` | text | yes |  | Choice |
| `confidence` | number | yes |  | Confidence |
| `order` | list of text | yes |  | Order |
| `probabilities` | map of number | yes |  | Probabilities |

### AggregatedChoice

Mean over permutations of one question: probabilities, argmax and sharpness statistics.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `argmax` | text | yes |  | Argmax |
| `confidence_agg` | number | yes |  | Confidence Agg |
| `order_sensitivity` | number | yes |  | Order Sensitivity |
| `probabilities` | map of number | yes |  | Probabilities |

### Band

Backend-assigned sharpness band of the model output.

One of confident, unsure, cannot_tell.

### DeciderIdentity

What `GET /health` said about the model that produced the answers.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `base_model` | text, optional | no | `null` | Base Model |
| `checkpoint` | text | yes |  | Checkpoint |
| `device` | text | yes |  | Device |
| `max_length` | whole number | yes |  | Max Length |
| `model` | text | yes |  | Model |
| `prefix_cache` | yes or no, optional | no | `null` | Prefix Cache |
| `server_git_sha` | text, optional | no | `null` | Server Git Sha |
| `temperature` | number, optional | no | `null` | Temperature |

### FactPanel

Validated panel answers: readings for every probe plus the advisory nature distribution.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `advisory_nature` | AdvisoryNature | yes |  |  |
| `high` | number | yes |  | High |
| `ids` | list of text | no |  | Ids |
| `low` | number | yes |  | Low |
| `readings` | map of NoulReading | yes |  | Readings |

### Lane

Suggested-disposition bucket used to order the queue (nothing is hidden).

One of looks_consistent, review_suggested, needs_local_knowledge, insufficient_evidence, rules_only.

### NoulReading

One panel probe: the model probability and its tri-state reading.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | text | yes |  | Id |
| `probability` | number | yes |  | Probability |
| `state` | Tri | yes |  |  |

### PermutationResult

One Decider choice answer for one option order (e.g. `nature_p0`).

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `confidence` | number | yes |  | Confidence |
| `name` | text | yes |  | Name |
| `order` | list of text | yes |  | Order |
| `probabilities` | map of number | yes |  | Probabilities |

### ReconciliationRecord

Q2 reconciliation against Q1; serialised with the key `from`.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `applied` | yes or no | yes |  | Applied |
| `from` | text, optional | no | `null` | From |
| `to` | text, optional | no | `null` | To |

### RuleHit

A deterministic policy rule that fired, with the parsed evidence that triggered it.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `code` | text | yes |  | Code |
| `label` | text | yes |  | Label |
| `severity` | Severity | yes |  |  |
| `triggered_by` | map of | no |  | Triggered By |

### Severity

Severity of a policy rule hit.

One of info, warn, block.

### Tri

A noul probability read against the panel thresholds.

One of no, unknown, yes.
