"""Where bulk import gets changeset ids from (MapRoulette challenges), behind a small seam.

The API layer never talks to OpenStreetMap services itself. It asks a `ChallengeLister`, which is
the read-only MapRoulette client in live mode and a stand-in that explains itself in replay mode
(replay reads fixtures only). Only GET requests are ever made.
"""

from __future__ import annotations

from typing import Protocol

from cso.adapters.osm import MapRouletteClient, OsmError
from cso.settings import Settings


class ChallengeImportUnavailable(Exception):
    """Challenge import cannot run in this mode (replay reads fixtures only)."""


class ChallengeSourceError(Exception):
    """The challenge source could not be read (network, rate limit, unexpected answer)."""


class ChallengeLister(Protocol):
    """Lists the changeset ids of one challenge."""

    async def list_changeset_ids(self, challenge_id: int, limit: int) -> list[int]:
        """Distinct changeset ids of the challenge's tasks, in task order, at most `limit`."""
        ...

    async def aclose(self) -> None:
        """Release the client."""
        ...


class UnavailableChallengeLister:
    """Used in replay mode: there is no network."""

    async def list_changeset_ids(self, challenge_id: int, limit: int) -> list[int]:
        raise ChallengeImportUnavailable("Challenge import needs live mode; replay reads fixtures.")

    async def aclose(self) -> None:
        return None


class MapRouletteChallengeLister:
    """The read-only MapRoulette client (host allowlist, GET only, bounded responses)."""

    def __init__(self, settings: Settings) -> None:
        settings.require_real_user_agent()
        self._client = MapRouletteClient(user_agent=settings.user_agent)

    async def list_changeset_ids(self, challenge_id: int, limit: int) -> list[int]:
        try:
            tasks = await self._client.list_challenge_tasks(challenge_id, limit)
        except OsmError as exc:
            raise ChallengeSourceError(str(exc)[:200]) from exc
        seen: set[int] = set()
        ids: list[int] = []
        for task in tasks:
            changeset_id = task["changeset_id"]
            if changeset_id not in seen:
                seen.add(changeset_id)
                ids.append(changeset_id)
        return ids[:limit]

    async def aclose(self) -> None:
        await self._client.aclose()


def build_challenge_lister(settings: Settings) -> ChallengeLister:
    """The lister for the current mode."""
    if settings.mode == "replay":
        return UnavailableChallengeLister()
    return MapRouletteChallengeLister(settings)
