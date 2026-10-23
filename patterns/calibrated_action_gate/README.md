# Calibrated action gate

Hackathon pattern tag: `#policy`.

A small, application-independent pattern for letting a typed classifier (Strands Decider 2B) make a decision that code then acts on, without trusting a single number. The classifier answers fixed questions with probabilities; **your code** validates the answer, averages away option-order effects, reconciles disagreements with a deterministic table, assigns a confidence band, and records a receipt. A Strands hook can then refuse an agent's tool call unless the stored decision allows it.

It targets the `POST /v1/systemone` contract of `strands-decider` 0.1.0 (`strands-decider serve`). It does not run without a Decider server. It has no dependency on the `cso` application; the only runtime dependency is `httpx`.

## How this relates to the application in this repository

This package implements the first design of the application's decision: choice questions repeated in several option orders, averaged, then reconciled (ADR-004, independent questions with deterministic reconciliation). On the application's own sample the four-way choice was close to uniform and strongly order-sensitive, so the application's decision input moved to a panel of ten yes/no probes composed by a fixed table (ADR-009, the fact panel). The panel uses the same request format and strict validation as this package (yes/no probes are "nouls" here). The panel's composition table and the application's rules are application-specific and are **not** in this package. What you get here is the reusable part: the question builder, the validator, the aggregator, the band, the consistency table helper, the receipt, the clients, and the hook idea. Treat the permutation averaging as a way to reduce order effects, not as proof that a choice is right.

## What it does

1. **Questions** (`questions.py`): builds one request holding every question you ask. Each choice question is repeated in `K` option orders (cyclic rotations, so each option takes a different position), plus optional yes/no probes. Question text and criteria come only from your option sets; evidence goes only into `state`.
2. **Validation** (`validate.py`): rejects any deviation: a missing or extra option, probabilities not summing to 1 within 1e-3, a `choice` that is not the argmax, a confidence or probe value outside [0, 1], a missing or unexpected answer or field. It never repairs or defaults an answer; the error keeps the raw response.
3. **Aggregation** (`aggregate.py`): mean probability per option, `order_sensitivity` (the largest pairwise L1 distance between permutations), `confidence_agg = (N * max(p) - 1) / (N - 1)`, and a `band()` helper.
4. **Consistency** (`consistency.py`): a table of which responses are allowed for each class and a deterministic `reconcile()`. The gate, not the model, enforces consistency.
5. **Receipt** (`receipt.py`): every permutation, order, aggregate and timing as JSON.
6. **Client** (`client.py`): sync and async. One retry on connection errors; never on a 422 or a timeout.

## Usage

```python
from calibrated_action_gate import ChoiceSpec, DeciderClient, NoulSpec, decide, band, reconcile

nature = ChoiceSpec("nature", "Pick the description that best matches.", {"a": "...", "b": "...", "c": "..."})
result = decide(DeciderClient("http://127.0.0.1:8099"), "<evidence text>", [nature], [NoulSpec("probe", "True if ...")])
agg = result.aggregates["nature"]
print(agg.argmax, band(max(agg.probabilities.values()), agg.order_sensitivity))
print(result.receipt.to_json())
```

Start the server first: `strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --host 127.0.0.1 --port 8099 --device cuda` (or `cpu`). Keep it on loopback: its `serve` command has no authentication option.

## The typed questions and option sets

You supply the option sets. Each `ChoiceSpec` is a name, one fixed instruction, and an ordered mapping from option code to a plain-language description. Descriptions are the model's only definition of each option, so write them as criteria, avoid loaded words, and keep them constant (never build them from user-supplied text).

The application's early design used two choice questions, which show the shape:

| Question | Options |
|---|---|
| nature of the edit | `consistent_edit`, `likely_good_faith_mistake`, `possible_deliberate_damage`, `needs_local_knowledge` |
| suggested response | `no_action_suggested`, `welcome_and_tips`, `ask_source_question`, `request_local_check`, `escalate_to_experienced_reviewer` |

and a table of the responses allowed for each nature (`ALLOWED_RESPONSES` in `consistency.py`), so that a response that does not fit the nature is replaced by the best allowed one and flagged as reconciled.

## Adapting it to your domain

1. Write your option sets as `ChoiceSpec` objects (and any yes/no facts as `NoulSpec`). Keep the number of options small; more options means a flatter distribution.
2. Replace `ALLOWED_RESPONSES` with your own table, or pass your mapping as the `allowed` argument of `reconcile()`.
3. Set band thresholds for your data: `band()` defaults to 0.80 for `confident`, 0.50 for `unsure`, and an order-sensitivity ceiling of 0.30. Those are provisional starting points, not calibrated values. Fit them on labelled data of your own.
4. Put only evidence in `state`. Escape or quote untrusted text before it goes in, and tell the reader of the receipt which text was untrusted.
5. Decide, in code, which signals should never be a model answer (the application's policy rules read parsed counts and ages, and a model answer is only allowed to make an outcome more cautious).

## Wiring a Strands hook

Store the decision, then let a hook refuse a tool call that the decision does not allow. This example was run against Strands Agents 1.61.1 (the gate logic with a stand-in event; it makes no model call):

```python
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry


class DecisionGate(HookProvider):
    """Cancel the tool call unless the stored decision allows the requested action."""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        args = event.tool_use.get("input") or {}
        action = str(args.get("action", "")) if isinstance(args, dict) else ""
        if action not in self.allowed:
            event.cancel_tool = f"The stored decision does not allow '{action}'."


@tool
def act(action: str) -> str:
    """Carry out the action (for example, draft a message for a person to review)."""
    return f"drafted: {action}"


allowed = {"welcome_and_tips"}          # taken from your stored, reconciled decision
agent = Agent(tools=[act], hooks=[DecisionGate(allowed)])
```

Keep the tool surface small (one tool is easiest to reason about), read the allowed set from stored data rather than from model output, and have the tool produce something a person reviews, not an irreversible action.

## The receipt

`Receipt.to_json()` is canonical JSON (sorted keys), so equal receipts serialise identically. Fields:

| Field | Meaning |
|---|---|
| `receipt_version` | Schema version, currently `"1"` |
| `decider` | Identity of the model server as reported by `/health` |
| `questions_hash` | Hash of the question set, so changed criteria are detectable |
| `state_tokens` | Input size the server reported |
| `permutations` | For each asked question: `name`, `order`, `probabilities`, `confidence` |
| `aggregated` | Per choice question: argmax, mean probabilities, order sensitivity, aggregate confidence |
| `nouls` | Yes/no probe probabilities |
| `timing_ms` | Timings of the stages |
| `errors` | Any recorded problems |

## What the numbers mean

`probabilities` is the model's softmax over your option labels. `confidence` rescales the top probability from the uniform floor to 1: it says how decisive the output is, **not** how likely the chosen option is correct. Averaging over option orders reduces order-induced variance; it does not recalibrate. Only your own labelled data turns sharpness into accuracy, so treat any band threshold as provisional.

## Observed on a real server (L4 GPU, `strands-decider-2B-qwen3.5-v1-2610`)

- Option order matters: the same question in different criteria orders gave different vectors, and on synthetic cases the top option changed between orders in several of them. That is the reason for permutations and for treating high `order_sensitivity` as "cannot tell".
- One 8-question request (about 1,600 input tokens) took about 0.44 s server side.
- `/health` reports `temperature` as a single number, and responses carry a top-level `latency_ms` that is not in the OpenAPI schema; the validator accepts exactly that one extra field.

## Dependencies

- Runtime: `httpx>=0.27`, Python 3.11 or newer.
- A running `strands-decider` server (the HTTP contract of version 0.1.0). Its Python package pulls in PyTorch and downloads about 4.5 GB of model weights on first start.
- For the hook example only: `strands-agents` 1.61 or newer. The package itself does not import it.
- Nothing from the `cso` application.

## Writing a pack for your community

The application the pattern comes from keeps its settings in a community pack: one YAML file in `config/communities/`. A pack changes thresholds, rules and tone. It cannot change how a reading becomes an action beyond two switches, and it cannot remove a safety floor. To write one, copy `default.yaml`, change the `id`, and edit the parts below.

```yaml
id: my-community              # lower case letters, digits and hyphens; equals pack.id
pack:
  id: my-community
  title: My community
  description: One or two sentences on who the pack is for.
  author: Your name or group
  version: "1.0"
option_sets: {}               # keep the codes; reword labels and descriptions if you must
bands: { confident_min: 0.80, unsure_min: 0.50, order_sensitivity_max: 0.30 }
panel:
  noul_ids: []                # keep the ten ids the application asks
  thresholds: { low: 0.35, high: 0.65 }
  band: { confident_max_unknown: 1, unsure_max_unknown: 3 }
  composition:                # both off unless you switch them on
    p4_requires_both: false
    newcomer_welcome_over_question: false
rules: []                     # R1 to R6, with your own numbers in params
tone:
  language_policy: mapper_language_else_english
  allowed_links: [https://wiki.openstreetmap.org/]
  banned_words: [vandal, vandalism, spam, illegal, stop, must]
```

Three things the loader refuses: a file whose `pack.id` differs from `id`, two files with the same id, and a `banned_words` list that drops a word of the built-in minimum. You may add words, never remove them.

The version of a pack is a hash of the whole file and of the composition code, so any edit makes a new version. An admin switches packs on the Config page after reading a list of every setting that would change. Runs already made keep the version they used, and each receipt names its pack.

## Tests

`uv run pytest -q` runs against a response recorded from a real server (synthetic input) and needs no network. The recorded files are in `tests/fixtures/`.

## Limits

Targets `strands-decider` 0.1.0. A schema change in a later version needs the validator updated, and the strictness is deliberate. Not tied to any domain: bring your own option sets. The package does not contain the application's fact panel or its rules; it also does not decide whether a model is accurate enough for your task. Measure that on labelled data before you rely on it.

Licence: Apache-2.0.
