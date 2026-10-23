from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cso.adapters.decider import DeciderClient
from cso.adapters.osm import ReplayClient, collect
from cso.cli import main
from cso.domain.config import CommunityConfig
from cso.domain.fixtures import load_case
from cso.domain.models import EvidenceSnapshot
from cso.evaluation.baselines import rule_baseline
from cso.evaluation.labels import GoldLabel
from cso.evaluation.paths import EVAL_DIR_ENV, EvalPaths
from cso.evaluation.runner import ItemRun, run_items
from cso.evaluation.spike import summarise
from cso.evaluation.split import Split, write_frozen

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "backend" / "fixtures" / "cases"
PATTERN_FIXTURES = ROOT / "patterns" / "calibrated_action_gate" / "tests" / "fixtures"
CONFIG = CommunityConfig.load()


def _case_dir(prefix: str) -> Path:
    return next(d for d in CASES.iterdir() if d.name.startswith(prefix))


async def _snapshot(prefix: str) -> EvidenceSnapshot:
    case_dir = _case_dir(prefix)
    return await collect(ReplayClient(case_dir), load_case(case_dir).expected.changeset_id)


def _decider(calls: list[str]) -> DeciderClient:
    response = json.loads((PATTERN_FIXTURES / "systemone_response_02.json").read_text("utf-8"))
    health = json.loads((PATTERN_FIXTURES / "health.json").read_text("utf-8"))

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json=health)
        return httpx.Response(200, json=response)

    http = httpx.AsyncClient(base_url="http://decider.test", transport=httpx.MockTransport(handler))
    return DeciderClient("http://decider.test", http=http)


async def test_rule_baseline_on_fixtures_follows_the_documented_mapping() -> None:
    legit = rule_baseline(await _snapshot("01"), CONFIG)
    assert (legit.nature.value, legit.response.value) == ("consistent_edit", "no_action_suggested")
    assert legit.fired == ()
    deletion = rule_baseline(await _snapshot("04"), CONFIG)
    assert deletion.nature.value == "possible_deliberate_damage"
    assert deletion.response.value == "escalate_to_experienced_reviewer"
    assert {"R1", "R2"} <= set(deletion.fired)  # v1 reads the product rules (R2 = mass deletion)


async def test_run_items_records_k1_k3_latency_and_one_receipt_per_item(tmp_path: Path) -> None:
    snapshots = {s.changeset.id: s for s in [await _snapshot("01"), await _snapshot("04")]}
    calls: list[str] = []
    client = _decider(calls)

    async def provider(cs: int) -> EvidenceSnapshot:
        return snapshots[cs]

    runs = await run_items(sorted(snapshots), provider, CONFIG, client, receipts_dir=tmp_path)
    await client.aclose()
    assert calls.count("/v1/systemone") == 2  # one request per item
    for run in runs:
        assert run.error is None
        assert run.k1_nature and run.k3_nature and run.k1_response and run.k3_response
        assert run.latency_ms is not None and run.max_p_nature is not None
        receipt = json.loads((tmp_path / f"{run.changeset_id}.json").read_text("utf-8"))
        assert receipt["config_version"] == CONFIG.version
        assert receipt["identity"]["model"]
        assert set(receipt["outputs"]) >= {"permutations", "nature", "response"}
        assert len(receipt["outputs"]["permutations"]) == 6


async def test_decider_failure_is_recorded_not_defaulted() -> None:
    snapshot = await _snapshot("01")

    async def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(500)
            if request.url.path != "/health"
            else httpx.Response(
                200, json=json.loads((PATTERN_FIXTURES / "health.json").read_text("utf-8"))
            )
        )

    http = httpx.AsyncClient(base_url="http://decider.test", transport=httpx.MockTransport(handler))
    client = DeciderClient("http://decider.test", http=http)

    async def provider(_cs: int) -> EvidenceSnapshot:
        return snapshot

    (run,) = await run_items([snapshot.changeset.id], provider, CONFIG, client)
    await client.aclose()
    assert run.error and "DeciderUnavailable" in run.error
    assert run.k3_nature is None and run.k1_nature is None


async def test_rules_only_run_without_a_decider_client() -> None:
    snapshot = await _snapshot("02")

    async def provider(_cs: int) -> EvidenceSnapshot:
        return snapshot

    (run,) = await run_items([snapshot.changeset.id], provider, CONFIG, None)
    assert run.k3_nature is None and run.rules_nature


def test_run_on_heldout_is_refused_without_released_and_calls_no_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_frozen(EvalPaths(tmp_path), Split((1, 2), (3, 4), ()))
    monkeypatch.setenv(EVAL_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("CSO_DECIDER_URL", "http://127.0.0.1:1")
    touched: list[str] = []

    def boom(*_a: object, **_k: object) -> None:
        touched.append("decider")
        raise AssertionError("the Decider must not be contacted")

    monkeypatch.setattr(DeciderClient, "from_settings", classmethod(lambda cls, s: boom()))
    assert main(["eval", "run", "--set", "heldout"]) == 1
    assert "--released" in capsys.readouterr().err
    assert touched == []


def test_summary_excludes_failed_runs_from_decider_scores() -> None:
    gold = {1: GoldLabel("dev", 1, "consistent_edit", "no_action_suggested", "agree", None, "t")}
    failed = ItemRun(1, "consistent_edit", "no_action_suggested", (), error="DeciderTimeout: x")
    summary = summarise([failed], gold, order_sensitivity_cap=0.3)
    assert summary.n_scored == 0 and summary.n_decider_failures == 1
