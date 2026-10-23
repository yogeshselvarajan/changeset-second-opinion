"""What the pipeline needs from the outside world, behind small seams so tests inject fakes.

- `OsmSourceProvider`: live (one shared GET-only client) or replay (a fresh fixture client per job).
- `PanelDecider`: the real single-flight `DeciderClient`, or anything with `decide_panel`.
- `Deps`: those plus the community config, the collect budget and caches.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import anyio

from cso.adapters.bedrock import DraftBudget, Drafter
from cso.adapters.decider.client import DeciderClient, PanelResult
from cso.adapters.decider.errors import DeciderError
from cso.adapters.osm import CollectBudget, OsmClient, OsmSource, PriorVersionCache, ReplayClient
from cso.adapters.osm.errors import NotFoundError
from cso.domain.config import CommunityConfig, default_config_path
from cso.domain.enums import Response
from cso.jobs.spend import LedgerSpend
from cso.settings import Settings

if TYPE_CHECKING:
    from strands.models import Model

FIXTURES_DIR_ENV = "CSO_FIXTURES_DIR"


def default_fixtures_dir() -> Path:
    """The recorded demo set (`backend/fixtures/demo`), or $CSO_FIXTURES_DIR."""
    override = os.environ.get(FIXTURES_DIR_ENV)
    return Path(override) if override else Path(__file__).resolve().parents[3] / "fixtures" / "demo"


class OsmSourceProvider(Protocol):
    """Hands the pipeline an `OsmSource` for one changeset."""

    def source_for(self, changeset_id: int) -> OsmSource:
        """The source to collect this changeset from; raises NotFoundError if there is none."""
        ...

    async def aclose(self) -> None:
        """Release any shared resources."""
        ...


class PanelDecider(Protocol):
    """The one Decider call the pipeline makes."""

    async def decide_panel(self, state: str, config: CommunityConfig) -> PanelResult:
        """Ask the fact panel about the rendered evidence."""
        ...


class LiveOsmProvider:
    """One shared `OsmClient` (GET only, allowlisted hosts, at most two calls in flight)."""

    def __init__(self, client: OsmClient) -> None:
        self._client = client

    def source_for(self, changeset_id: int) -> OsmSource:
        return self._client

    async def aclose(self) -> None:
        await self._client.aclose()


class ReplayOsmProvider:
    """Serves changesets from fixture directories, matched by changeset id; no network."""

    def __init__(self, fixtures_dir: Path) -> None:
        root = fixtures_dir / "cases" if (fixtures_dir / "cases").is_dir() else fixtures_dir
        self._by_id: dict[int, Path] = {}
        self._by_name: dict[str, Path] = {}
        for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = case_dir / "changeset.json"
            if not meta.is_file():
                continue
            try:
                changeset_id = int(json.loads(meta.read_text(encoding="utf-8"))["changeset"]["id"])
            except (KeyError, TypeError, ValueError):
                continue
            self._by_id[changeset_id] = case_dir
            self._by_name[case_dir.name] = case_dir

    def changeset_id_of(self, fixture_name: str) -> int:
        """Changeset id of a fixture directory name such as `02-good-faith-mistake`."""
        case_dir = self._by_name.get(fixture_name)
        if case_dir is None:
            raise NotFoundError(f"no fixture named {fixture_name!r}")
        return next(cid for cid, path in self._by_id.items() if path == case_dir)

    def source_for(self, changeset_id: int) -> OsmSource:
        case_dir = self._by_id.get(changeset_id)
        if case_dir is None:
            raise NotFoundError(f"no replay fixture for changeset {changeset_id}")
        return ReplayClient(case_dir)  # fresh client: its call counter is per collection

    async def aclose(self) -> None:
        return None


class DeciderNotConfigured(DeciderError):
    """No Decider URL is set. Retrying cannot help, so the run falls back to rules at once."""

    failure_code = "decider_not_configured"
    permanent = True


class UnavailableDecider:
    """Stands in when no Decider is configured: every call fails, so runs fall back to rules."""

    def __init__(self, reason: str = "no Decider is configured (set CSO_DECIDER_URL)") -> None:
        self._reason = reason

    async def decide_panel(self, state: str, config: CommunityConfig) -> PanelResult:
        raise DeciderNotConfigured(self._reason)


@dataclass
class DraftingDeps:
    """What the draft job uses. All defaults are offline: templates and the scripted agent model.

    `drafter` is a real Bedrock drafter only when live mode AND CSO_LIVE_BEDROCK=1 (see
    `build_drafting_deps`); `model_for` builds the Strands model for one response type.
    """

    drafter: Drafter | None = None
    budget: DraftBudget | None = None  # per-process burst limiter only
    model_for: Callable[[Response], Model] | None = None
    spend: LedgerSpend | None = None  # the daily dollar ceiling (see jobs.spend)


@dataclass
class Deps:
    """Everything `run_analyze` uses. The lock keeps Decider calls strictly one at a time."""

    osm: OsmSourceProvider
    decider: PanelDecider
    config: CommunityConfig
    config_yaml: str
    budget: CollectBudget = field(default_factory=CollectBudget)
    cache: PriorVersionCache = field(default_factory=PriorVersionCache)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    decider_lock: anyio.Lock = field(default_factory=anyio.Lock)
    drafting: DraftingDeps | None = None  # None means offline templates (see DraftingDeps)


def build_drafting_deps(settings: Settings) -> DraftingDeps:
    """Offline unless live mode and CSO_LIVE_BEDROCK=1; no AWS client is created otherwise."""
    from cso.adapters.bedrock import build_drafter
    from cso.agent import build_agent_model

    return DraftingDeps(
        drafter=build_drafter(settings),
        budget=DraftBudget.from_env(),
        model_for=lambda response_type: build_agent_model(settings, response_type),
        spend=LedgerSpend.from_settings(settings),
    )


def build_deps(settings: Settings, *, fixtures_dir: Path | None = None) -> Deps:
    """Wire the dependencies for `settings.mode`; live mode needs a real User-Agent."""
    yaml_path = default_config_path()
    config = CommunityConfig.load(yaml_path)
    osm: OsmSourceProvider
    if settings.mode == "live":
        settings.require_real_user_agent()
        osm = LiveOsmProvider(OsmClient.from_settings(settings))
    else:
        osm = ReplayOsmProvider(fixtures_dir or default_fixtures_dir())
    decider: PanelDecider = (
        DeciderClient.from_settings(settings) if settings.decider_url else UnavailableDecider()
    )
    return Deps(
        osm=osm,
        decider=decider,
        config=config,
        config_yaml=yaml_path.read_text(encoding="utf-8"),
        drafting=build_drafting_deps(settings),
    )
