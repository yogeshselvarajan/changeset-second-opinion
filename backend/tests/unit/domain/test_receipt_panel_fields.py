"""The receipt's composition and cross-check fields are additive and optional."""

from __future__ import annotations

from pathlib import Path

from cso.adapters.osm import ReplayClient, collect
from cso.domain.receipt import RECEIPT_VERSION, DecisionReceipt, build_receipt

CASE = Path(__file__).resolve().parents[3] / "fixtures" / "cases" / "01-legitimate"
COMPOSITION = {
    "nature": "consistent_edit",
    "response": "no_action_suggested",
    "band": "confident",
    "nature_row": "N4",
    "response_row": "P5",
    "yes": [],
    "unknown": ["conventions_followed"],
}


async def _receipt(**kwargs: object) -> DecisionReceipt:
    replay = ReplayClient(CASE)
    snapshot = await collect(replay, replay.case.changeset.id)
    return build_receipt(snapshot, config_version="sha256:test", **kwargs)  # type: ignore[arg-type]


async def test_fields_default_to_none_and_the_version_is_unchanged() -> None:
    receipt = await _receipt()
    assert receipt.panel_composition is None and receipt.panel_cross_checks is None
    assert receipt.receipt_version == RECEIPT_VERSION == "1"


async def test_fields_round_trip_through_the_stored_json() -> None:
    receipt = await _receipt(
        panel_composition=COMPOSITION, panel_cross_checks={"mature_feature_deleted": "agree"}
    )
    stored = receipt.to_json_dict()
    assert stored["panel_composition"] == COMPOSITION
    assert stored["panel_cross_checks"] == {"mature_feature_deleted": "agree"}
    assert DecisionReceipt.model_validate(stored) == receipt


async def test_a_receipt_stored_before_the_fields_existed_still_loads() -> None:
    stored = (await _receipt()).to_json_dict()
    del stored["panel_composition"], stored["panel_cross_checks"]
    loaded = DecisionReceipt.model_validate(stored)
    assert loaded.panel_composition is None and loaded.panel_cross_checks is None
