"""Snapshots, runs, drafts, configs, audit and sessions: round trips through the repositories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from persistence_support import config, make_draft, make_result, store_case, store_draft
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.domain.enums import DraftStatus, Lane, Response, RunStatus
from cso.domain.models import EvidenceSnapshot
from cso.domain.receipt import build_receipt
from cso.persistence.db import session_scope
from cso.persistence.errors import NotFoundError
from cso.persistence.repos import (
    AuditRepo,
    ConfigsRepo,
    DraftsRepo,
    RunsRepo,
    SessionsRepo,
    SnapshotsRepo,
)


async def test_snapshot_round_trips_exactly(
    factory: async_sessionmaker[AsyncSession], snapshot_02: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_02, with_run=False)
    async with factory() as s:
        loaded = await SnapshotsRepo(s).get(stored.snapshot_id)
        latest = await SnapshotsRepo(s).latest_for_case(stored.case_id)
        by_version = await SnapshotsRepo(s).get_by_version(
            stored.case_id, snapshot_02.evidence_version
        )
    assert loaded is not None and latest is not None and by_version is not None
    expected = snapshot_02.model_copy(update={"id": stored.snapshot_id, "case_id": stored.case_id})
    assert loaded == expected
    assert latest == expected
    assert by_version.id == stored.snapshot_id


async def test_run_round_trips_with_receipt(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    cfg, _ = config()
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        result = make_result(
            cfg.version, lane=Lane.NEEDS_LOCAL_KNOWLEDGE, snapshot_id=stored.snapshot_id
        )
        receipt = build_receipt(
            snapshot_01, config_version=cfg.version, lane=Lane.NEEDS_LOCAL_KNOWLEDGE
        )
        run_id = await RunsRepo(s).add(
            stored.case_id, stored.snapshot_id, result, receipt=receipt, decider_checkpoint="ckpt"
        )
    async with factory() as s:
        repo = RunsRepo(s)
        loaded = await repo.get(run_id)
        row = await repo.get_row(run_id)
        latest = await repo.latest_for_case(stored.case_id)
    assert loaded is not None and row is not None and latest is not None
    assert loaded.lane is Lane.NEEDS_LOCAL_KNOWLEDGE
    assert loaded.status is RunStatus.SUCCEEDED
    assert loaded.nature_probabilities == result.nature_probabilities
    assert loaded.config_version == cfg.version
    assert row.decider_checkpoint == "ckpt"
    assert row.receipt is not None and row.receipt["lane"] == "needs_local_knowledge"
    assert latest.id == run_id


async def test_failed_run_keeps_its_reason(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    cfg, _ = config()
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        failed = make_result(cfg.version, lane=Lane.RULES_ONLY, snapshot_id=stored.snapshot_id)
        failed = failed.model_copy(
            update={"status": RunStatus.FAILED, "failure_code": "decider_unavailable"}
        )
        run_id = await RunsRepo(s).add(stored.case_id, stored.snapshot_id, failed)
    async with factory() as s:
        loaded = await RunsRepo(s).get(run_id)
    assert loaded is not None
    assert loaded.status is RunStatus.FAILED
    assert loaded.failure_code == "decider_unavailable"
    assert loaded.lane is Lane.RULES_ONLY


async def test_runs_list_newest_first(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    cfg, _ = config()
    base = datetime(2026, 10, 17, tzinfo=UTC)
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        ids = [
            await RunsRepo(s).add(
                stored.case_id,
                stored.snapshot_id,
                make_result(cfg.version, snapshot_id=stored.snapshot_id),
                now=base + timedelta(minutes=i),
            )
            for i in range(3)
        ]
        runs = await RunsRepo(s).list_for_case(stored.case_id)
    assert [r.id for r in runs] == list(reversed(ids))


async def test_draft_round_trip_and_latest_for_run(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01)
        first = await store_draft(s, stored)
        second = await DraftsRepo(s).add(
            stored.case_id,
            make_draft(stored.run_id).model_copy(update={"status": DraftStatus.TEMPLATE_FALLBACK}),
            config_version=config()[0].version,
            now=datetime.now(UTC) + timedelta(seconds=5),
        )
    async with factory() as s:
        repo = DraftsRepo(s)
        latest = await repo.latest_for_run(stored.run_id, Response.WELCOME_AND_TIPS)
        other_type = await repo.latest_for_run(stored.run_id, Response.ASK_SOURCE_QUESTION)
        everything = await repo.list_for_case(stored.case_id)
        loaded = await repo.get(first)
    assert latest is not None and latest.id == second
    assert latest.status is DraftStatus.TEMPLATE_FALLBACK
    assert other_type is None
    assert [d.id for d in everything] == [second, first]
    assert loaded is not None and loaded.body == "Thanks for mapping."


async def test_draft_without_a_run_is_rejected(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
    async with factory() as s:
        with pytest.raises(ValueError, match="run"):
            await DraftsRepo(s).add(
                stored.case_id,
                make_draft(uuid4()).model_copy(update={"run_id": None}),
                config_version=config()[0].version,
            )


async def test_config_versions_and_activation(factory: async_sessionmaker[AsyncSession]) -> None:
    cfg, yaml_text = config()
    other = cfg.model_copy(update={"version": "sha256:other"})
    async with session_scope(factory) as s:
        repo = ConfigsRepo(s)
        await repo.add_if_absent(cfg, yaml_text, activate=True)
        await repo.add_if_absent(cfg, yaml_text)  # idempotent
        await repo.add_if_absent(other, yaml_text)
        versions = await repo.list_versions()
        active = await repo.get_active()
        assert active is not None and active.version == cfg.version
        await repo.activate("sha256:other")
        active_now = await repo.get_active()
        old = await repo.get(cfg.version)
        with pytest.raises(NotFoundError):
            await repo.activate("sha256:missing")
    assert len(versions) == 2
    assert active_now is not None and active_now.version == "sha256:other"
    assert old is not None and old.is_active is False


async def test_audit_events_page_in_order(
    factory: async_sessionmaker[AsyncSession], snapshot_01: EvidenceSnapshot
) -> None:
    async with session_scope(factory) as s:
        stored = await store_case(s, snapshot_01, with_run=False)
        audit = AuditRepo(s)
        for i in range(5):
            await audit.append(
                actor="a",
                action=f"act{i}",
                payload={"i": i},
                case_id=stored.case_id,
                request_id="r",
            )
        await audit.append(actor="a", action="other-case")
    async with factory() as s:
        audit = AuditRepo(s)
        first = await audit.list_for_case(stored.case_id, limit=3)
        assert first.next_after_id is not None
        second = await audit.list_for_case(stored.case_id, after_id=first.next_after_id, limit=3)
    assert [e.action for e in first.items] == ["act0", "act1", "act2"]
    assert [e.action for e in second.items] == ["act3", "act4"]
    assert second.next_after_id is None
    assert first.items[0].payload == {"i": 0}


async def test_sessions_stub(factory: async_sessionmaker[AsyncSession]) -> None:
    now = datetime(2026, 10, 17, tzinfo=UTC)
    async with session_scope(factory) as s:
        repo = SessionsRepo(s)
        invite = await repo.add_invite_code(code_hash="h1", role="reviewer", label="demo", now=now)
        session = await repo.create_session(
            invite_code_id=invite.id,
            display_name="Reviewer A",
            role="reviewer",
            expires_at=now + timedelta(hours=1),
            now=now,
        )
        found = await repo.get_invite_by_hash("h1")
        assert found is not None and found.id == invite.id
        assert await repo.get_active(session.id, now=now) is not None
        assert await repo.get_active(session.id, now=now + timedelta(hours=2)) is None
        assert await repo.revoke(session.id) is True
        assert await repo.get_active(session.id, now=now) is None
        assert await repo.revoke(uuid4()) is False
