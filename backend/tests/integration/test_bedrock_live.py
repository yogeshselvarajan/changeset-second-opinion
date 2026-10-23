"""Live Bedrock smoke test for fixture 02. Skipped unless CSO_LIVE_BEDROCK=1.

This makes a real, billed Converse call and needs AWS credentials with `bedrock:InvokeModel` on the
Claude Haiku 4.5 inference profile. It must only be run by a person who has agreed to the spend:

    CSO_LIVE_BEDROCK=1 uv run pytest tests/integration/test_bedrock_live.py -q -s

Nothing here posts anywhere; it only checks that a validated draft comes back.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cso.adapters.bedrock import DraftBudget, build_drafter, produce_draft
from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.enums import DraftStatus, Response
from cso.domain.evidence import render
from cso.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("CSO_LIVE_BEDROCK") != "1",
    reason="live Bedrock test: set CSO_LIVE_BEDROCK=1 (billed; needs AWS credentials)",
)

CASES = Path(__file__).resolve().parents[2] / "fixtures" / "cases"


async def test_a_real_haiku_draft_for_fixture_02_validates() -> None:
    settings = Settings(
        mode="live",
        user_agent="CSOLiveTest/0.1 (+https://example.org/repo; test@example.org)",
    )
    drafter = build_drafter(settings)
    assert drafter is not None, "the live guard did not pass (mode live and CSO_LIVE_BEDROCK=1)"

    config = CommunityConfig.load()
    case_dir = next(p for p in sorted(CASES.iterdir()) if p.name.startswith("02"))
    client = ReplayClient(case_dir)
    snapshot = await collect(client, client.case.changeset.id)
    evidence = render(snapshot, config, profile="compact")

    budget = DraftBudget(max_calls=2, max_tokens=20_000)
    outcome = await produce_draft(
        response_type=Response.WELCOME_AND_TIPS,
        evidence=evidence,
        tone=config.tone,
        language="en",
        drafter=drafter,
        budget=budget,
    )
    print(
        f"status={outcome.status.value} calls={outcome.usage['model_calls']} "
        f"input_tokens={outcome.usage['input_tokens']} "
        f"output_tokens={outcome.usage['output_tokens']} "
        f"fallback={outcome.usage.get('fallback_reason')}"
    )
    assert outcome.status is DraftStatus.VALIDATED, outcome.usage
    assert outcome.validation.ok
