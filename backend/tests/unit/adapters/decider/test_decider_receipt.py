from __future__ import annotations

import json
from pathlib import Path

import pytest
from decider_support import REPO, client_for, config, fake_server
from pydantic import ValidationError

from cso.adapters.decider import DeciderClient
from cso.adapters.osm import ReplayClient, collect
from cso.domain.enums import Band, Lane
from cso.domain.receipt import ReconciliationRecord, build_receipt

CASE = REPO / "backend" / "fixtures" / "cases" / "02-good-faith-mistake"


async def _snapshot_and_result() -> tuple[object, object]:
    replay = ReplayClient(Path(CASE))
    snapshot = await collect(replay, replay.case.changeset.id)
    result = await DeciderClient("unused", http=client_for(fake_server())).decide("s", config())
    return snapshot, result


async def test_receipt_merges_snapshot_config_questions_and_timings() -> None:
    snapshot, result = await _snapshot_and_result()
    cfg = config()
    receipt = build_receipt(
        snapshot,  # type: ignore[arg-type]
        config_version=cfg.version,
        questions_hash=result.questions_hash,  # type: ignore[attr-defined]
        identity=result.identity,  # type: ignore[attr-defined]
        outputs=result.outputs,  # type: ignore[attr-defined]
        state_tokens=result.input_tokens,  # type: ignore[attr-defined]
        timing_ms={"fetch": 12, "decider": result.latency_ms},  # type: ignore[attr-defined]
    )
    data = receipt.to_json_dict()
    json.dumps(data)  # fully JSON-serialisable
    assert data["receipt_version"] == "1"
    assert data["evidence_version"] == snapshot.evidence_version  # type: ignore[attr-defined]
    assert data["config_version"] == cfg.version
    assert data["decider"]["device"] == "cuda"
    assert len(data["permutations"]) == 6
    assert set(data["aggregated"]) == {"nature", "response"}
    assert data["coverage"]["elements_in_changeset"] >= 0
    assert data["timing_ms"]["fetch"] == 12
    assert data["human_outcome_ids"] == []


async def test_receipt_is_immutable_and_serialises_reconciliation_with_the_key_from() -> None:
    snapshot, _ = await _snapshot_and_result()
    receipt = build_receipt(
        snapshot,  # type: ignore[arg-type]
        config_version="sha256:x",
        band=Band.UNSURE,
        lane=Lane.REVIEW_SUGGESTED,
        reconciliation=ReconciliationRecord(
            applied=True, from_="no_action_suggested", to="welcome_and_tips"
        ),
    )
    assert receipt.to_json_dict()["reconciliation"] == {
        "applied": True,
        "from": "no_action_suggested",
        "to": "welcome_and_tips",
    }
    with pytest.raises(ValidationError):
        receipt.lane = Lane.LOOKS_CONSISTENT  # type: ignore[misc]


async def test_a_failed_run_still_yields_a_valid_receipt_with_no_outputs() -> None:
    snapshot, _ = await _snapshot_and_result()
    receipt = build_receipt(
        snapshot,  # type: ignore[arg-type]
        config_version="sha256:x",
        errors=["decider_unavailable"],
        lane=Lane.RULES_ONLY,
    )
    data = receipt.to_json_dict()
    assert data["permutations"] == [] and data["aggregated"] == {}
    assert data["decider"] is None
    assert data["errors"] == ["decider_unavailable"]
