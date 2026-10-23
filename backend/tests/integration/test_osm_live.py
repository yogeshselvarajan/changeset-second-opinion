"""Live read-only check against api.openstreetmap.org (GET only). Run with CSO_LIVE_TESTS=1."""

from __future__ import annotations

import os

import pytest

from cso.adapters.osm import CollectBudget, OsmClient, collect
from cso.domain.enums import EvidenceSource
from cso.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("CSO_LIVE_TESTS") != "1", reason="set CSO_LIVE_TESTS=1 to call the live OSM API"
)

CHANGESET = 150000000
MAX_CALLS = 6


async def test_prior_tags_are_reconstructed_within_six_calls() -> None:
    client = OsmClient.from_settings(get_settings())
    try:
        snap = await collect(client, CHANGESET, CollectBudget(max_total_calls=MAX_CALLS))
    finally:
        await client.aclose()
    print(
        f"\ncs {CHANGESET}: {client.calls} logical calls, {client.http_attempts} HTTP requests, "
        f"{snap.coverage.elements_detailed}/{snap.coverage.elements_in_changeset} detailed, "
        f"{len(snap.coverage.history_gaps)} gaps, {len(snap.tag_diffs)} tag diffs"
    )

    assert snap.source is EvidenceSource.OSM_API
    assert client.calls <= MAX_CALLS
    assert any(e.tags_before is not None for e in snap.elements), "no prior tags reconstructed"
    assert snap.changeset.attribution.get("license")
