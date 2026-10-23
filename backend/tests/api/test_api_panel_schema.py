"""The fact panel as the API shows it: built from domain types, round-tripped, worded safely."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cso.adapters.osm import ReplayClient, collect
from cso.api.schemas import PanelProbe, PanelView, RunSummary
from cso.domain.config import CommunityConfig
from cso.domain.enums import Lane, RunStatus
from cso.domain.lanes import evaluate_panel_run
from cso.domain.panel import (
    PANEL_LABELS,
    PANEL_NOUL_IDS,
    AdvisoryNature,
    FactPanel,
    NoulReading,
    Tri,
    classify,
)

CONFIG = CommunityConfig.load()
CASES = Path(__file__).parents[2] / "fixtures" / "cases"
BANNED = re.compile(r"\b(vandal|vandalism|spam|illegal|stop|must)\b", re.IGNORECASE)
NATURES = ["consistent_edit", "likely_good_faith_mistake", "possible_deliberate_damage"]


def make_panel(overrides: dict[str, float] | None = None) -> FactPanel:
    probs = {i: 0.05 for i in PANEL_NOUL_IDS}
    probs.update({"comment_matches_changes": 0.95, "conventions_followed": 0.95})
    probs.update(overrides or {})
    readings = {i: NoulReading(id=i, probability=p, state=classify(p)) for i, p in probs.items()}
    return FactPanel(
        low=0.35,
        high=0.65,
        readings=readings,
        advisory_nature=AdvisoryNature(
            order=NATURES,
            probabilities=dict.fromkeys(NATURES, 1 / 3),
            choice="consistent_edit",
            confidence=1 / 3,
        ),
        ids=list(PANEL_NOUL_IDS),
    )


async def fixture_view(name: str, panel: FactPanel) -> PanelView:
    case = next(p for p in CASES.iterdir() if p.name.startswith(name))
    changeset_id = json.loads((case / "changeset.json").read_text(encoding="utf-8"))["changeset"][
        "id"
    ]
    snapshot = await collect(ReplayClient(case), changeset_id)
    outcome = evaluate_panel_run(snapshot, panel, CONFIG)
    assert outcome.composition is not None
    return PanelView.from_domain(panel, outcome.composition, outcome.cross_checks)


async def test_panel_view_covers_every_probe_with_label_reading_and_use() -> None:
    view = await fixture_view("02-", make_panel({"new_account_first_edits": 0.9}))
    assert [p.id for p in view.probes] == list(PANEL_NOUL_IDS)
    assert all(p.label == PANEL_LABELS[p.id] for p in view.probes)
    by_id = {p.id: p for p in view.probes}
    assert by_id["new_account_first_edits"].reading is Tri.YES
    assert by_id["evidence_sufficient"].use == "cross_check_only"
    assert by_id["deleted_own_recent_additions"].use == "composed"
    assert by_id["comment_matches_changes"].yes_means == "reassurance"
    assert (view.low, view.high) == (0.35, 0.65)


async def test_panel_view_reports_the_rows_that_fired_and_the_cross_checks() -> None:
    view = await fixture_view("02-", make_panel({"new_account_first_edits": 0.9}))
    assert view.composition is not None
    assert (view.composition.response_row, view.composition.nature_row) == ("P4", "N3")
    assert "new_account_first_edits" in view.composition.yes
    assert set(view.cross_checks) == {
        "mature_feature_deleted",
        "new_account_first_edits",
        "deleted_own_recent_additions",
        "mass_retag_single_key",
        "evidence_sufficient",
    }
    assert set(view.cross_checks.values()) <= {"agree", "disagree", "undecided", "n/a"}


async def test_advisory_nature_is_every_option_and_flagged_advisory() -> None:
    view = await fixture_view("02-", make_panel())
    assert view.advisory_nature.advisory is True
    assert {n.value for n in view.advisory_nature.probabilities} == set(NATURES)
    assert view.advisory_nature.choice.value == "consistent_edit"
    assert "confidence" not in type(view.advisory_nature).model_fields  # no single figure


async def test_panel_view_round_trips_through_json_and_inside_a_run() -> None:
    view = await fixture_view("04-", make_panel({"mature_feature_deleted": 0.9}))
    assert PanelView.model_validate_json(view.model_dump_json()) == view
    run = RunSummary(
        id=uuid4(),
        snapshot_id=uuid4(),
        config_version="sha256:test",
        status=RunStatus.SUCCEEDED,
        lane=Lane.INSUFFICIENT_EVIDENCE,
        panel=view,
        created_at=datetime.now(UTC),
    )
    assert RunSummary.model_validate_json(run.model_dump_json()) == run


def test_panel_stays_optional_so_older_runs_still_validate() -> None:
    run = RunSummary(
        id=uuid4(),
        snapshot_id=uuid4(),
        config_version="sha256:test",
        status=RunStatus.FAILED,
        lane=Lane.RULES_ONLY,
        created_at=datetime.now(UTC),
    )
    assert run.panel is None


def test_probe_labels_and_view_text_avoid_banned_words() -> None:
    assert not [t for t in PANEL_LABELS.values() if BANNED.search(t)]
    assert set(PANEL_LABELS) == set(PANEL_NOUL_IDS)
    assert not BANNED.search(json.dumps(PanelView.model_json_schema()))


def test_no_field_carries_a_single_confidence_figure() -> None:
    bad = re.compile(r"percent|pct|confidence|vandal|spam", re.IGNORECASE)
    for model in (PanelView, PanelProbe):
        assert not [f for f in model.model_fields if bad.search(f)], model.__name__
