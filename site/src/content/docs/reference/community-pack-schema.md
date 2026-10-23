---
title: Community pack schema
description: The fields of a community pack file, with types and defaults.
---

*For admins and contributors. Reference.*

:::note[Generated page]
This page is written by `site/scripts/generate.mjs` from the `CommunityConfig` model in `backend/src/cso/domain/config.py`. Do not edit it by hand; change the code and rebuild.
:::

### CommunityConfig

Validated community configuration; `version` is the sha256 of the canonical YAML.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `bands` | Bands | yes |  |  |
| `calibration` | CalibrationRef, optional | no | `null` |  |
| `id` | text | yes |  | Id |
| `option_sets` | OptionSets | yes |  |  |
| `pack` | PackInfo, optional | no | `null` |  |
| `panel` | Panel | yes |  |  |
| `rules` | list of RuleConfig | yes |  | Rules |
| `tone` | Tone | yes |  |  |
| `version` | text | yes |  | Version |

### Bands

Provisional sharpness-band thresholds.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `confident_min` | number | yes |  | Confident Min |
| `order_sensitivity_max` | number | no | `0.3` | Order Sensitivity Max |
| `unsure_min` | number | yes |  | Unsure Min |

### CalibrationRef

The calibration whose thresholds are folded into this configuration, if any.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `id` | text | yes |  | Id |

### CompositionOptions

Options of the composition tables a community may switch (both off by default).

They never touch the rules or the parsed-fact floor: they only change which table row a
given set of readings lands on.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `newcomer_welcome_over_question` | yes or no | no | `false` | Newcomer Welcome Over Question |
| `p4_requires_both` | yes or no | no | `false` | P4 Requires Both |

### Option

One answer option of a Decider question, with UI/criteria text.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `code` | text | yes |  | Code |
| `description` | text | yes |  | Description |
| `label` | text | yes |  | Label |

### OptionSets

Option sets for Q1 (nature) and Q2 (response).

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `nature` | list of Option | yes |  | Nature |
| `response` | list of Option | yes |  | Response |

### PackInfo

Who a pack is for and who wrote it; shown in the pack list. Not used by the decision code.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `author` | text | yes |  | Author |
| `description` | text | yes |  | Description |
| `id` | text | yes |  | Id |
| `title` | text | yes |  | Title |
| `version` | text | yes |  | Version |

### Panel

Fact panel: the yes/no probe ids asked of the Decider and the tri-state thresholds.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `band` | PanelBand | no | `{"confident_max_unknown":1,"unsure_max_unknown":3}` |  |
| `composition` | CompositionOptions | no | `{"newcomer_welcome_over_question":false,"p4_requires_both":false}` |  |
| `noul_ids` | list of text | yes |  | Noul Ids |
| `probe_thresholds` | map of PanelThresholds | no |  | Probe Thresholds |
| `thresholds` | PanelThresholds | yes |  |  |

### PanelBand

Backend band from how many composed probes read `unknown` (cautious reading).

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `confident_max_unknown` | whole number | no | `1` | Confident Max Unknown |
| `unsure_max_unknown` | whole number | no | `3` | Unsure Max Unknown |

### PanelThresholds

Tri-state cut points for panel probabilities: below `low` no, above `high` yes.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `high` | number | yes |  | High |
| `low` | number | yes |  | Low |

### RuleConfig

Parameters of one deterministic policy rule.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `code` | text | yes |  | Code |
| `label` | text | yes |  | Label |
| `params` | map of | no |  | Params |

### Tone

Drafting tone constraints.

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `allowed_links` | list of text | yes |  | Allowed Links |
| `banned_words` | list of text | yes |  | Banned Words |
| `language_policy` | text | yes |  | Language Policy |
