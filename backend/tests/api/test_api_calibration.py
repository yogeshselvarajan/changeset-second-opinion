"""Calibration over HTTP: a dry run changes nothing; apply stores a new version; floors hold."""

from __future__ import annotations

from datetime import timedelta

import httpx
import sqlalchemy as sa
from api_support import (
    ADMIN,
    BASE_TIME,
    REVIEWER,
    Caller,
    _store_panel_run,
    config,
    fixture_snapshot,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_api_routes_cases import assert_problem

from cso.domain.enums import Disposition
from cso.domain.models import OutcomeInput
from cso.persistence.db import session_scope
from cso.persistence.repos import CasesRepo, ConfigsRepo, OutcomesRepo, RunsRepo, SnapshotsRepo
from cso.persistence.tables import AuditEventRow, CalibrationRow

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
PROBE = "mature_feature_deleted"


async def seed_outcomes(factory: Factory, agree: int, wrong_yes: int) -> None:
    """`agree` cases the reviewer agreed with (the probe read no at 0.05), and `wrong_yes` cases
    where the probe read yes at 0.75 and the reviewer said it was wrong (it should read no)."""
    cfg, yaml_text = config()
    base = await fixture_snapshot(1)
    async with session_scope(factory) as session:
        await ConfigsRepo(session).add_if_absent(cfg, yaml_text, activate=True)
        for index in range(agree + wrong_yes):
            stamp = BASE_TIME + timedelta(minutes=index)
            snapshot = base.model_copy(
                update={"changeset": base.changeset.model_copy(update={"id": 910000000000 + index})}
            )
            case, _ = await CasesRepo(session).get_or_create(snapshot.changeset.id, now=stamp)
            snapshot_id, _ = await SnapshotsRepo(session).add(case.id, snapshot, now=stamp)
            wrong = index >= agree
            run_id = await _store_panel_run(
                session,
                case.id,
                snapshot_id,
                snapshot,
                cfg,
                {PROBE: 0.75} if wrong else None,
                stamp,
            )
            await OutcomesRepo(session).append(
                case.id,
                OutcomeInput(
                    disposition=Disposition.DISAGREE_WITH_MODEL if wrong else Disposition.AGREE,
                    run_id_seen=run_id,
                    probe_corrections={PROBE: "no"} if wrong else None,
                ),
                reviewer_display="Rae Reviewer",
                session_id=None,
                expected_version=0,
                now=stamp,
            )


async def test_a_dry_run_reports_and_changes_nothing(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    await seed_outcomes(factory, agree=25, wrong_yes=5)
    caller.principal = ADMIN
    report = (await client.get(f"{API}/config/reliability")).json()
    assert report["pack_id"] == "default" and report["n_outcomes"] == 30
    probe = next(p for p in report["probes"] if p["probe"] == PROBE)
    assert probe["n"] == 30 and probe["status"] == "fitted"
    # After the fit every decided reading is right, and at least 60 percent still decide.
    assert probe["tuned_correct"] == probe["tuned_decided"]
    assert probe["coverage"] >= 0.6
    # The five wrong yes readings pull the default accuracy down; the fit moves the high cut up.
    assert probe["correct"] < probe["decided"]
    assert probe["default_high"] == 0.65 and probe["high"] > probe["default_high"]
    assert 0.15 <= probe["low"] < probe["high"] <= 0.85
    async with session_scope(factory) as session:
        rows = (await session.execute(sa.select(CalibrationRow))).scalars().all()
        active = await ConfigsRepo(session).get_active()
    assert rows == [] and active is not None and active.calibration_id is None


async def test_a_probe_with_too_few_labels_keeps_the_pack_default(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    await seed_outcomes(factory, agree=3, wrong_yes=0)
    caller.principal = ADMIN
    report = (await client.get(f"{API}/config/reliability")).json()
    assert all(p["status"] == "insufficient_data" for p in report["probes"])
    assert all(
        (p["low"], p["high"]) == (p["default_low"], p["default_high"]) for p in report["probes"]
    )
    result = (await client.post(f"{API}/config/calibrate", json={"apply": True})).json()
    assert result["applied"] is False and "enough" in result["reason"]


async def test_apply_stores_a_new_version_and_old_runs_keep_theirs(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    await seed_outcomes(factory, agree=25, wrong_yes=5)
    async with session_scope(factory) as session:
        rows = await RunsRepo(session).list_rows_for_case(
            (await CasesRepo(session).get_by_changeset(910000000000)).id  # type: ignore[union-attr]
        )
        before_version = rows[0].config_version
    caller.principal = ADMIN
    result = (await client.post(f"{API}/config/calibrate", json={"apply": True})).json()
    assert result["applied"] is True and result["calibration_id"].startswith("cal-")
    assert result["config_version"] != before_version

    active = (await client.get(f"{API}/config")).json()
    assert active["version"] == result["config_version"]
    assert active["calibration"]["id"] == result["calibration_id"]
    tuned = active["panel"]["probe_thresholds"][PROBE]
    assert tuned["high"] > 0.65 and 0.15 <= tuned["low"] < tuned["high"] <= 0.85
    assert active["rules"]  # rules are untouched by calibration

    async with session_scope(factory) as session:
        events = (
            (
                await session.execute(
                    sa.select(AuditEventRow).where(
                        AuditEventRow.action == "config.calibration_applied"
                    )
                )
            )
            .scalars()
            .all()
        )
        stored = await ConfigsRepo(session).get_active()
        old = await RunsRepo(session).list_rows_for_case(
            (await CasesRepo(session).get_by_changeset(910000000000)).id  # type: ignore[union-attr]
        )
    assert len(events) == 1 and events[0].actor.startswith("admin:")
    assert stored is not None and stored.calibration_id == result["calibration_id"]
    assert old[0].config_version == before_version


async def test_only_an_admin_can_calibrate(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = REVIEWER
    assert_problem(await client.post(f"{API}/config/calibrate", json={}), 403, "forbidden")
    assert_problem(await client.get(f"{API}/config/reliability"), 403, "forbidden")


async def test_an_unknown_pack_is_404(client: httpx.AsyncClient, caller: Caller) -> None:
    caller.principal = ADMIN
    assert_problem(
        await client.post(f"{API}/config/calibrate", json={"pack_id": "nope"}), 404, "not_found"
    )


async def test_corrections_are_refused_on_an_agreement_and_for_unknown_probes(
    client: httpx.AsyncClient, caller: Caller, factory: Factory
) -> None:
    await seed_outcomes(factory, agree=1, wrong_yes=0)
    caller.principal = REVIEWER
    async with session_scope(factory) as session:
        case = await CasesRepo(session).get_by_changeset(910000000000)
        assert case is not None
        run_id = case.latest_run_id
        case_id = case.id
    headers = {"If-Match": 'W/"1"'}
    agree = {"disposition": "agree", "run_id_seen": str(run_id), "probe_corrections": {PROBE: "no"}}
    assert (
        await client.put(f"{API}/cases/{case_id}/outcome", json=agree, headers=headers)
    ).status_code == 422
    unknown = {
        "disposition": "disagree_with_model",
        "run_id_seen": str(run_id),
        "probe_corrections": {"not_a_probe": "no"},
    }
    assert (
        await client.put(f"{API}/cases/{case_id}/outcome", json=unknown, headers=headers)
    ).status_code == 422
