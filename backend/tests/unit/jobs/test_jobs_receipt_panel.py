"""The pipeline stores the table rows that fired and the parsed cross-checks in the receipt."""

from __future__ import annotations

from collections.abc import Callable

from jobs_support import (
    FakePanelDecider,
    ManualClock,
    config,
    enqueue_fixture,
    make_deps,
    runs_of,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cso.adapters.decider.errors import DeciderUnavailable
from cso.domain.receipt import DecisionReceipt
from cso.jobs import Worker

Factory = async_sessionmaker[AsyncSession]


async def test_successful_run_stores_composition_and_cross_checks(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    await make_worker().run_until_idle()

    run = (await runs_of(factory, case_id))[0]
    assert run.receipt is not None
    composition = run.receipt["panel_composition"]
    assert composition["response_row"].startswith("P") and composition["nature_row"].startswith("N")
    assert composition["response"] == run.response and composition["nature"] == run.nature
    assert isinstance(composition["yes"], list) and isinstance(composition["unknown"], list)
    cross_checks = run.receipt["panel_cross_checks"]
    assert cross_checks and set(cross_checks.values()) <= {"agree", "disagree", "undecided", "n/a"}
    # The stored JSON loads back into the receipt model with both fields intact.
    receipt = DecisionReceipt.model_validate(run.receipt)
    assert receipt.panel_composition == composition and receipt.panel_cross_checks == cross_checks


async def test_failed_run_has_no_composition(
    factory: Factory, clock: ManualClock, make_worker: Callable[..., Worker]
) -> None:
    decider = FakePanelDecider(config()[0], failures=[DeciderUnavailable("down")] * 3)
    case_id, _ = await enqueue_fixture(factory, 2, clock)
    worker = make_worker(deps=make_deps(decider))
    for _ in range(3):
        await worker.run_until_idle()
        clock.advance(120)
    runs = await runs_of(factory, case_id)
    failed = [r for r in runs if r.status == "failed"]
    assert failed, "the Decider never recovered, so a failed run is stored"
    receipt = failed[-1].receipt
    assert receipt is not None
    assert receipt.get("panel_composition") is None and receipt.get("panel_cross_checks") is None
    assert DecisionReceipt.model_validate(receipt).panel is None
