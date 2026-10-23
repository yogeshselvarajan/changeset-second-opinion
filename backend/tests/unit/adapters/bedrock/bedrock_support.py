"""Shared helpers for the Bedrock adapter tests: real fixture evidence and a no-op sleeper."""

from __future__ import annotations

from pathlib import Path

from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.evidence import RenderedEvidence, render

CONFIG = CommunityConfig.load()
TONE = CONFIG.tone
CASES = Path(__file__).resolve().parents[4] / "fixtures" / "cases"


async def fixture_evidence(prefix: str) -> RenderedEvidence:
    """The compact evidence block of the fixture whose directory starts with `prefix`."""
    case_dir = next(p for p in sorted(CASES.iterdir()) if p.name.startswith(prefix))
    client = ReplayClient(case_dir)
    snapshot = await collect(client, client.case.changeset.id)
    return render(snapshot, CONFIG, profile="compact")


class Sleeps:
    """An injectable sleep that records the delays instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
