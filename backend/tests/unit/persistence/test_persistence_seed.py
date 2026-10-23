"""`cso seed`: fixture cases and snapshots load idempotently; runs only from matching receipts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import sqlalchemy as sa
from persistence_support import CASE_01, CASES, config, rendered_snapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.cli import main
from cso.domain.config import CommunityConfig
from cso.domain.enums import Band, Lane, Nature, Response
from cso.domain.models import (
    AggregatedChoice,
    DecisionOutputs,
    EvidenceSnapshot,
    PermutationResult,
)
from cso.domain.receipt import build_receipt
from cso.persistence.admin import seed_fixtures
from cso.persistence.repos import CasesRepo, RunsRepo
from cso.settings import get_settings


async def _count(factory: async_sessionmaker[AsyncSession], table: str) -> int:
    query = sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608  # fixed table names
    async with factory() as s:
        return int((await s.execute(query)).scalar_one())


def _receipt_for(snapshot: EvidenceSnapshot, config_version: str) -> dict[str, object]:
    nature = AggregatedChoice(
        probabilities={n.value: 0.25 for n in Nature},
        argmax=Nature.CONSISTENT_EDIT.value,
        confidence_agg=0.25,
        order_sensitivity=0.05,
    )
    response = AggregatedChoice(
        probabilities={r.value: 0.2 for r in Response},
        argmax=Response.NO_ACTION_SUGGESTED.value,
        confidence_agg=0.2,
        order_sensitivity=0.05,
    )
    perm = PermutationResult(
        name="nature_p0",
        order=[n.value for n in Nature],
        probabilities=nature.probabilities,
        confidence=0.25,
    )
    outputs = DecisionOutputs(permutations=[perm], nature=nature, response=response)
    receipt = build_receipt(
        snapshot,
        config_version=config_version,
        outputs=outputs,
        band=Band.UNSURE,
        lane=Lane.REVIEW_SUGGESTED,
    )
    return receipt.to_json_dict()


async def test_seed_loads_all_eight_fixture_cases(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    report = await seed_fixtures(factory, CASES.parent)
    assert report.cases_created == 8 and report.cases_existing == 0
    assert report.snapshots_created == 8
    assert report.runs_created == 0 and report.runs_skipped == []  # no fixture carries a receipt
    assert await _count(factory, "review_cases") == 8
    assert await _count(factory, "evidence_snapshots") == 8
    assert await _count(factory, "community_configs") == 1
    async with factory() as s:
        case = await CasesRepo(s).get_by_changeset(900000000004)
    assert case is not None
    assert case.element_delete == 126
    assert case.flags == ["mass deletion"]
    assert case.status == "new"


async def test_seed_is_idempotent(factory: async_sessionmaker[AsyncSession]) -> None:
    await seed_fixtures(factory, CASES.parent)
    again = await seed_fixtures(factory, CASES.parent)
    assert again.cases_created == 0 and again.cases_existing == 8
    assert again.snapshots_created == 0
    assert await _count(factory, "review_cases") == 8
    assert await _count(factory, "evidence_snapshots") == 8


async def test_seed_stores_rendered_text(factory: async_sessionmaker[AsyncSession]) -> None:
    await seed_fixtures(factory, CASES.parent)
    async with factory() as s:
        text, tokens = (
            await s.execute(
                sa.text("SELECT rendered_text, rendered_tokens FROM evidence_snapshots LIMIT 1")
            )
        ).one()
    assert text and tokens > 0


async def _fixture_with_receipt(tmp_path: Path, config_version: str) -> Path:
    root = tmp_path / "fx"
    target = root / "cases" / "01-legitimate"
    shutil.copytree(CASE_01, target)
    snapshot = await rendered_snapshot(CASE_01)
    expected = json.loads((target / "expected.json").read_text(encoding="utf-8"))
    expected["receipt"] = _receipt_for(snapshot, config_version)
    (target / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
    return root


async def test_seed_stores_a_precomputed_run_when_the_receipt_matches(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    cfg: CommunityConfig = config()[0]
    root = await _fixture_with_receipt(tmp_path, cfg.version)
    report = await seed_fixtures(factory, root)
    assert report.runs_created == 1 and report.runs_skipped == []
    async with factory() as s:
        case = await CasesRepo(s).get_by_changeset(900000000001)
        assert case is not None and case.latest_run_id is not None
        run = await RunsRepo(s).get(case.latest_run_id)
    assert case.lane == "review_suggested"
    assert case.status == "analyzed"
    assert run is not None and run.band is Band.UNSURE
    assert run.nature is Nature.CONSISTENT_EDIT


async def test_seed_stores_a_fact_panel_run_with_place_and_comment(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    cfg: CommunityConfig = config()[0]
    root = tmp_path / "fx"
    target = root / "cases" / "01-legitimate"
    shutil.copytree(CASE_01, target)
    snapshot = await rendered_snapshot(CASE_01)
    receipt = build_receipt(
        snapshot,
        config_version=cfg.version,
        band=Band.CONFIDENT,
        lane=Lane.NEEDS_LOCAL_KNOWLEDGE,
        panel_composition={
            "nature": Nature.NEEDS_LOCAL_KNOWLEDGE.value,
            "response": Response.ASK_SOURCE_QUESTION.value,
            "band": "confident",
            "nature_row": "N2",
            "response_row": "P2",
            "yes": [],
            "unknown": [],
        },
    )
    expected = json.loads((target / "expected.json").read_text(encoding="utf-8"))
    expected["receipt"] = receipt.to_json_dict()
    expected["place_label"] = "Test Town, Testland"
    (target / "expected.json").write_text(json.dumps(expected), encoding="utf-8")

    report = await seed_fixtures(factory, root)

    assert report.runs_created == 1 and report.runs_skipped == []
    async with factory() as s:
        case = await CasesRepo(s).get_by_changeset(900000000001)
        assert case is not None and case.latest_run_id is not None
        run = await RunsRepo(s).get(case.latest_run_id)
    assert run is not None and run.nature is Nature.NEEDS_LOCAL_KNOWLEDGE
    assert run.response is Response.ASK_SOURCE_QUESTION
    assert case.lane == "needs_local_knowledge"
    assert case.place_label == "Test Town, Testland"
    assert case.comment == ((snapshot.changeset.comment or "").strip()[:280] or None)


async def test_seed_skips_a_receipt_made_with_another_config(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root = await _fixture_with_receipt(tmp_path, "sha256:not-the-current-config")
    report = await seed_fixtures(factory, root)
    assert report.runs_created == 0
    assert len(report.runs_skipped) == 1 and "config" in report.runs_skipped[0]
    assert await _count(factory, "analysis_runs") == 0
    assert await _count(factory, "review_cases") == 1


def test_cli_seed_and_db_upgrade_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()
    try:
        assert main(["db", "upgrade"]) == 0
        assert "database at head" in capsys.readouterr().out
        assert main(["seed", "--fixtures", str(CASES.parent)]) == 0
        assert "seeded 8 new and 0 existing cases" in capsys.readouterr().out
        assert main(["seed", "--fixtures", str(CASES.parent)]) == 0
        assert "seeded 0 new and 8 existing cases" in capsys.readouterr().out
        assert main(["seed", "--fixtures", str(tmp_path / "missing")]) == 1
    finally:
        get_settings.cache_clear()
