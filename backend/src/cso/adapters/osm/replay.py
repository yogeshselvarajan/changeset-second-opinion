"""ReplayClient: serves a fixture directory through the same protocol as the live client.

Marker files (see backend/fixtures/schema.md) make a call fail like the real API would:
`__403__` raises Redacted403, `__timeout__` raises OsmTimeoutError.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cso.adapters.osm.errors import NotFoundError, OsmTimeoutError, ParseError, Redacted403
from cso.adapters.osm.protocol import MAX_MULTIFETCH_IDS
from cso.domain.enums import OsmType
from cso.domain.fixtures import FixtureCase, Marker, load_case


def _raise_for(marker: Marker, what: str) -> None:
    if marker is Marker.FORBIDDEN:
        raise Redacted403(f"replay marker __403__ for {what}")
    raise OsmTimeoutError(f"replay marker __timeout__ for {what}")


class ReplayClient:
    """OsmSource backed by one validated fixture case directory."""

    def __init__(self, case_dir: Path | str) -> None:
        self._dir = Path(case_dir)
        self.case: FixtureCase = load_case(self._dir)
        self._user_raw: dict[str, Any] | None = None
        if self.case.user_marker is None:
            try:
                self._user_raw = json.loads((self._dir / "user.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:  # load_case already validated; defensive
                raise ParseError(f"cannot read user.json: {exc}") from exc
        self.calls = 0

    def _check_changeset(self, changeset_id: int) -> None:
        if changeset_id != self.case.changeset.id:
            raise NotFoundError(f"replay case {self.case.name} has no changeset {changeset_id}")

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        """Return changeset.json (hidden comments are dropped by the converter, as live)."""
        self.calls += 1
        self._check_changeset(changeset_id)
        return copy.deepcopy(self.case.changeset_raw)

    async def get_osc(self, changeset_id: int) -> bytes:
        """Return download.osc bytes."""
        self.calls += 1
        self._check_changeset(changeset_id)
        return self.case.osc_xml.encode("utf-8")

    async def get_element_version(
        self, osm_type: OsmType, osm_id: int, version: int
    ) -> dict[str, Any]:
        """Return prev/<type>_<id>_<version>.json's element, or raise per marker/NotFound."""
        self.calls += 1
        key = (osm_type, osm_id, version)
        data = self.case.prev.get(key)
        if data is not None:
            return copy.deepcopy(data["elements"][0])
        marker = self.case.prev_markers.get(key)
        if marker is not None:
            _raise_for(marker, f"{osm_type.value}/{osm_id}/{version}")
        raise NotFoundError(f"replay has no {osm_type.value}/{osm_id}/{version}")

    async def get_element_history(self, osm_type: OsmType, osm_id: int) -> list[dict[str, Any]]:
        """Readable versions from prev/ (ascending). Redacted-only elements yield [] like the API.

        With no readable version, a `__timeout__` marker raises OsmTimeoutError and no data or
        marker at all raises NotFoundError.
        """
        self.calls += 1
        found = sorted(
            (v, data) for (t, i, v), data in self.case.prev.items() if (t, i) == (osm_type, osm_id)
        )
        if found:
            return [copy.deepcopy(data["elements"][0]) for _v, data in found]
        markers = [
            m for (t, i, _v), m in self.case.prev_markers.items() if (t, i) == (osm_type, osm_id)
        ]
        if Marker.TIMEOUT in markers:
            _raise_for(Marker.TIMEOUT, f"{osm_type.value}/{osm_id} history")
        if markers:
            return []
        raise NotFoundError(f"replay has no history for {osm_type.value}/{osm_id}")

    async def get_elements(
        self, osm_type: OsmType, osm_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        """Highest available version per id from prev/; all-or-nothing like the live API."""
        self.calls += 1
        ids = sorted(set(osm_ids))
        if len(ids) > MAX_MULTIFETCH_IDS:
            raise ValueError(f"at most {MAX_MULTIFETCH_IDS} ids per call, got {len(ids)}")
        result: dict[int, dict[str, Any]] = {}
        for osm_id in ids:
            versions = [v for (t, i, v) in self.case.prev if (t, i) == (osm_type, osm_id)]
            if not versions:
                timeouts = [
                    m
                    for (t, i, _v), m in self.case.prev_markers.items()
                    if (t, i) == (osm_type, osm_id) and m is Marker.TIMEOUT
                ]
                if timeouts:
                    _raise_for(Marker.TIMEOUT, f"{osm_type.value}/{osm_id}")
                raise NotFoundError(f"replay multi-fetch missing {osm_type.value}/{osm_id}")
            result[osm_id] = copy.deepcopy(
                self.case.prev[(osm_type, osm_id, max(versions))]["elements"][0]
            )
        return result

    async def get_user(self, uid: int) -> dict[str, Any]:
        """Return user.json, or raise per user.__403__/__timeout__ marker."""
        self.calls += 1
        if self.case.user_marker is not None:
            _raise_for(self.case.user_marker, f"user/{uid}")
        raw = self._user_raw
        if raw is None or (raw.get("user") or {}).get("id") != uid:
            raise NotFoundError(f"replay case {self.case.name} has no user {uid}")
        return copy.deepcopy(raw)
