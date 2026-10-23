"""MapRoulette public task listing (GET only) used as an import source and for weak labels."""

from __future__ import annotations

import re
from typing import Any, TypedDict

import anyio
import httpx

from cso.adapters.osm.client import (
    CALL_TIMEOUT_S,
    MAX_RESPONSE_BYTES,
    SafeGetClient,
    Sleep,
)
from cso.adapters.osm.errors import ParseError

MAPROULETTE_HOST = "maproulette.org"
MAPROULETTE_BASE = f"https://{MAPROULETTE_HOST}/api/v2"
MAX_TASKS = 1000
_CHANGESET_ID_RE = re.compile(r"[0-9]{1,13}")


class RouletteTask(TypedDict):
    """A MapRoulette task reduced to what the import and label flows need."""

    changeset_id: int
    status: int
    task_id: int


def _changeset_id(task: dict[str, Any]) -> int | None:
    """changeset_id lives in geometries.features[*].properties as a string (top-level is -1)."""
    geometries = task.get("geometries")
    features = geometries.get("features") if isinstance(geometries, dict) else None
    for feature in features if isinstance(features, list) else []:
        props = feature.get("properties") if isinstance(feature, dict) else None
        raw = props.get("changeset_id") if isinstance(props, dict) else None
        # ASCII digits only: `str.isdigit()` accepts "²" and other digits `int()` rejects
        if isinstance(raw, int | str) and _CHANGESET_ID_RE.fullmatch(str(raw)) and int(raw) > 0:
            return int(raw)
    return None


class MapRouletteClient(SafeGetClient):
    """Read-only MapRoulette client (host allowlist: maproulette.org)."""

    def __init__(
        self,
        *,
        user_agent: str,
        http: httpx.AsyncClient | None = None,
        sleep: Sleep = anyio.sleep,
        timeout_s: float = CALL_TIMEOUT_S,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        super().__init__(
            allowed_hosts=frozenset({MAPROULETTE_HOST}),
            user_agent=user_agent,
            http=http,
            sleep=sleep,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
        )

    async def list_challenge_tasks(self, challenge_id: int, limit: int = 50) -> list[RouletteTask]:
        """GET /challenge/{id}/tasks?limit=; tasks without a usable changeset id are skipped."""
        if challenge_id <= 0 or limit <= 0:
            raise ValueError("challenge_id and limit must be positive")
        data = await self.get_json(
            f"{MAPROULETTE_BASE}/challenge/{challenge_id}/tasks",
            params={"limit": str(min(limit, MAX_TASKS))},
        )
        if not isinstance(data, list):
            raise ParseError("MapRoulette tasks: expected a JSON array")
        tasks: list[RouletteTask] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            changeset_id = _changeset_id(item)
            task_id, status = item.get("id"), item.get("status")
            if changeset_id is None or not isinstance(task_id, int) or not isinstance(status, int):
                continue
            tasks.append({"changeset_id": changeset_id, "status": status, "task_id": task_id})
        return tasks
