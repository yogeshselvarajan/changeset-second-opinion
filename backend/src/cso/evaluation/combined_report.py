"""`cso eval report --latest`: one markdown report from the latest committed results files.

Nothing is run here: no model, no network, no Bedrock. The spike and the label-free diagnostic are
recomputed from the stored per-item runs (and, for the spike, the adjudicated dev labels), and the
held-out section is re-rendered from its results JSON. The spike's verdict line therefore exists
only when enough gold labels do: without them the section says `NOT RUN` and shows no verdict.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Any

from cso.domain.config import CommunityConfig
from cso.evaluation.heldout_report import render_heldout
from cso.evaluation.labels import LabelStore, load_gold
from cso.evaluation.panel_eval import (
    PanelItemRun,
    diagnose_panel,
    evaluate_panel_gate,
    summarise_panel,
)
from cso.evaluation.panel_report import label_provenance, render_diagnostic, render_panel_spike
from cso.evaluation.paths import EvalPaths
from cso.evaluation.spike import REQUIRED_LABELS, not_run_line
from cso.evaluation.split import DEV, SplitError, load_ids

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_HEADING_RE = re.compile(r"^(#{1,5}) ", re.MULTILINE)


def latest_file(results_dir: Path, pattern: str) -> Path | None:
    """The newest results file matching `pattern`.

    Ordered by the date in the file name, then plain before tagged (a tagged re-run such as
    `-v2` supersedes the plain run of the same day), then by the tag itself.
    """

    def key(path: Path) -> tuple[str, bool, str]:
        match = _DATE_RE.search(path.name)
        date = match.group(1) if match else ""
        tag = path.stem[match.end() :] if match else path.stem
        return (date, bool(tag), tag)

    files = sorted(results_dir.glob(pattern), key=key)
    return files[-1] if files else None


def runs_from_json(items: list[dict[str, Any]]) -> list[PanelItemRun]:
    """Panel runs from a results file; fields an older file lacks take their defaults."""
    known = {f.name for f in fields(PanelItemRun)}
    runs: list[PanelItemRun] = []
    for raw in items:
        data = {k: v for k, v in raw.items() if k in known}
        data["rules_fired"] = tuple(data.get("rules_fired", ()))
        runs.append(PanelItemRun(**data))
    return runs


def _demote(text: str) -> str:
    """One heading level deeper, so an embedded report nests under the combined one."""
    return _HEADING_RE.sub(lambda m: f"{m.group(1)}# ", text)


def _load(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _spike_section(paths: EvalPaths) -> str:
    path = latest_file(paths.results_dir, "spike-*.json")
    if path is None:
        return "No spike results file exists yet."
    payload = _load(path)
    if payload is None or not payload.get("items") or "states" not in payload["items"][0]:
        return f"`{path.name}` is not a fact-panel spike file; it is not rendered here."
    try:
        dev_ids = set(load_ids(paths, DEV))
    except SplitError:
        dev_ids = set()
    gold = load_gold(paths.adjudicated(DEV))
    labelled = [i for i in sorted(dev_ids) if i in gold and gold[i].version >= 2]
    if len(labelled) < REQUIRED_LABELS:
        return (
            f"{not_run_line(len(labelled))}. There are not enough adjudicated labels, so no "
            "verdict is shown."
        )
    runs = [r for r in runs_from_json(payload["items"]) if r.changeset_id in set(labelled)]
    summary = summarise_panel(runs, gold)
    gate = evaluate_panel_gate(summary)
    provenance = label_provenance(
        (row.labeller for row in LabelStore(paths.labels(DEV), DEV).rows()),
        (g.adjudicator for g in gold.values() if g.adjudicator),
    )
    return _demote(
        render_panel_spike(
            summary,
            gate,
            date=payload["date"],
            config_version=payload["config_version"],
            model=payload["model"],
            provenance=provenance,
        )
    )


def _diagnostic_section(paths: EvalPaths, config: CommunityConfig) -> str:
    path = latest_file(paths.results_dir, "panel-diagnostic-*.json")
    payload = _load(path) if path is not None else None
    if path is None or payload is None or not payload.get("items"):
        return "No panel diagnostic file exists yet."
    diag = diagnose_panel(runs_from_json(payload["items"]), config)
    return _demote(
        render_diagnostic(
            diag,
            date=payload["date"],
            config_version=payload["config_version"],
            model=payload["model"],
            profile=payload.get("profile", "compact"),
            split_status=f"from `{path.name}`",
        )
    )


def _heldout_section(paths: EvalPaths) -> str:
    path = latest_file(paths.results_dir, "*-heldout-*.json")
    payload = _load(path) if path is not None else None
    if path is None or payload is None or payload.get("kind") != "heldout":
        return "The held-out evaluation has not been run yet."
    return _demote(render_heldout(payload))


def render_combined(paths: EvalPaths, config: CommunityConfig) -> str:
    """The combined markdown: spike, label-free diagnostic and held-out, from stored files."""
    return "\n".join(
        [
            "# Combined evaluation report",
            "",
            "Rendered from the committed results files. Nothing was run to produce it: no model, "
            "no network and no Bedrock call.",
            "",
            "## Day-1 feasibility spike (dev set)",
            "",
            _spike_section(paths),
            "",
            "## Fact-panel diagnostic (no labels, not a verdict)",
            "",
            _diagnostic_section(paths, config),
            "",
            "## Held-out evaluation",
            "",
            _heldout_section(paths),
            "",
        ]
    )
