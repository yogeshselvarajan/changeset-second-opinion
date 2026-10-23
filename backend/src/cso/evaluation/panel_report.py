"""Markdown for the fact-panel diagnostic, panel run and panel spike (Wilson CI on every share)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from cso.evaluation.panel_eval import (
    PANEL_POOLED_LOWER_BOUND,
    PanelDiagnostic,
    PanelGate,
    PanelSummary,
)
from cso.evaluation.report import DEV_NOTE, LABEL_NOTE, SMOKE_BANNER, _num, pct
from cso.evaluation.spike import F1_MARGIN

DIAGNOSTIC_BANNER = "PANEL DIAGNOSTIC - NO LABELS - NOT A VERDICT"

CONTRACT_NOTE = (
    "Decision contract (ADR-009): ten yes/no probes read as no, unknown or yes at 0.35 and 0.65; "
    "the composed nature and response come from a fixed table over those readings plus the parsed "
    "rules; the four-way nature the model also answers is advisory and never used for lanes."
)


def panel_verdict_line(gate: PanelGate) -> str:
    """One-line verdict."""
    if gate.verdict == "BORDERLINE":
        return (
            "VERDICT: BORDERLINE (one of two conditions met): rewrite the criteria once and rerun"
        )
    return f"VERDICT: {gate.verdict}"


def _counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def render_diagnostic(
    diag: PanelDiagnostic,
    *,
    date: str,
    config_version: str,
    model: str,
    profile: str,
    split_status: str,
) -> str:
    """The label-free diagnostic report: histograms, near-0.5 shares, agreement, tokens, latency."""
    lat = diag.latency
    lines: list[str] = [
        f"# Fact-panel diagnostic ({date})",
        "",
        f"**{DIAGNOSTIC_BANNER}**",
        "",
        "No labels are read or written here. Held-out ids appear only in these label-free "
        "statistics; thresholds (0.35 and 0.65) and the composition table were fixed before this "
        "run, and nothing is tuned on these numbers.",
        "",
        f"- Config version: `{config_version}`; model: `{model}`; evidence profile: `{profile}`",
        f"- Split: {split_status}",
        f"- {CONTRACT_NOTE}",
        "",
        "## Data",
        "",
        f"- Items: {diag.n_items}; answered: {diag.n_answered}; "
        f"Decider failures: {diag.n_failures}",
        "",
        "## Probe probabilities",
        "",
        "Histogram counts are for ten equal bins from 0.0 to 1.0 (the last includes 1.0). "
        "`near 0.5` is a probability from 0.40 to 0.60; `unknown` is 0.35 to 0.65.",
        "",
        "| Probe | n | Histogram (0.0 ... 1.0) | Near 0.5 | Unknown | Yes | No |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in diag.probes:
        lines.append(
            f"| {p.probe} | {p.n} | {' '.join(str(c) for c in p.histogram)} | {pct(p.near_half)} | "
            f"{pct(p.unknown)} | {pct(p.yes)} | {pct(p.no)} |"
        )
    lines += [
        "",
        "## Agreement with facts computed from parsed evidence",
        "",
        "Informational: the policy rules decide, and these facts are exact for the question as "
        "worded (`mass_retag_single_key` is counted over the elements with details). Agreement is "
        "over items where the panel said yes or no.",
        "",
        "| Probe | Agree | Disagree | Unknown | Not applicable | Agreement (Wilson 95%) |",
        "|---|---|---|---|---|---|",
    ]
    for a in diag.agreement:
        lines.append(
            f"| {a.probe} | {a.agree} | {a.disagree} | {a.undecided} | {a.not_applicable} | "
            f"{pct(a.agreement_decided)} |"
        )
    lines += [
        "",
        "## Composition (no labels, so these are counts and not accuracy)",
        "",
        f"- Nature: {_counts(diag.nature_counts)}",
        f"- Response: {_counts(diag.response_counts)}",
        f"- Lane: {_counts(diag.lane_counts)}",
        f"- Band: {_counts(diag.band_counts)}",
        f"- Table rows (nature/response): {_counts(diag.rows_counts)}",
        f"- Advisory nature, top probability p50: {_num(diag.advisory_top_p50)}",
        "",
        "## Input size and latency",
        "",
        f"- Input tokens: p50 {_num(diag.input_tokens_p50, '{:.0f}')}, "
        f"p95 {_num(diag.input_tokens_p95, '{:.0f}')}",
        f"- End to end: p50 {_num(lat.p50, '{:.0f}')} ms, p95 {_num(lat.p95, '{:.0f}')} ms "
        f"(n={lat.n})",
        f"- Server side: p50 {_num(lat.server_p50, '{:.0f}')} ms, "
        f"p95 {_num(lat.server_p95, '{:.0f}')} ms",
        "",
    ]
    return "\n".join(lines)


def render_panel_summary(summary: PanelSummary, *, label_note: str = LABEL_NOTE) -> str:
    """Per-probe accuracy, systems table and latency for labelled items."""
    lat = summary.latency
    lines: list[str] = [
        "## Data",
        "",
        f"- Labelled items (probe labels): {summary.n_labelled}; scored for nature "
        f"(non-ambiguous, Decider answered): {summary.n_scored}; Decider failures: "
        f"{summary.n_failures}",
        f"- Ambiguous rate among labelled: {pct(summary.ambiguous)}",
        f"- {label_note}",
        "",
        "## Per-probe accuracy (gold yes or no only; gold unknown excluded)",
        "",
        "| Probe | Gold n | Panel unknown | Accuracy when decided | Strict accuracy |",
        "|---|---|---|---|---|",
    ]
    for s in summary.probes:
        lines.append(
            f"| {s.probe} | {s.n_gold} | {pct(s.panel_unknown)} | {pct(s.accuracy_decided)} | "
            f"{pct(s.accuracy_strict)} |"
        )
    lines += [
        "",
        f"Pooled accuracy when decided: {pct(summary.pooled_decided)}",
        "",
        "Strict accuracy counts an unknown reading as wrong; `unknown` is the cautious reading, so "
        "it costs coverage and never raises a lane.",
        "",
        "## Nature (composed from the panel versus baselines)",
        "",
        "| System | Macro-F1 | Accuracy (Wilson 95%) |",
        "|---|---|---|",
        f"| Rule baseline v1 (policy rules) | {summary.rules_nature.macro_f1:.3f} | "
        f"{pct(summary.rules_nature.accuracy)} |",
        f"| Panel composed (decision input) | {summary.composed_nature.macro_f1:.3f} | "
        f"{pct(summary.composed_nature.accuracy)} |",
        f"| Model advisory nature (not used for lanes) | "
        f"{summary.advisory_nature.macro_f1:.3f} | {pct(summary.advisory_nature.accuracy)} |",
        "",
        "Macro-F1 averages the classes that occur in the gold labels (support > 0).",
        "",
        "## Input size and latency",
        "",
        f"- Input tokens: p50 {_num(summary.input_tokens_p50, '{:.0f}')}, "
        f"p95 {_num(summary.input_tokens_p95, '{:.0f}')}",
        f"- End to end: p50 {_num(lat.p50, '{:.0f}')} ms, p95 {_num(lat.p95, '{:.0f}')} ms "
        f"(n={lat.n})",
        f"- Server side: p50 {_num(lat.server_p50, '{:.0f}')} ms, "
        f"p95 {_num(lat.server_p95, '{:.0f}')} ms",
        "",
    ]
    return "\n".join(lines)


def label_provenance(labellers: Iterable[str], adjudicators: Iterable[str]) -> str:
    """Who produced the gold labels, stated in the report: AI-only unless a person took part.

    A labeller or adjudicator named `claude` is an AI. Any other name is treated as a person.
    """
    people = sorted({n for n in (*labellers, *adjudicators) if n and n.lower() != "claude"})
    if not people:
        return (
            "LABELS: AI-ONLY. Every gold label was produced by an AI (Claude), and the "
            "disagreements between its two sessions were resolved by the same AI after reading the "
            "public OpenStreetMap pages. No person labelled or adjudicated. The verdict below "
            "scores the Decider against another model's opinion, so it is indicative only and is "
            "not human-validated."
        )
    return (
        "LABELS: MIXED. Gold labels combine an AI (Claude) with these people: "
        f"{', '.join(people)}. See the label notes for which items each produced."
    )


def render_panel_spike(
    summary: PanelSummary,
    gate: PanelGate,
    *,
    date: str,
    config_version: str,
    model: str,
    provenance: str = "",
) -> str:
    """The panel spike report with its one-line verdict and the gate criteria it applied."""
    ai_only = provenance.startswith("LABELS: AI-ONLY")
    verdict = panel_verdict_line(gate)
    if ai_only:
        verdict += " (AI-ONLY LABELS: indicative, not human-validated)"
    head = [
        f"# Day-1 feasibility spike, fact-panel contract ({date})",
        "",
        verdict,
        "",
        *([provenance, ""] if provenance else []),
        f"- Config version: `{config_version}`; model: `{model}`",
        f"- {DEV_NOTE}",
        f"- {CONTRACT_NOTE}",
        "- Gate (ADR-009): condition 1, composed-nature macro-F1 beats the rule baseline by at "
        f"least {F1_MARGIN * 100:.0f} points; condition 2, pooled probe accuracy when decided has "
        f"a Wilson lower bound of at least {PANEL_POOLED_LOWER_BOUND:.2f}. Both met is GO, one is "
        "BORDERLINE (rewrite the criteria once and rerun), none is NO-GO.",
        "",
        "## Gate",
        "",
        "| Condition | Value | Required | Met |",
        "|---|---|---|---|",
        f"| Composed macro-F1 minus rule macro-F1 | {gate.f1_delta:+.3f} | "
        f">= +{F1_MARGIN:.2f} | {'yes' if gate.f1_condition else 'no'} |",
        f"| Pooled decided probe accuracy, Wilson lower bound | {gate.pooled_lower:.3f} | "
        f">= {PANEL_POOLED_LOWER_BOUND:.2f} | {'yes' if gate.pooled_condition else 'no'} |",
        "",
    ]
    note = (
        "Gold labels were produced by an AI and adjudicated by the same AI (see LABELS above); "
        "weak labels (MapRoulette status) are never used as ground truth."
        if ai_only
        else LABEL_NOTE
    )
    return "\n".join(head) + "\n" + render_panel_summary(summary, label_note=note)


def render_panel_run(
    summary: PanelSummary,
    *,
    title: str,
    banner: str | None,
    date: str,
    config_version: str,
    model: str,
    synthetic: bool = False,
) -> str:
    """A panel run summary with no go/no-go verdict (smoke, dev or held-out runs)."""
    head = [f"# {title} ({date})", ""]
    if banner:
        head += [f"**{banner}**", ""]
    head += [f"- Config version: `{config_version}`; model: `{model}`", f"- {CONTRACT_NOTE}", ""]
    note = (
        "Labels here are synthetic hints from the fixtures' expected.json, not hand labels."
        if synthetic or banner == SMOKE_BANNER
        else LABEL_NOTE
    )
    return "\n".join(head) + "\n" + render_panel_summary(summary, label_note=note)
