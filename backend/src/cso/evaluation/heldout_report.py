"""Markdown for the held-out results (rendered from the results JSON, so it can be re-rendered).

Every proportion goes through `pct` (k/n = value [Wilson 95% interval]); an empty denominator is
printed as undefined, never as a rate of zero. Without gold labels the report contains counts and
label-free shares only, and says so; the words accuracy and F1 appear only in the scored sections.
There is no verdict or go/no-go line: the held-out run reports numbers, it is not a gate.
"""

from __future__ import annotations

from typing import Any, Final

from cso.evaluation.report import pct
from cso.evaluation.stats import Proportion, wilson_interval

NO_GOLD: Final = "no gold labels: only label-free statistics"

DISCLOSURE: Final = (
    "Disclosure. This project was built with AI coding assistance (Claude). The Strands Decider "
    "checkpoint is experimental: it is used as shipped and its temperature was not fitted on our "
    "data. The labels line above says who produced the gold labels; where it says AI-ONLY, no "
    "person labelled or adjudicated them, and every number scored against them is indicative "
    "only and not human-validated. The dev set was used for tuning (probe wording, thresholds and "
    "the composition table) and is never reported as validation. This held-out set was frozen "
    "before tuning ended, was evaluated once, and nothing was changed after seeing these results. "
    "Weak labels (MapRoulette status and tool flags) are never used as ground truth. The system "
    "never writes to OpenStreetMap: every call to OpenStreetMap is a read-only GET and a person "
    "posts any comment. Cost figures are estimates from catalogue prices that were not verified "
    "against the live pricing pages."
)


def prop(raw: dict[str, Any] | None) -> Proportion | None:
    """A stored proportion dict back into a `Proportion` (None stays None)."""
    if raw is None:
        return None
    return Proportion(k=raw["k"], n=raw["n"], lower=raw["lower"], upper=raw["upper"])


def rate(raw: dict[str, Any] | None, *, missing: str = "needs gold labels") -> str:
    """A rate with its interval; undefined (n=0) is stated, never shown as 0."""
    p = prop(raw)
    if p is None:
        return missing
    if p.n == 0:
        return "undefined (n=0)"
    return pct(p)


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.5f}"


def _num(value: float | None, fmt: str = "{:.2f}") -> str:
    return "n/a" if value is None else fmt.format(value)


def _systems_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| System | What it is | Status | Answered | Note |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        status = "NOT RUN" if row["status"] == "not run" else row["status"]
        answered = f"{row['n_answered']}/{row['n_items']}" if row["status"] != "not run" else "-"
        note = row.get("reason") or ""
        errors = row.get("n_errors", 0)
        if errors and row["status"] != "not run":
            note = (note + f" {errors} unanswered").strip()
        lines.append(f"| {row['name']} | {row['description']} | {status} | {answered} | {note} |")
    return lines


def _scored_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| System | Scored n | Macro-F1 | Accuracy (Wilson 95%) |",
        "|---|---|---|---|",
    ]
    for row in rows:
        scored = row.get("scored")
        if scored is None:
            continue
        lines.append(
            f"| {row['name']} | {scored['n']} | {scored['macro_f1']:.3f} | "
            f"{rate(scored['accuracy'])} |"
        )
    return lines


def _count_shares(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["| System | Answer | Share of answered (Wilson 95%) |", "|---|---|---|"]
    for row in rows:
        if row["status"] == "not run" or not row["n_answered"]:
            continue
        total = row["n_answered"]
        for label, count in sorted(row["nature_counts"].items()):
            share = {"k": count, "n": total, **_wilson(count, total)}
            lines.append(f"| {row['name']} | {label} | {rate(share)} |")
    return lines


def _wilson(k: int, n: int) -> dict[str, float]:
    lower, upper = wilson_interval(k, n)
    return {"lower": lower, "upper": upper}


def _share_lines(title: str, counts: dict[str, int], total: int) -> list[str]:
    if not counts or total == 0:
        return []
    lines = [f"- {title}:"]
    for label, k in sorted(counts.items()):
        lines.append(f"  - {label}: {rate({'k': k, 'n': total, **_wilson(k, total)})}")
    return lines


def render_heldout(payload: dict[str, Any]) -> str:
    """The held-out report for one results payload."""
    labels = payload["labels"]
    scored_mode = labels["mode"] == "scored"
    systems: list[dict[str, Any]] = payload["systems"]
    ablations: list[dict[str, Any]] = payload["ablations"]
    diag = payload["diagnostic"]
    lines = [
        f"# Held-out evaluation ({payload['date']})",
        "",
        labels["provenance"] if scored_mode and labels["provenance"] else NO_GOLD,
        "",
        f"- Freeze commit `{payload['freeze_commit']}`; HEAD when run `{payload['head_commit']}`; "
        f"held-out ids sha256 `{payload['heldout_sha256']}`",
        f"- Items: {payload['n_items']}; gold labels: {labels['gold_items']}; "
        f"config `{payload['config_version']}`; model `{payload['model']}`; "
        f"evidence profile {payload['profile']}",
        "- This run happened once, after the freeze. Nothing was tuned on these items.",
        "",
        "## Systems and ablations attempted",
        "",
        *_systems_table(systems + ablations),
        "",
    ]
    if scored_mode:
        lines += [
            "## Nature, scored against the gold labels",
            "",
            *_scored_table(systems + ablations),
            "",
            "Macro-F1 averages the classes present in the gold labels (support above 0); "
            "ambiguous items are excluded and unanswered items are not scored.",
            "",
        ]
        summary = payload.get("panel_summary")
        if summary:
            lines += [
                "## Product panel, per probe (gold yes or no only)",
                "",
                "| Probe | Gold n | Panel unknown | When decided | Strict |",
                "|---|---|---|---|---|",
            ]
            for probe in summary["probes"]:
                lines.append(
                    f"| {probe['probe']} | {probe['n_gold']} | {rate(probe['panel_unknown'])} | "
                    f"{rate(probe['accuracy_decided'])} | {rate(probe['accuracy_strict'])} |"
                )
            lines += [
                "",
                f"Pooled when decided: {rate(summary['pooled_decided'])}",
                "",
                "### Composed nature per class",
                "",
                "| Class | Support | Precision | Recall |",
                "|---|---|---|---|",
            ]
            for cls in summary["composed_nature"]["per_class"]:
                lines.append(
                    f"| {cls['label']} | {cls['support']} | {rate(cls['precision'])} | "
                    f"{rate(cls['recall'])} |"
                )
            lines.append("")
    else:
        lines += [
            "## Answers without labels",
            "",
            "Counts and shares only; none of these numbers measures correctness.",
            "",
            *_count_shares(systems + ablations),
            "",
        ]
    n_answered = diag["n_answered"]
    lines += [
        "## Product path without labels",
        "",
        f"- Answered {n_answered} of {diag['n_items']} items; failures {diag['n_failures']}.",
        *_share_lines("Lanes", diag["lane_counts"], n_answered),
        *_share_lines("Bands", diag["band_counts"], n_answered),
        "",
        "## Harmful recommendations, rules on and off",
        "",
        payload["harm"]["definition"],
        "",
        "| System | Rules | Rule-eligible (R1 or R3) | Gold damage | Either | Unanswered |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["harm"]["rows"]:
        lines.append(
            f"| {row['system']} | {row['rules']} | {rate(row['rule_eligible'])} | "
            f"{rate(row['gold_damage'])} | {rate(row['union'])} | {row['unanswered']} |"
        )
    cost, avoided = payload["cost"], payload["calls_avoided"]
    lines += [
        "",
        "## Cost and Bedrock calls (estimates)",
        "",
        f"- Product path, GPU compute per review: {_money(cost['product_gpu_usd_per_review'])} "
        f"(n={cost['n_product']}); host price ${cost['host_usd_per_hour']:.3f} per hour",
        f"- Haiku decision per review: {_money(cost['haiku_usd_per_review'])} "
        f"(n={cost['n_haiku']}); Decider-removed application: "
        f"{_money(cost['decider_removed_usd_per_review'])}",
        f"- Bedrock decision calls avoided: {avoided['decision_calls_avoided']} of "
        f"{avoided['baseline_decision_calls']} (the product path asks Bedrock nothing to decide)",
        f"- Items that need no Bedrock call at all: {avoided['items_needing_no_bedrock_call']}; "
        f"upper bound on draft calls, made only when a reviewer asks: {avoided['max_draft_calls']}",
        f"- {cost['note']}",
    ]
    pairs = payload.get("paraphrase_agreement") or []
    if pairs:
        lines += [
            "",
            "## Wording stability (agreement between instruction variants)",
            "",
            "| Variant A | Variant B | Items | Same reading, per probe | Cohen's kappa | "
            "Same composed nature | Cohen's kappa |",
            "|---|---|---|---|---|---|---|",
        ]
        for a in pairs:
            lines.append(
                f"| {a['a']} | {a['b']} | {a['items']} | {rate(a['probe_agreement'])} | "
                f"{_num(a['probe_kappa'])} | {rate(a['nature_agreement'])} | "
                f"{_num(a['nature_kappa'])} |"
            )
    lat = diag["latency"]
    lines += [
        "",
        "## Input size and latency",
        "",
        f"- Input tokens: p50 {_num(diag['input_tokens_p50'], '{:.0f}')}, "
        f"p95 {_num(diag['input_tokens_p95'], '{:.0f}')}",
        f"- End to end: p50 {_num(lat['p50'], '{:.0f}')} ms, p95 {_num(lat['p95'], '{:.0f}')} ms",
        f"- Server side: p50 {_num(lat['server_p50'], '{:.0f}')} ms, "
        f"p95 {_num(lat['server_p95'], '{:.0f}')} ms",
        "",
        payload["disclosure"],
        "",
    ]
    return "\n".join(lines)
