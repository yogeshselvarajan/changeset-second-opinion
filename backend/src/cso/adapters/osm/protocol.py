"""The adapter protocol shared by the live client and the replay client.

All methods return the decoded API JSON (not domain models); collect.py converts with
cso.domain.fixtures.{changeset_from_api, discussion_from_api, user_from_api}. Errors are the
classes in cso.adapters.osm.errors. `calls` counts logical API calls started (one per method
invocation, regardless of retries) so the collector can enforce its call budget and tests can
assert it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from cso.domain.enums import OsmType

MAX_MULTIFETCH_IDS = 200


@runtime_checkable
class OsmSource(Protocol):
    """Read-only source of OSM evidence."""

    calls: int

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        """changeset.json envelope with discussion (`changeset.comments`)."""
        ...

    async def get_osc(self, changeset_id: int) -> bytes:
        """Raw osmChange XML bytes (size-capped; parse with parse.parse_osm_change)."""
        ...

    async def get_element_version(
        self, osm_type: OsmType, osm_id: int, version: int
    ) -> dict[str, Any]:
        """The single element dict (`type,id,version,timestamp,visible,tags,nodes|members,...`).

        Raises Redacted403 for redacted versions and NotFoundError when absent.
        """
        ...

    async def get_element_history(self, osm_type: OsmType, osm_id: int) -> list[dict[str, Any]]:
        """Readable versions of an element, ascending by version (redacted versions are omitted)."""
        ...

    async def get_elements(
        self, osm_type: OsmType, osm_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        """Current versions of up to MAX_MULTIFETCH_IDS elements keyed by id.

        All-or-nothing like the real API: NotFoundError if any id is missing or redacted.
        """
        ...

    async def get_user(self, uid: int) -> dict[str, Any]:
        """user/{uid}.json envelope (`user{id,display_name,account_created,changesets,blocks}`)."""
        ...
