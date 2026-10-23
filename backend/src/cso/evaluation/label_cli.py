"""Interactive labelling and adjudication prompts.

The labeller sees the rendered evidence only: no model output, no weak labels, no rule results.
This module must never import the Decider, the runner or the baselines (a test enforces it).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from cso.domain.config import CommunityConfig
from cso.domain.evidence import render
from cso.domain.models import EvidenceSnapshot
from cso.domain.panel import PANEL_INSTRUCTIONS
from cso.evaluation.labels import (
    LABELLED_PROBES,
    NATURE_LABELS,
    RESPONSE_LABELS,
    LabelRow,
    LabelStore,
    session_order,
)

InputFn = Callable[[str], str]
PrintFn = Callable[[str], None]
SnapshotLookup = Callable[[int], EvidenceSnapshot]

RUBRIC = (
    "Rubric: pick the label that best describes the changeset from the evidence shown. "
    "Choose 'ambiguous' when the evidence does not let you decide."
)


def _menu(title: str, labels: Sequence[str]) -> str:
    rows = "  ".join(f"{i}={label}" for i, label in enumerate(labels, start=1))
    return f"{title}: {rows}"


def ask_choice(
    title: str,
    labels: Sequence[str],
    *,
    input_fn: InputFn,
    print_fn: PrintFn,
    extra: dict[str, str] | None = None,
) -> str:
    """Ask for a 1-based number (or one of `extra` keys, returned verbatim) until valid."""
    print_fn(_menu(title, labels))
    while True:
        answer = input_fn("> ").strip().lower()
        if extra and answer in extra:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(labels):
            return labels[int(answer) - 1]
        print_fn(f"enter 1-{len(labels)}" + (f" or {', '.join(extra)}" if extra else ""))


def label_session(
    *,
    store: LabelStore,
    ids: Sequence[int],
    snapshots: SnapshotLookup,
    config: CommunityConfig,
    labeller: str,
    session: str,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
    limit: int | None = None,
) -> int:
    """Label pending items in this session's randomized order; returns how many were labelled.

    Items already labelled in this (labeller, session) are skipped, so a session can be resumed.
    Typing `s` skips an item for now; `q` ends the session.
    """
    done = store.effective(labeller, session)
    pending = [cs for cs in session_order(ids, session) if cs not in done]
    total = len(ids)
    labelled = 0
    print_fn(RUBRIC)
    for cs in pending:
        if limit is not None and labelled >= limit:
            break
        rendered = render(snapshots(cs), config)
        print_fn(f"\n=== item {total - len(pending) + labelled + 1}/{total} (changeset {cs}) ===")
        print_fn(rendered.text)
        print_fn("")
        nature = ask_choice(
            "Nature",
            NATURE_LABELS,
            input_fn=input_fn,
            print_fn=print_fn,
            extra={"s": "skip", "q": "quit"},
        )
        if nature == "q":
            break
        if nature == "s":
            continue
        response = ask_choice("Response", RESPONSE_LABELS, input_fn=input_fn, print_fn=print_fn)
        store.append(
            changeset_id=cs, labeller=labeller, session=session, nature=nature, response=response
        )
        labelled += 1
    print_fn(f"labelled {labelled} item(s) this run; {len(pending) - labelled} pending")
    return labelled


def adjudication_prompt(
    *,
    snapshots: SnapshotLookup,
    config: CommunityConfig,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
) -> Callable[[int, LabelRow, LabelRow], tuple[str, str]]:
    """A `decide` callback for `labels.adjudicate`: show evidence and both labels, ask for one."""

    def decide(cs: int, a: LabelRow, b: LabelRow) -> tuple[str, str]:
        print_fn(f"\n=== disagreement on changeset {cs} ===")
        print_fn(render(snapshots(cs), config).text)
        print_fn(f"\nsession A: nature={a.nature} response={a.response}")
        print_fn(f"session B: nature={b.nature} response={b.response}")
        print_fn("Enter the final labels ('ambiguous' keeps the item out of accuracy).")
        nature = ask_choice("Nature", NATURE_LABELS, input_fn=input_fn, print_fn=print_fn)
        response = ask_choice("Response", RESPONSE_LABELS, input_fn=input_fn, print_fn=print_fn)
        return nature, response

    return decide


# ------------------------------------------------------------------ fact-panel labelling (v2)

PANEL_RUBRIC = (
    "Rubric: answer each question about the changeset from the evidence shown. Use yes or no "
    "when the evidence settles it and unknown when it does not. Pick the nature that best "
    "describes the changeset, or 'ambiguous' when the evidence does not let you decide."
)
_PROBE_KEYS = {
    "y": "yes",
    "yes": "yes",
    "n": "no",
    "no": "no",
    "u": "unknown",
    "unknown": "unknown",
}


def ask_probe(question: str, *, input_fn: InputFn, print_fn: PrintFn) -> str:
    """Ask one yes/no/unknown question; accepts y, n, u (or the words, or 1, 2, 3)."""
    print_fn(f"- {question}  [y=yes n=no u=unknown]")
    numbered = {"1": "yes", "2": "no", "3": "unknown"}
    while True:
        answer = input_fn("> ").strip().lower()
        if answer in _PROBE_KEYS:
            return _PROBE_KEYS[answer]
        if answer in numbered:
            return numbered[answer]
        print_fn("enter y, n or u")


def label_panel_session(
    *,
    store: LabelStore,
    ids: Sequence[int],
    snapshots: SnapshotLookup,
    config: CommunityConfig,
    labeller: str,
    session: str,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
    limit: int | None = None,
) -> int:
    """Label pending items with a nature and a yes/no/unknown answer for every composed probe.

    The text shown is the compact rendering the Decider also reads, followed by the probe
    questions. No model output, rule results or weak labels are shown. Resumable per session; `q`
    at the nature prompt ends the session and `s` skips an item for now.
    """
    done = store.effective(labeller, session)
    pending = [cs for cs in session_order(ids, session) if cs not in done]
    total = len(ids)
    labelled = 0
    print_fn(PANEL_RUBRIC)
    for cs in pending:
        if limit is not None and labelled >= limit:
            break
        rendered = render(snapshots(cs), config, profile="compact")
        print_fn(f"\n=== item {total - len(pending) + labelled + 1}/{total} (changeset {cs}) ===")
        print_fn(rendered.text)
        print_fn("")
        nature = ask_choice(
            "Nature",
            NATURE_LABELS,
            input_fn=input_fn,
            print_fn=print_fn,
            extra={"s": "skip", "q": "quit"},
        )
        if nature == "q":
            break
        if nature == "s":
            continue
        probes: dict[str, str] = {}
        for probe_id in LABELLED_PROBES:
            probes[probe_id] = ask_probe(
                PANEL_INSTRUCTIONS[probe_id], input_fn=input_fn, print_fn=print_fn
            )
        store.append(
            changeset_id=cs, labeller=labeller, session=session, nature=nature, probes=probes
        )
        labelled += 1
    print_fn(f"labelled {labelled} item(s) this run; {len(pending) - labelled} pending")
    return labelled


def adjudication_prompt_probes(
    *,
    snapshots: SnapshotLookup,
    config: CommunityConfig,
    input_fn: InputFn = input,
    print_fn: PrintFn = print,
) -> Callable[[int, LabelRow, LabelRow], tuple[str, dict[str, str]]]:
    """A `decide_probes` callback: show evidence and both labels, re-ask only differing fields."""

    def decide(cs: int, a: LabelRow, b: LabelRow) -> tuple[str, dict[str, str]]:
        print_fn(f"\n=== disagreement on changeset {cs} ===")
        print_fn(render(snapshots(cs), config, profile="compact").text)
        nature = a.nature
        if a.nature != b.nature:
            print_fn(f"\nsession A nature={a.nature}; session B nature={b.nature}")
            nature = ask_choice("Nature", NATURE_LABELS, input_fn=input_fn, print_fn=print_fn)
        probes = dict(a.probes)
        for probe_id in LABELLED_PROBES:
            if a.probes.get(probe_id) == b.probes.get(probe_id):
                continue
            print_fn(f"\nsession A: {a.probes.get(probe_id)}; session B: {b.probes.get(probe_id)}")
            probes[probe_id] = ask_probe(
                PANEL_INSTRUCTIONS[probe_id], input_fn=input_fn, print_fn=print_fn
            )
        return nature, probes

    return decide
