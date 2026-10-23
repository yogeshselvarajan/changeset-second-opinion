"""`cso worker` and the embedded worker: replay demo, unmigrated databases, lifespan wiring."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import anyio
import pytest
from jobs_support import FIXTURES, FakePanelDecider, config, make_deps
from sqlalchemy.ext.asyncio import create_async_engine

from cso import cli
from cso.domain.enums import JobStatus
from cso.jobs import EmbeddedWorker, run_worker_cli
from cso.jobs import runtime as runtime_module
from cso.main import create_app, lifespan
from cso.persistence.db import make_engine, make_sessionmaker, session_scope
from cso.persistence.repos import CasesRepo, JobsRepo, RunsRepo
from cso.persistence.tables import Base
from cso.settings import Settings, get_settings


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(
        mode="replay",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'demo.db'}",
        decider_url=None,
        jobs_worker_enabled=False,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
def clean_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_fixture_demo_without_a_decider_prints_the_rules_only_run(tmp_path: Path) -> None:
    lines: list[str] = []

    code = await run_worker_cli(
        _settings(tmp_path),
        once=True,
        fixture="02-good-faith-mistake",
        fixtures_dir=FIXTURES,
        out=lines.append,
    )

    text = "\n".join(lines)
    assert code == 1  # the job failed (no Decider), but a run was stored and printed
    assert "failed error=decider_not_configured" in text
    assert "lane=rules_only" in text and "status=failed" in text
    assert "timing_ms=" in text


async def test_fixture_demo_with_a_decider_prints_lane_response_and_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakePanelDecider(config()[0])
    monkeypatch.setattr(
        runtime_module, "build_deps", lambda settings, fixtures_dir=None: make_deps(fake)
    )
    lines: list[str] = []

    code = await run_worker_cli(
        _settings(tmp_path), once=True, fixture="02-good-faith-mistake", out=lines.append
    )

    text = "\n".join(lines)
    assert code == 0 and fake.calls == 1
    assert "succeeded error=None" in text
    assert "status=succeeded" in text and "lane=" in text and "lane=rules_only" not in text
    assert "'decide'" in text and "'total'" in text  # the receipt's timing fields


async def test_the_fixture_flag_needs_replay_mode_and_a_known_fixture(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    lines: list[str] = []
    with pytest.raises(Exception, match="no fixture named"):
        await run_worker_cli(settings, once=True, fixture="99-nope", out=lines.append)


async def test_plain_once_needs_a_migrated_database(tmp_path: Path) -> None:
    lines: list[str] = []
    code = await run_worker_cli(_settings(tmp_path), once=True, out=lines.append)
    assert code == 1 and "cso db upgrade" in lines[0]


def test_cli_worker_command_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_settings_cache: None,
) -> None:
    monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("CSO_MODE", "replay")
    monkeypatch.delenv("CSO_DECIDER_URL", raising=False)
    monkeypatch.setenv("CSO_FIXTURES_DIR", str(FIXTURES))

    code = cli.main(["worker", "--once", "--fixture", "02-good-faith-mistake"])

    out = capsys.readouterr().out
    assert code == 1 and "lane=rules_only" in out  # replay without a Decider falls back to rules


def test_cli_worker_reports_an_unknown_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clean_settings_cache: None,
) -> None:
    monkeypatch.setenv("CSO_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cli2.db'}")
    monkeypatch.setenv("CSO_MODE", "replay")
    monkeypatch.setenv("CSO_FIXTURES_DIR", str(FIXTURES))

    code = cli.main(["worker", "--once", "--fixture", "99-nope"])

    assert code == 1 and "no fixture named" in capsys.readouterr().err


async def test_embedded_worker_waits_for_a_migrated_database(tmp_path: Path) -> None:
    worker = EmbeddedWorker(_settings(tmp_path))

    assert await worker.start() is False  # nothing to poll yet; no crash
    await worker.stop()


async def test_embedded_worker_processes_a_job_and_stops_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSO_FIXTURES_DIR", str(FIXTURES))
    settings = _settings(tmp_path)
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_sessionmaker(engine)
    async with session_scope(factory) as session:
        from cso.jobs import enqueue_changeset

        queued = await enqueue_changeset(session, 900000000002)
    worker = EmbeddedWorker(settings, poll_interval_s=0.02)
    # the synthetic test cases, not the default demo set
    assert await worker.start() is True
    try:
        with anyio.fail_after(15):
            while True:
                async with factory() as session:
                    job = await JobsRepo(session).get(queued.job.id)
                if job is not None and job.status in (
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                ):
                    break
                await anyio.sleep(0.05)
    finally:
        await worker.stop()

    assert job.status == JobStatus.FAILED.value and job.last_error == "decider_not_configured"
    async with factory() as session:
        run = await RunsRepo(session).latest_for_case(queued.case.id)
        case = await CasesRepo(session).get(queued.case.id)
    assert run is not None and run.lane.value == "rules_only"
    assert case is not None and case.latest_run_id is not None
    await engine.dispose()


async def test_api_lifespan_starts_and_stops_the_worker_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_settings_cache: None
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'api.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    monkeypatch.setenv("CSO_DATABASE_URL", url)
    monkeypatch.setenv("CSO_MODE", "replay")

    started: list[str] = []
    real_start = EmbeddedWorker.start

    async def spy_start(self: EmbeddedWorker) -> bool:
        started.append("start")
        return await real_start(self)

    monkeypatch.setattr(EmbeddedWorker, "start", spy_start)

    monkeypatch.setenv("CSO_JOBS_WORKER_ENABLED", "false")
    get_settings.cache_clear()
    async with lifespan(create_app()):
        pass
    assert started == []  # disabled: the API process runs no worker

    monkeypatch.setenv("CSO_JOBS_WORKER_ENABLED", "true")
    get_settings.cache_clear()
    async with lifespan(create_app()):
        assert started == ["start"]
    # leaving the context stopped the worker without hanging
