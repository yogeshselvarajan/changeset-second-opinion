"""Model-size ablation: the same panel request on two Decider servers, side by side.

`cso eval ablate-model` sends the identical rendered evidence and identical questions to a second
server (another checkpoint, such as E4B or 12B) and sets the result next to the 2B run of the same
day. Nothing here changes the contract: composition, thresholds and rules are shared, so any
difference is the model's. The report states who produced the labels and says "not run" for a
server that was not asked.

Pure functions only (runs in, text out); the network lives in `eval_cli`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from xml.sax.saxutils import escape

from cso.evaluation.labels import GoldLabel
from cso.evaluation.panel_eval import PanelItemRun, PanelSummary, summarise_panel
from cso.evaluation.report import _num, pct
from cso.evaluation.stats import Proportion, proportion

ABLATION_VERSION = 1
DIFF_NOTE = (
    "Both columns used the same evidence text, the same ten questions, the same cut points "
    "(0.35 and 0.65) and the same composition table. Only the model behind the server differs."
)


@dataclass(frozen=True)
class ModelRun:
    """One server's answers over the same items."""

    label: str
    model: str
    runs: tuple[PanelItemRun, ...]


@dataclass(frozen=True)
class ProbeCompare:
    """One probe for both models."""

    probe: str
    a: Proportion
    b: Proportion
    a_unknown: Proportion
    b_unknown: Proportion


@dataclass(frozen=True)
class Ablation:
    """Everything the report and the chart need."""

    a: ModelRun
    b: ModelRun
    summary_a: PanelSummary
    summary_b: PanelSummary
    probes: tuple[ProbeCompare, ...]
    n_items: int
    n_both_answered: int
    nature_agreement: Proportion
    labelled: bool


def runs_from_json(text: str) -> tuple[str, str, list[PanelItemRun]]:
    """(model, config_version, runs) from a results `.json` written by `_panel_json`."""
    data = json.loads(text)
    known = {f.name for f in fields(PanelItemRun)}
    runs: list[PanelItemRun] = []
    for item in data["items"]:
        values = {k: v for k, v in item.items() if k in known}
        values["rules_fired"] = tuple(values.get("rules_fired") or ())
        values["cross_checks"] = dict(values.get("cross_checks") or {})
        runs.append(PanelItemRun(**values))
    return str(data.get("model", "unknown")), str(data.get("config_version", "")), runs


def _agreement(a: tuple[PanelItemRun, ...], b: tuple[PanelItemRun, ...]) -> tuple[int, int]:
    """(items where both composed the same nature, items both answered)."""
    by_id = {r.changeset_id: r for r in b}
    both = same = 0
    for ra in a:
        rb = by_id.get(ra.changeset_id)
        if rb is None or ra.error or rb.error or not ra.composed_nature or not rb.composed_nature:
            continue
        both += 1
        same += ra.composed_nature == rb.composed_nature
    return same, both


def compare_models(a: ModelRun, b: ModelRun, gold: dict[int, GoldLabel]) -> Ablation:
    """Score both runs on the same labelled items and line the probes up."""
    ids_a = {r.changeset_id for r in a.runs}
    ids_b = {r.changeset_id for r in b.runs}
    common = ids_a & ids_b
    runs_a = tuple(r for r in a.runs if r.changeset_id in common)
    runs_b = tuple(r for r in b.runs if r.changeset_id in common)
    summary_a, summary_b = summarise_panel(runs_a, gold), summarise_panel(runs_b, gold)
    probes = tuple(
        ProbeCompare(
            pa.probe, pa.accuracy_decided, pb.accuracy_decided, pa.panel_unknown, pb.panel_unknown
        )
        for pa, pb in zip(summary_a.probes, summary_b.probes, strict=True)
    )
    same, both = _agreement(runs_a, runs_b)
    return Ablation(
        a=ModelRun(a.label, a.model, runs_a),
        b=ModelRun(b.label, b.model, runs_b),
        summary_a=summary_a,
        summary_b=summary_b,
        probes=probes,
        n_items=len(common),
        n_both_answered=both,
        nature_agreement=proportion(same, both),
        labelled=summary_a.n_labelled > 0,
    )


def _delta(a: Proportion, b: Proportion) -> str:
    if a.n == 0 or b.n == 0:
        return "n/a"
    diff = b.k / b.n - a.k / a.n
    overlap = b.lower <= a.upper and a.lower <= b.upper
    return f"{diff:+.2f} ({'intervals overlap' if overlap else 'intervals apart'})"


def render_ablation(
    result: Ablation,
    *,
    date: str,
    config_version: str,
    provenance: str,
    chart_name: str | None = None,
    set_name: str = "dev",
) -> str:
    """The side-by-side report."""
    a, b = result.a, result.b
    sa, sb = result.summary_a, result.summary_b
    lines: list[str] = [
        f"# Model-size ablation: {a.label} vs {b.label} ({date})",
        "",
        "**ABLATION - NOT A RELEASE GATE**",
        "",
        provenance,
        "",
        f"- Items in both runs ({set_name} set): {result.n_items}; both answered: "
        f"{result.n_both_answered}",
        f"- Config version: `{config_version}`",
        f"- {a.label}: `{a.model}`",
        f"- {b.label}: `{b.model}`",
        f"- {DIFF_NOTE}",
        f"- Same composed nature on the same item, both answered: {pct(result.nature_agreement)}",
        "",
    ]
    if not result.labelled:
        lines += [
            "No adjudicated probe labels cover these items, so the accuracy columns below are "
            "empty. The unknown rates and the agreement line above still compare the two models.",
            "",
        ]
    lines += [
        "## Per-probe accuracy when decided",
        "",
        f"| Probe | {a.label} accuracy | {b.label} accuracy | Difference | "
        f"{a.label} unknown | {b.label} unknown |",
        "|---|---|---|---|---|---|",
    ]
    for p in result.probes:
        lines.append(
            f"| {p.probe} | {pct(p.a)} | {pct(p.b)} | {_delta(p.a, p.b)} | "
            f"{pct(p.a_unknown)} | {pct(p.b_unknown)} |"
        )
    lines += [
        "",
        f"Pooled accuracy when decided: {a.label} {pct(sa.pooled_decided)}; "
        f"{b.label} {pct(sb.pooled_decided)}",
        "",
        "## Composed nature",
        "",
        "| System | Macro-F1 | Accuracy (Wilson 95%) |",
        "|---|---|---|",
        f"| Rule baseline | {sa.rules_nature.macro_f1:.3f} | {pct(sa.rules_nature.accuracy)} |",
        f"| {a.label} composed | {sa.composed_nature.macro_f1:.3f} | "
        f"{pct(sa.composed_nature.accuracy)} |",
        f"| {b.label} composed | {sb.composed_nature.macro_f1:.3f} | "
        f"{pct(sb.composed_nature.accuracy)} |",
        "",
        "## Speed and size",
        "",
        "| | Input tokens p50 | End to end p50 | End to end p95 | Server p50 | Decider failures |",
        "|---|---|---|---|---|---|",
        f"| {a.label} | {_num(sa.input_tokens_p50, '{:.0f}')} | "
        f"{_num(sa.latency.p50, '{:.0f}')} ms | {_num(sa.latency.p95, '{:.0f}')} ms | "
        f"{_num(sa.latency.server_p50, '{:.0f}')} ms | {_failures(a.runs)} |",
        f"| {b.label} | {_num(sb.input_tokens_p50, '{:.0f}')} | "
        f"{_num(sb.latency.p50, '{:.0f}')} ms | {_num(sb.latency.p95, '{:.0f}')} ms | "
        f"{_num(sb.latency.server_p50, '{:.0f}')} ms | {_failures(b.runs)} |",
        "",
    ]
    if chart_name:
        lines += [f"![Per-probe accuracy, {a.label} vs {b.label}]({chart_name})", ""]
    lines += [
        "Reading this: a larger model earns its memory only if it moves the accuracy columns "
        "outside the other model's interval, or cuts the unknown rate without losing accuracy. "
        "Overlapping intervals on this many items say the two cannot be told apart yet.",
        "",
    ]
    return "\n".join(lines)


def _failures(runs: tuple[PanelItemRun, ...]) -> int:
    return sum(1 for r in runs if r.error is not None)


# ---------------------------------------------------------------------------------- chart

_W, _ROW, _LEFT, _TOP, _RIGHT = 760, 34, 230, 56, 24
_COLOURS = ("#4E5BD8", "#B8791F")


def render_chart(result: Ablation) -> str:
    """Grouped horizontal bars (accuracy when decided) with Wilson whiskers, one row per probe."""
    probes = result.probes
    height = _TOP + _ROW * len(probes) + 48
    plot = _W - _LEFT - _RIGHT

    def x(value: float) -> float:
        return _LEFT + plot * value

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {height}" width="{_W}" '
        f'height="{height}" role="img" aria-label="Per-probe accuracy when decided, '
        f'{escape(result.a.label)} vs {escape(result.b.label)}, with Wilson 95 percent intervals">',
        f'<rect width="{_W}" height="{height}" fill="#F6F5F2"/>',
        "<style>text{font:12px Inter,Arial,sans-serif;fill:#1B1A17}.m{fill:#4a4944}"
        ".t{font-weight:600;font-size:14px}</style>",
        f'<text class="t" x="{_LEFT}" y="22">Accuracy when decided, by probe</text>',
    ]
    for i, (label, colour) in enumerate(
        zip((result.a.label, result.b.label), _COLOURS, strict=True)
    ):
        cx = _LEFT + 220 + i * 150
        parts.append(f'<rect x="{cx}" y="32" width="12" height="12" fill="{colour}"/>')
        parts.append(f'<text x="{cx + 18}" y="43">{escape(label)}</text>')
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        parts.append(
            f'<line x1="{x(tick):.1f}" y1="{_TOP - 6}" x2="{x(tick):.1f}" '
            f'y2="{_TOP + _ROW * len(probes)}" stroke="#D9D6CE"/>'
        )
        parts.append(
            f'<text class="m" x="{x(tick):.1f}" y="{height - 12}" '
            f'text-anchor="middle">{tick:.2f}</text>'
        )
    for row, probe in enumerate(probes):
        top = _TOP + row * _ROW
        parts.append(
            f'<text x="{_LEFT - 8}" y="{top + 20}" text-anchor="end">{escape(probe.probe)}</text>'
        )
        for slot, (prop, colour) in enumerate(zip((probe.a, probe.b), _COLOURS, strict=True)):
            y = top + 4 + slot * 12
            if prop.n == 0:
                parts.append(f'<text class="m" x="{x(0) + 4}" y="{y + 9}">no labels</text>')
                continue
            value = prop.k / prop.n
            parts.append(
                f'<rect x="{x(0):.1f}" y="{y}" width="{plot * value:.1f}" height="10" '
                f'fill="{colour}"/>'
            )
            parts.append(
                f'<line x1="{x(prop.lower):.1f}" y1="{y + 5}" '
                f'x2="{x(prop.upper):.1f}" y2="{y + 5}" '
                'stroke="#1B1A17" stroke-width="1.5"/>'
            )
            for edge in (prop.lower, prop.upper):
                parts.append(
                    f'<line x1="{x(edge):.1f}" y1="{y + 1}" x2="{x(edge):.1f}" y2="{y + 9}" '
                    'stroke="#1B1A17" stroke-width="1.5"/>'
                )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def load_run_file(path: Path) -> tuple[str, str, list[PanelItemRun]]:
    """Read a saved panel run (the `.json` beside a report)."""
    return runs_from_json(path.read_text(encoding="utf-8"))
