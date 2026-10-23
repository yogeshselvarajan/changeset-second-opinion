"""Shared fakes for the held-out tests: a recording Decider, a Haiku fake, a frozen temp git repo.

Nothing here touches the network, AWS, the real `evaluation/` data or this repository's git
configuration: every repository is created under pytest's tmp_path.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from cso.adapters.bedrock.fake import FakeBedrockRuntime
from cso.adapters.decider import DeciderClient
from cso.adapters.osm import ReplayClient, collect
from cso.domain.config import CommunityConfig
from cso.domain.fixtures import load_case
from cso.domain.models import EvidenceSnapshot
from cso.domain.panel import PANEL_NOUL_IDS
from cso.evaluation.haiku_baseline import (
    TOOL_NAME,
    HaikuBaseline,
    SpendTracker,
)
from cso.evaluation.labels import LABELLED_PROBES, NOT_COLLECTED, GoldLabel
from cso.evaluation.paths import EvalPaths
from cso.evaluation.split import Split, write_frozen

ROOT = Path(__file__).resolve().parents[4]
CASES = ROOT / "backend" / "fixtures" / "cases"
CONFIG = CommunityConfig.load()
HEALTH = {
    "status": "ok",
    "model": "strands-decider-2B-qwen3.5-v1-2610",
    "checkpoint": "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610",
    "base_model": "Qwen/Qwen3.5-2B-Base",
    "num_slots": 24,
    "max_length": 4096,
    "temperature": 1.0,
    "device": "cuda",
    "prefix_cache": True,
}
GOOD_UA = "ChangesetSecondOpinion/0.1 (+https://example.org/repo; someone@example.org)"


_SNAPSHOTS: dict[int, EvidenceSnapshot] = {}


async def all_snapshots() -> dict[int, EvidenceSnapshot]:
    """The eight replay fixtures collected into snapshots, keyed by changeset id (cached).

    Collection replays a timeout fixture with real backoff, so it takes seconds; snapshots are
    immutable models, so one copy per process is safe to share across tests.
    """
    if not _SNAPSHOTS:
        for case_dir in sorted(CASES.iterdir()):
            cs = load_case(case_dir).expected.changeset_id
            _SNAPSHOTS[cs] = await collect(ReplayClient(case_dir), cs)
    return dict(_SNAPSHOTS)


def provider(snaps: dict[int, EvidenceSnapshot]) -> Callable[[int], Any]:
    async def get(cs: int) -> EvidenceSnapshot:
        return snaps[cs]

    return get


def decider(
    *,
    bodies: list[dict[str, Any]] | None = None,
    health_status: int = 200,
    server_ms: float = 400.0,
) -> DeciderClient:
    """A Decider whose panel answers 'no' everywhere except 'comment' and 'conventions' (yes).

    Every request body sent to `/v1/systemone` is appended to `bodies`.
    """
    probs = {c.code: 0.25 for c in CONFIG.option_sets.nature}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if health_status != 200:
                return httpx.Response(health_status, json={"detail": "down"})
            return httpx.Response(200, json=HEALTH)
        import json

        body = json.loads(request.content)
        if bodies is not None:
            bodies.append(body)
        answers: dict[str, Any] = {
            "nature": {
                "type": "choice",
                "choice": "consistent_edit",
                "probabilities": probs,
                "confidence": 0.1,
            }
        }
        for noul_id in PANEL_NOUL_IDS:
            answers[noul_id] = {"type": "noul", "noul": 0.1}
        answers["comment_matches_changes"] = {"type": "noul", "noul": 0.9}
        answers["conventions_followed"] = {"type": "noul", "noul": 0.9}
        return httpx.Response(
            200,
            json={
                "model": HEALTH["model"],
                "answers": answers,
                "usage": {"input_tokens": 700, "output_tokens": 0},
                "latency_ms": server_ms,
            },
        )

    http = httpx.AsyncClient(base_url="http://decider.test", transport=httpx.MockTransport(handler))
    return DeciderClient("http://decider.test", http=http)


def haiku_reply(
    nature: str, response: str, *, input_tokens: int = 600, output_tokens: int = 20
) -> dict[str, Any]:
    """A Converse reply that calls the decision tool."""
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "t1",
                            "name": TOOL_NAME,
                            "input": {"nature": nature, "response": response},
                        }
                    }
                ],
            }
        },
        "usage": {"inputTokens": input_tokens, "outputTokens": output_tokens},
    }


def fake_haiku(
    *steps: Any, ceiling_usd: float = 5.0, config: CommunityConfig = CONFIG
) -> tuple[HaikuBaseline, FakeBedrockRuntime]:
    """A `HaikuBaseline` over a scripted fake runtime (default: always 'consistent / no action')."""
    runtime = FakeBedrockRuntime(
        *(steps or (haiku_reply("consistent_edit", "no_action_suggested"),))
    )

    async def no_sleep(_s: float) -> None:
        return None

    baseline = HaikuBaseline(
        runtime,
        model_id="fake-haiku",
        config=config,
        tracker=SpendTracker(ceiling_usd),
        sleep=no_sleep,
        rng=lambda: 0.5,
    )
    return baseline, runtime


def gold_for(
    ids: list[int], nature: str = "consistent_edit", *, natures: dict[int, str] | None = None
) -> dict[int, GoldLabel]:
    """Version 2 gold rows (all probes 'no') for `ids`."""
    return {
        cs: GoldLabel(
            "heldout",
            cs,
            (natures or {}).get(cs, nature),
            NOT_COLLECTED,
            "adjudicated",
            "claude",
            "t",
            version=2,
            probes=dict.fromkeys(LABELLED_PROBES, "no"),
        )
        for cs in ids
    }


# ------------------------------------------------------------------------------- temp git repo

_GIT_FLAGS = [
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.org",
    "-c",
    "commit.gpgsign=false",
]


def git(repo: Path, *args: str) -> str:
    """Run git in a temp repo; returns stdout and raises if it fails."""
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *_GIT_FLAGS, *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


@dataclass(frozen=True)
class FrozenRepo:
    """A temp git repository whose `evaluation/splits/` was frozen and committed."""

    repo: Path
    paths: EvalPaths
    first_commit: str  # before the freeze (does not contain the split files)
    freeze_commit: str


def make_frozen_repo(tmp_path: Path, heldout_ids: list[int]) -> FrozenRepo:
    """init, commit a README, freeze `heldout_ids` through `write_frozen`, commit the freeze."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("temp\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    first = git(repo, "rev-parse", "HEAD")
    paths = EvalPaths(repo / "evaluation")
    write_frozen(paths, Split(tuple(range(1, 61)), tuple(sorted(heldout_ids)), ()))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "freeze the split")
    return FrozenRepo(repo, paths, first, git(repo, "rev-parse", "HEAD"))


# ------------------------------------------------------------------------- a fake full run

from collections.abc import Sequence  # noqa: E402

from cso.adapters.decider import DeciderClient as _Client  # noqa: E402
from cso.evaluation.haiku_baseline import HaikuBaseline as _Haiku  # noqa: E402
from cso.evaluation.heldout import (  # noqa: E402
    FreezeInfo,
    HeldOutRequest,
    Prepared,
    RunDeps,
    execute_heldout,
)

FAKE_COMMIT = "c" * 40
DATE = "2026-10-20"


def prepared_for(ids: Sequence[int]) -> Prepared:
    """A `Prepared` without git, for tests of the run itself (the guards have their own tests)."""
    info = FreezeInfo(FAKE_COMMIT, "d" * 40, Path("."), "e" * 64)
    return Prepared(info=info, ids=sorted(ids))


async def run_it(
    tmp_path: Path,
    *,
    gold: dict[int, GoldLabel] | None = None,
    labellers: Sequence[str] = (),
    haiku: _Haiku | None = None,
    haiku_reason: str | None = None,
    ablations: bool = False,
    hobson: _Client | None = None,
    bodies: list[dict[str, Any]] | None = None,
    snapshots: Any = None,
    authorize: float | None = None,
) -> tuple[EvalPaths, dict[str, Any]]:
    """Run `execute_heldout` over the eight fixtures with fakes; returns (paths, payload)."""
    snaps = await all_snapshots()
    paths = EvalPaths(tmp_path / "evaluation")
    deps = RunDeps(
        client=decider(bodies=bodies),
        snapshots=snapshots or provider(snaps),
        config=CONFIG,
        hobson_client=hobson,
        haiku=haiku,
        haiku_reason=haiku_reason,
    )
    request = HeldOutRequest(
        released=True,
        confirm_freeze=FAKE_COMMIT,
        ablations=ablations,
        authorize_bedrock_usd=authorize,
    )
    payload = await execute_heldout(
        prepared=prepared_for(list(snaps)),
        paths=paths,
        request=request,
        deps=deps,
        model="strands-decider (cuda)",
        hobson_model="hobson-v21 (cuda)" if hobson is not None else None,
        gold=gold or {},
        labellers=labellers,
        date=DATE,
        progress=lambda _m: None,
    )
    return paths, payload
