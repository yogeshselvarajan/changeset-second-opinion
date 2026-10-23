"""Markdown rendering of run and spike summaries (every proportion shown with its Wilson CI)."""

from __future__ import annotations

from cso.evaluation.spike import (
    CANNOT_TELL_BELOW,
    F1_MARGIN,
    REQUIRED_LABELS,
    TOP_THIRD_LOWER_BOUND,
    Gate,
    Summary,
    not_run_line,
    verdict_line,
)
from cso.evaluation.stats import Proportion

SMOKE_BANNER = "PIPELINE SMOKE TEST - SYNTHETIC - NOT A VERDICT"
DEV_NOTE = "The dev set is used for tuning and is never reported as validation."
LABEL_NOTE = (
    "Gold labels are hand labels by the authors, adjudicated; weak labels (MapRoulette status) "
    "are never used as ground truth."
)


def pct(p: Proportion) -> str:
    """`k/n = 0.xx [lo, hi]` with the Wilson 95% interval."""
    if p.n == 0:
        return "n/a (n=0)"
    return f"{p.k}/{p.n} = {p.k / p.n:.2f} [{p.lower:.2f}, {p.upper:.2f}]"


def _num(value: float | None, fmt: str = "{:.2f}") -> str:
    return "n/a" if value is None else fmt.format(value)


SYNTHETIC_LABEL_NOTE = (
    "Labels here are synthetic hints from the fixtures' expected.json, not hand labels. "
    "Numbers on a handful of synthetic items say nothing about accuracy."
)


def render_summary(summary: Summary, *, label_note: str = LABEL_NOTE) -> str:
    """The shared body: data, systems, per-class, calibration, order sensitivity, latency."""
    lines: list[str] = [
        "## Data",
        "",
        f"- Labelled items: {summary.n_labelled}; scored (non-ambiguous, Decider answered): "
        f"{summary.n_scored}; Decider failures: {summary.n_decider_failures}",
        f"- Ambiguous rate among labelled: {pct(summary.ambiguous)}",
        f"- {label_note}",
        "",
        "## Q1 (nature)",
        "",
        "| System | Macro-F1 | Accuracy (Wilson 95%) |",
        "|---|---|---|",
        f"| Rule baseline v0 | {summary.q1_rules.macro_f1:.3f} | "
        f"{pct(summary.q1_rules.accuracy)} |",
        f"| Decider K=1 | {summary.q1_k1.macro_f1:.3f} | {pct(summary.q1_k1.accuracy)} |",
        f"| Decider K=3 | {summary.q1_k3.macro_f1:.3f} | {pct(summary.q1_k3.accuracy)} |",
        "",
        "Macro-F1 averages the classes that occur in the gold labels (support > 0).",
        "",
        "### Per class (Decider K=3 vs rule baseline)",
        "",
        "| Class | Support | K=3 precision | K=3 recall | Rules precision | Rules recall |",
        "|---|---|---|---|---|---|",
    ]
    rules_by = {c.label: c for c in summary.q1_rules.per_class}
    for c in summary.q1_k3.per_class:
        r = rules_by[c.label]
        lines.append(
            f"| {c.label} | {c.support} | {pct(c.precision)} | {pct(c.recall)} | "
            f"{pct(r.precision)} | {pct(r.recall)} |"
        )
    lines += [
        "",
        "## Q2 (response)",
        "",
        "| System | Macro-F1 | Accuracy (Wilson 95%) |",
        "|---|---|---|",
        f"| Rule baseline v0 | {summary.q2_rules.macro_f1:.3f} | "
        f"{pct(summary.q2_rules.accuracy)} |",
        f"| Decider K=1 | {summary.q2_k1.macro_f1:.3f} | {pct(summary.q2_k1.accuracy)} |",
        f"| Decider K=3 | {summary.q2_k3.macro_f1:.3f} | {pct(summary.q2_k3.accuracy)} |",
        "",
        "## Sharpness and calibration (Decider K=3, Q1)",
        "",
        f"- Top third by max(p_agg): Q1 accuracy {pct(summary.top_third)}",
        f"- Share of items with max(p_agg) < {CANNOT_TELL_BELOW:.2f} (cannot_tell band): "
        f"{pct(summary.cannot_tell_share)}",
        "",
        "| max(p_agg) bin | n | Accuracy (Wilson 95%) |",
        "|---|---|---|",
    ]
    for b in summary.reliability:
        lines.append(f"| [{b.lo:.2f}, {b.hi:.2f}) | {b.accuracy.n} | {pct(b.accuracy)} |")
    od = summary.order_sensitivity
    lat = summary.latency
    lines += [
        "",
        "ECE is not reported: bins hold fewer than 25 items on a set this size.",
        "",
        "## Order sensitivity (Q1, max pairwise L1 across the three orders)",
        "",
        f"- n={od.n}; p50 {_num(od.p50)}; p90 {_num(od.p90)}; max {_num(od.maximum)}",
        f"- Share above the 0.30 cap: {pct(od.share_above_cap)}",
        "",
        "## Latency (one request answers all eight questions)",
        "",
        f"- End to end: p50 {_num(lat.p50, '{:.0f}')} ms, "
        f"p95 {_num(lat.p95, '{:.0f}')} ms (n={lat.n})",
        f"- Server side: p50 {_num(lat.server_p50, '{:.0f}')} ms, "
        f"p95 {_num(lat.server_p95, '{:.0f}')} ms",
        "",
    ]
    return "\n".join(lines)


def render_spike(
    summary: Summary, gate: Gate, *, date: str, config_version: str, model: str
) -> str:
    """The spike report with its one-line verdict."""
    head = [
        f"# Day-1 feasibility spike ({date})",
        "",
        verdict_line(gate),
        "",
        f"- Config version: `{config_version}`; model: `{model}`",
        f"- {DEV_NOTE}",
        "",
        "## Gate",
        "",
        "| Condition | Value | Required | Met |",
        "|---|---|---|---|",
        f"| Decider K=3 macro-F1 minus rule macro-F1 | {gate.f1_delta:+.3f} | "
        f">= +{F1_MARGIN:.2f} | {'yes' if gate.f1_condition else 'no'} |",
        f"| Top-third Q1 accuracy, Wilson lower bound | {gate.top_third_lower:.3f} | "
        f">= {TOP_THIRD_LOWER_BOUND:.2f} | {'yes' if gate.top_third_condition else 'no'} |",
        "",
    ]
    return "\n".join(head) + "\n" + render_summary(summary)


def render_not_run(n_labelled: int, *, date: str) -> str:
    """The spike file written when too few labels exist: no verdict of any kind."""
    return (
        f"# Day-1 feasibility spike ({date})\n\n"
        f"{not_run_line(n_labelled)}\n\n"
        f"The spike needs {REQUIRED_LABELS} adjudicated dev labels. Label with "
        "`uv run cso eval label --set dev`, adjudicate with `uv run cso eval adjudicate`, "
        "then rerun `uv run cso eval spike`.\n"
    )


def render_run(
    summary: Summary, *, title: str, banner: str | None, date: str, config_version: str, model: str
) -> str:
    """A run summary with no go/no-go verdict (smoke, dev or held-out runs)."""
    head = [f"# {title} ({date})", ""]
    if banner:
        head += [f"**{banner}**", ""]
    head += [f"- Config version: `{config_version}`; model: `{model}`", ""]
    note = SYNTHETIC_LABEL_NOTE if banner == SMOKE_BANNER else LABEL_NOTE
    return "\n".join(head) + "\n" + render_summary(summary, label_note=note)
