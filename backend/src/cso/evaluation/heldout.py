"""The guarded, once-only held-out evaluation.

Nothing here tunes anything. The run uses the default community config, the compact evidence
profile and the shipped instruction wording; there is no threshold, profile or config parameter
to turn. The held-out ids are read only after every guard has passed:

1. `--released` was given;
2. `--confirm-freeze <commit>` names a commit hash that exists in this repository, is an ancestor of
   (or equal to) HEAD, and contains `evaluation/splits/heldout_ids.sha256` with exactly the value
   now in the working tree, and its committed id list hashes to that value (so the freeze is real
   and nothing changed after it);
3. `evaluation/results/heldout-run.json` does not exist (the run happens once).

The marker file is created (exclusively) just before the first system runs, as `in_progress`, and
finalised as `finished` or `failed`. A failed run still blocks a second one: deleting the marker is
a human decision (and should be disclosed), never an automatic retry. Preflight failures (no
Decider, an unreachable server) are detected before the marker is written, so they cost nothing.

Systems that cannot run (no Bedrock authorisation, no hobson server, superseded contracts) are
listed with the reason; nothing is silently skipped.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from cso.adapters.bedrock.types import DraftingError
from cso.adapters.decider import DeciderClient
from cso.domain.config import CommunityConfig
from cso.domain.evidence import render
from cso.evaluation.ablation_text import (
    PARAPHRASE_NAMES,
    WITHOUT_CUES,
    instructions_for,
)
from cso.evaluation.haiku_baseline import (
    HaikuBaseline,
    HaikuBudgetExhausted,
    HaikuDecision,
    is_reassuring,
    rules_floor,
)
from cso.evaluation.heldout_report import DISCLOSURE, render_heldout
from cso.evaluation.labels import GoldLabel
from cso.evaluation.panel_eval import (
    PanelItemRun,
    SnapshotProvider,
    diagnose_panel,
    run_panel_items,
    summarise_panel,
)
from cso.evaluation.panel_report import label_provenance
from cso.evaluation.paths import EvalPaths, write_text_lf
from cso.evaluation.runner import score_system
from cso.evaluation.safety_metrics import (
    HARM_DEFINITION,
    Verdict,
    calls_avoided,
    estimate_cost,
    harm_row,
    paraphrase_agreement,
    verdict_from_run,
)
from cso.evaluation.spike import NATURES
from cso.evaluation.split import HELDOUT, SHA_FILE, SplitError, ids_hash, load_ids
from cso.evaluation.variants import make_variant_decide

MARKER_NAME: Final = "heldout-run.json"
PROFILE: Final = "compact"
_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_GIT_TIMEOUT_S = 30

SUPERSEDED = (
    "superseded by ADR-009: the permutation contract (K=1 vs K=3) is compared on the dev set "
    "only (`cso eval spike --contract permutation`)"
)
DESCRIPTIONS: Final = {
    "rule_baseline_v1": "policy rules R1-R4 mapped to a fixed answer (parsed evidence only)",
    "decider_panel_composed": "product: fact panel composed by the ADR-009 table, rules on",
    "decider_panel_rules_off": "the same panel requests composed with every rule hit removed",
    "decider_advisory_nature": "the model's own four-way nature answer, asked once (advisory)",
    "decider_permutation_k3": "permutation contract of ADR-004 (K=1 and K=3)",
    "haiku_decision": "Bedrock Haiku 4.5 forced-tool decision, temperature 0, no rules",
    "haiku_plus_rules": "Decider-removed application: Haiku decision with the rules as a floor",
    "without_cues": "probe wording without thresholds and examples",
    "paraphrase_1": "probe wording paraphrase 1 (thresholds kept)",
    "paraphrase_2": "probe wording paraphrase 2 (thresholds kept)",
    "paraphrase_3": "probe wording paraphrase 3 (thresholds kept)",
    "hobson_v21": "hobson-v21 checkpoint behind a second server, same wording as the product",
    "coverage_block_last": "renderer with the coverage block last instead of first",
    "k1_vs_k3": "ablation: single option order versus the shuffle-averaged permutation",
}


class RunRefused(Exception):
    """A guard refused the held-out run. The message says which condition failed."""


@dataclass(frozen=True)
class HeldOutRequest:
    """Everything the human chose for the single run. No tuning parameter exists."""

    released: bool = False
    confirm_freeze: str | None = None
    ablations: bool = False
    authorize_bedrock_usd: float | None = None
    hobson_url: str | None = None
    expect_config_version: str | None = None


@dataclass(frozen=True)
class FreezeInfo:
    """The verified freeze: the commit, HEAD at run time and the held-out hash."""

    commit: str
    head: str
    repo_root: Path
    heldout_sha256: str


@dataclass(frozen=True)
class Prepared:
    """Guards passed: the freeze and the (hash-verified) held-out ids."""

    info: FreezeInfo
    ids: list[int]


@dataclass
class RunDeps:
    """What a run talks to. Tests inject fakes; the CLI builds the real ones."""

    client: DeciderClient
    snapshots: SnapshotProvider
    config: CommunityConfig
    hobson_client: DeciderClient | None = None
    haiku: HaikuBaseline | None = None
    haiku_reason: str | None = None  # why Haiku is not run when `haiku` is None
    hobson_reason: str | None = None


# ----------------------------------------------------------------------------- the guards


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(repo), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RunRefused(
            f"git could not be run to verify the freeze ({type(exc).__name__})"
        ) from exc


def marker_path(paths: EvalPaths) -> Path:
    """Where the once-only marker lives."""
    return paths.results_dir / MARKER_NAME


def _toplevel(root: Path) -> Path:
    result = _git(root, "rev-parse", "--show-toplevel")
    if result.returncode != 0 or not result.stdout.strip():
        raise RunRefused(f"{root} is not inside a git repository, so the freeze cannot be verified")
    return Path(result.stdout.strip()).resolve()


def _committed_text(repo: Path, commit: str, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise RunRefused(f"{path} is outside the repository {repo}") from exc
    shown = _git(repo, "show", f"{commit}:{rel}")
    if shown.returncode != 0:
        raise RunRefused(
            f"commit {commit[:8]} does not contain {rel}: that is not the freeze commit"
        )
    return shown.stdout


def confirm_freeze(paths: EvalPaths, sha: str) -> FreezeInfo:
    """Verify `sha` is the real freeze commit; raises `RunRefused` with the failing condition."""
    if not _HASH_RE.match(sha.strip()):
        raise RunRefused("--confirm-freeze needs a commit hash (7 to 40 hex digits), not a name")
    repo = _toplevel(paths.root)
    found = _git(repo, "rev-parse", "--verify", "--quiet", f"{sha.strip()}^{{commit}}")
    if found.returncode != 0:
        raise RunRefused(f"{sha} is not a commit in this repository")
    commit = found.stdout.strip()
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    ancestor = _git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor.returncode == 1:
        raise RunRefused(f"freeze commit {commit[:8]} is not an ancestor of HEAD {head[:8]}")
    if ancestor.returncode != 0:
        raise RunRefused("git could not relate the freeze commit to HEAD")
    sha_file = paths.splits_dir / SHA_FILE
    if not sha_file.exists():
        raise RunRefused(f"{sha_file} is missing: no frozen held-out split")
    committed_hash = _committed_text(repo, commit, sha_file).strip()
    working_hash = sha_file.read_text(encoding="utf-8").strip()
    if committed_hash != working_hash:
        raise RunRefused(
            f"{SHA_FILE} in the working tree differs from the one in commit {commit[:8]}: "
            "the held-out list changed after the freeze"
        )
    ids_text = _committed_text(repo, commit, paths.splits_dir / "heldout_ids.txt")
    committed_ids = [int(line) for line in ids_text.split() if line.strip()]
    if ids_hash(committed_ids) != committed_hash:
        raise RunRefused("the committed held-out id list does not match its committed hash")
    return FreezeInfo(commit=commit, head=head, repo_root=repo, heldout_sha256=committed_hash)


def refuse_if_already_run(paths: EvalPaths) -> None:
    """The held-out run happens once: any marker, even a failed run's, blocks another."""
    marker = marker_path(paths)
    if marker.exists():
        raise RunRefused(
            f"{marker} exists: the held-out evaluation runs once. If you deliberately accept "
            "discarding that run, delete the file by hand and disclose it in the report"
        )


def prepare(
    paths: EvalPaths, request: HeldOutRequest, *, config_version: str | None = None
) -> Prepared:
    """Run every guard, in order, without side effects; returns the verified freeze and ids."""
    if not request.released:
        raise RunRefused(
            "the held-out set is frozen: pass --released after the freeze commit "
            "(and only for the one final evaluation run)"
        )
    if not request.confirm_freeze or not request.confirm_freeze.strip():
        raise RunRefused(
            "--confirm-freeze <commit> is required: name the commit that froze "
            "evaluation/splits/ (`git log -- evaluation/splits`)"
        )
    info = confirm_freeze(paths, request.confirm_freeze)
    refuse_if_already_run(paths)
    expected = request.expect_config_version
    if expected and config_version is not None and not config_version.startswith(expected):
        raise RunRefused(
            f"config version {config_version[:16]} does not match --expect-config-version "
            f"{expected}: refusing to evaluate a config that was not the frozen one"
        )
    try:
        ids = load_ids(paths, HELDOUT, released=True)  # re-verifies the id list against its hash
    except SplitError as exc:
        raise RunRefused(str(exc)) from exc
    return Prepared(info=info, ids=ids)


def _write_marker(paths: EvalPaths, data: Mapping[str, Any]) -> None:
    marker = marker_path(paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8", newline="\n") as handle:  # exclusive create
            handle.write(json.dumps(dict(data), indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise RunRefused(f"{marker} appeared while starting: another run is in progress") from exc


def _update_marker(paths: EvalPaths, **fields: Any) -> None:
    marker = marker_path(paths)
    current = json.loads(marker.read_text(encoding="utf-8"))
    current.update(fields)
    write_text_lf(marker, json.dumps(current, indent=2, sort_keys=True) + "\n")


# ------------------------------------------------------------------------ results assembly


def _truth_pairs(
    answers: Mapping[int, str | None], gold: Mapping[int, GoldLabel]
) -> tuple[list[str], list[str]]:
    ids = [cs for cs in sorted(gold) if not gold[cs].ambiguous and answers.get(cs)]
    return [gold[cs].nature for cs in ids], [str(answers[cs]) for cs in ids]


def _entry(
    name: str,
    answers: Mapping[int, str | None] | None,
    gold: Mapping[int, GoldLabel] | None,
    *,
    n_items: int,
    status: str = "ran",
    reason: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One system's result row: counts always, accuracy only when gold labels exist."""
    entry: dict[str, Any] = {
        "name": name,
        "description": DESCRIPTIONS[name],
        "status": status,
        "reason": reason,
        "n_items": n_items,
        "n_answered": 0,
        "n_errors": 0,
        "nature_counts": {},
        "scored": None,
        "extra": dict(extra or {}),
    }
    if answers is None:
        return entry
    given = [v for v in answers.values() if v]
    entry["n_answered"] = len(given)
    entry["n_errors"] = len(answers) - len(given)
    entry["nature_counts"] = dict(Counter(given))
    if gold:
        truth, pred = _truth_pairs(answers, gold)
        entry["scored"] = asdict(score_system(truth, pred, NATURES))
    return entry


def _pooled(runs: Sequence[PanelItemRun], gold: Mapping[int, GoldLabel]) -> dict[str, Any]:
    """Pooled probe accuracy when decided, for an ablation run (needs gold labels)."""
    return asdict(summarise_panel(runs, dict(gold)).pooled_decided)


def not_run(name: str, reason: str) -> dict[str, Any]:
    """A listed-but-not-run system or ablation."""
    return _entry(name, None, None, n_items=0, status="not run", reason=reason)


def _requested_names(request: HeldOutRequest, deps: RunDeps) -> list[str]:
    names = ["rule_baseline_v1", "decider_panel_composed", "decider_panel_rules_off"]
    names.append("decider_advisory_nature")
    if deps.haiku is not None:
        names += ["haiku_decision", "haiku_plus_rules"]
    if request.ablations:
        names += [WITHOUT_CUES, *PARAPHRASE_NAMES]
    if deps.hobson_client is not None:
        names.append("hobson_v21")
    return names


async def _run_haiku(
    ids: Sequence[int], deps: RunDeps, progress: Any
) -> dict[int, HaikuDecision | str]:
    """One Haiku decision per item from the same compact text; a failure keeps its code."""
    if deps.haiku is None:
        raise RuntimeError("_run_haiku needs a Haiku baseline")
    results: dict[int, HaikuDecision | str] = {}
    exhausted = False
    for n, cs in enumerate(ids, start=1):
        if exhausted:
            results[cs] = HaikuBudgetExhausted.code
            continue
        text = render(await deps.snapshots(cs), deps.config, profile=PROFILE).text
        try:
            results[cs] = await deps.haiku.decide(text)
        except HaikuBudgetExhausted:
            exhausted = True
            results[cs] = HaikuBudgetExhausted.code
        except DraftingError as exc:
            results[cs] = exc.code
        progress(f"[haiku {n}/{len(ids)}] {cs}: {'ok' if cs in results else '?'}")
    return results


def _item_rows(
    runs: Sequence[PanelItemRun],
    haiku: Mapping[int, HaikuDecision | str] | None,
    floor: Mapping[int, tuple[str, str, bool]],
    gold: Mapping[int, GoldLabel] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in runs:
        row: dict[str, Any] = {
            "changeset_id": r.changeset_id,
            "rules_fired": list(r.rules_fired),
            "rules_nature": r.rules_nature,
            "rules_response": r.rules_response,
            "composed_nature": r.composed_nature,
            "composed_response": r.composed_response,
            "composed_lane": r.composed_lane,
            "composed_band": r.composed_band,
            "norules_nature": r.norules_nature,
            "norules_response": r.norules_response,
            "norules_lane": r.norules_lane,
            "advisory_choice": r.advisory_choice,
            "states": r.states,
            "input_tokens": r.input_tokens,
            "latency_ms": r.latency_ms,
            "server_latency_ms": r.server_latency_ms,
            "error": r.error,
        }
        if haiku is not None:
            h = haiku.get(r.changeset_id)
            if isinstance(h, HaikuDecision):
                row.update(
                    haiku_nature=h.nature,
                    haiku_response=h.response,
                    haiku_input_tokens=h.input_tokens,
                    haiku_output_tokens=h.output_tokens,
                )
                if r.changeset_id in floor:
                    fn, fr, overridden = floor[r.changeset_id]
                    row.update(haiku_rules_nature=fn, haiku_rules_response=fr)
                    row["haiku_rules_overridden"] = overridden
            else:
                row["haiku_error"] = h
        if gold is not None and r.changeset_id in gold:
            row["gold_nature"] = gold[r.changeset_id].nature
        rows.append(row)
    return rows


async def run_all(
    *,
    prepared: Prepared,
    paths: EvalPaths,
    request: HeldOutRequest,
    deps: RunDeps,
    model: str,
    hobson_model: str | None,
    gold: Mapping[int, GoldLabel],
    labellers: Sequence[str],
    stem: str,
    date: str,
    progress: Any = print,
) -> dict[str, Any]:
    """Run every requested system once and assemble the results payload (no files written)."""
    ids, config = prepared.ids, deps.config
    receipts = paths.results_dir / "receipts" / stem
    product = await run_panel_items(
        ids,
        deps.snapshots,
        config,
        deps.client,
        profile=PROFILE,
        receipts_dir=receipts / "product",
        progress=progress,
    )
    has_gold = bool(gold)
    g: Mapping[int, GoldLabel] | None = gold if has_gold else None

    haiku: dict[int, HaikuDecision | str] | None = None
    floor: dict[int, tuple[str, str, bool]] = {}
    if deps.haiku is not None:
        haiku = await _run_haiku(ids, deps, progress)
        for r in product:
            h = haiku.get(r.changeset_id)
            if isinstance(h, HaikuDecision):
                floor[r.changeset_id] = rules_floor(
                    r.rules_fired, r.rules_nature, r.rules_response, h.nature, h.response
                )

    variant_runs: dict[str, list[PanelItemRun]] = {}
    if request.ablations:
        for name in (WITHOUT_CUES, *PARAPHRASE_NAMES):
            variant_runs[name] = await run_panel_items(
                ids,
                deps.snapshots,
                config,
                deps.client,
                profile=PROFILE,
                receipts_dir=receipts / name,
                progress=progress,
                decide=make_variant_decide(deps.client, instructions_for(name)),
            )
    if deps.hobson_client is not None:
        variant_runs["hobson_v21"] = await run_panel_items(
            ids,
            deps.snapshots,
            config,
            deps.hobson_client,
            profile=PROFILE,
            receipts_dir=receipts / "hobson_v21",
            progress=progress,
        )

    n = len(ids)
    systems: list[dict[str, Any]] = [
        _entry("rule_baseline_v1", {r.changeset_id: r.rules_nature for r in product}, g, n_items=n),
        _entry(
            "decider_panel_composed",
            {r.changeset_id: r.composed_nature for r in product},
            g,
            n_items=n,
        ),
        _entry(
            "decider_panel_rules_off",
            {r.changeset_id: r.norules_nature for r in product},
            g,
            n_items=n,
        ),
        _entry(
            "decider_advisory_nature",
            {r.changeset_id: r.advisory_choice for r in product},
            g,
            n_items=n,
        ),
        not_run("decider_permutation_k3", SUPERSEDED),
    ]
    if haiku is not None:
        tokens = [
            (h.input_tokens, h.output_tokens)
            for h in haiku.values()
            if isinstance(h, HaikuDecision)
        ]
        systems.append(
            _entry(
                "haiku_decision",
                {
                    cs: (h.nature if isinstance(h, HaikuDecision) else None)
                    for cs, h in haiku.items()
                },
                g,
                n_items=n,
                extra={
                    "attempts": deps.haiku.attempts if deps.haiku else 0,
                    "estimated_usd": round(deps.haiku.tracker.spent_usd, 4) if deps.haiku else 0,
                    "authorised_usd": request.authorize_bedrock_usd,
                    "error_codes": dict(Counter(h for h in haiku.values() if isinstance(h, str))),
                },
            )
        )
        systems.append(
            _entry(
                "haiku_plus_rules",
                {cs: floor[cs][0] if cs in floor else None for cs in haiku},
                g,
                n_items=n,
                extra={"rules_overrode": sum(1 for v in floor.values() if v[2])},
            )
        )
    else:
        reason = deps.haiku_reason or "not requested"
        systems.append(not_run("haiku_decision", reason))
        systems.append(not_run("haiku_plus_rules", f"needs the Haiku decision: {reason}"))
        tokens = []

    ablations: list[dict[str, Any]] = []
    reference = {r.changeset_id: r.composed_nature for r in product}
    for name in (WITHOUT_CUES, *PARAPHRASE_NAMES):
        if name in variant_runs:
            runs = variant_runs[name]
            answers = {r.changeset_id: r.composed_nature for r in runs}
            extra: dict[str, Any] = {
                "same_nature_as_product": sum(
                    1 for cs, v in answers.items() if v and v == reference.get(cs)
                ),
            }
            if has_gold:
                extra["pooled_probe_accuracy"] = _pooled(runs, gold)
            ablations.append(_entry(name, answers, g, n_items=n, extra=extra))
        else:
            ablations.append(not_run(name, "not requested (pass --ablations)"))
    if "hobson_v21" in variant_runs:
        runs = variant_runs["hobson_v21"]
        extra = {"model": hobson_model}
        if has_gold:
            extra["pooled_probe_accuracy"] = _pooled(runs, gold)
        ablations.append(
            _entry(
                "hobson_v21",
                {r.changeset_id: r.composed_nature for r in runs},
                g,
                n_items=n,
                extra=extra,
            )
        )
    else:
        ablations.append(
            not_run(
                "hobson_v21", deps.hobson_reason or "no hobson-v21 server URL given (--hobson-url)"
            )
        )
    ablations.append(
        not_run("coverage_block_last", "no renderer variant with the coverage block last exists")
    )
    ablations.append(not_run("k1_vs_k3", SUPERSEDED))

    # harmful recommendations, rules on and off
    rule_verdicts = [
        Verdict(r.changeset_id, True, r.rules_response == "no_action_suggested", r.rules_fired)
        for r in product
    ]
    harm = [
        harm_row(
            "decider_panel_composed", "on", [verdict_from_run(r, rules_on=True) for r in product], g
        ),
        harm_row(
            "decider_panel_rules_off",
            "off",
            [verdict_from_run(r, rules_on=False) for r in product],
            g,
        ),
        harm_row(
            "decider_advisory_nature",
            "off",
            [verdict_from_run(r, rules_on=False, field="advisory") for r in product],
            g,
        ),
        harm_row("rule_baseline_v1", "rules only", rule_verdicts, g),
    ]
    if haiku is not None:
        by_id = {r.changeset_id: r for r in product}
        haiku_alone: list[Verdict] = []
        haiku_rules: list[Verdict] = []
        for cs, h in haiku.items():
            fired = by_id[cs].rules_fired if cs in by_id else ()
            if isinstance(h, HaikuDecision):
                haiku_alone.append(Verdict(cs, True, is_reassuring(h.nature, h.response), fired))
                fn, fr, _ = floor[cs]
                haiku_rules.append(Verdict(cs, True, is_reassuring(fn, fr), fired))
            else:
                haiku_alone.append(Verdict(cs, False, False, fired))
                haiku_rules.append(Verdict(cs, False, False, fired))
        harm.append(harm_row("haiku_decision", "off", haiku_alone, g))
        harm.append(harm_row("haiku_plus_rules", "on", haiku_rules, g))

    summary = summarise_panel(product, dict(gold)) if has_gold else None
    agreement = paraphrase_agreement({"product": product, **variant_runs}) if variant_runs else []
    provenance = (
        label_provenance(labellers, [g_.adjudicator for g_ in gold.values() if g_.adjudicator])
        if has_gold
        else None
    )
    return {
        "kind": "heldout",
        "date": date,
        "stem": stem,
        "freeze_commit": prepared.info.commit,
        "head_commit": prepared.info.head,
        "heldout_sha256": prepared.info.heldout_sha256,
        "config_version": config.version,
        "profile": PROFILE,
        "model": model,
        "n_items": n,
        "labels": {
            "mode": "scored" if has_gold else "label_free",
            "gold_items": len(gold),
            "provenance": provenance,
        },
        "systems": systems,
        "ablations": ablations,
        "panel_summary": asdict(summary) if summary is not None else None,
        "diagnostic": asdict(diagnose_panel(product, config)),
        "harm": {"definition": HARM_DEFINITION, "rows": [asdict(h) for h in harm]},
        "cost": asdict(estimate_cost(product, tokens)),
        "calls_avoided": asdict(calls_avoided(product)),
        "paraphrase_agreement": [asdict(a) for a in agreement],
        "disclosure": DISCLOSURE,
        "items": _item_rows(product, haiku, floor, g),
    }


# ------------------------------------------------------------------------------- the run


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def execute_heldout(
    *,
    prepared: Prepared,
    paths: EvalPaths,
    request: HeldOutRequest,
    deps: RunDeps,
    model: str,
    hobson_model: str | None,
    gold: Mapping[int, GoldLabel],
    labellers: Sequence[str],
    date: str,
    progress: Any = print,
) -> dict[str, Any]:
    """Write the in-progress marker, run every system once, write results and finalise the marker.

    Call only after `prepare` and after the preflight checks (the Decider answers `/health`), so
    that anything that can fail cheaply has already failed.
    """
    stem = f"{date}-heldout-{prepared.info.commit[:8]}"
    _write_marker(
        paths,
        {
            "status": "in_progress",
            "started": _utc_now(),
            "freeze_commit": prepared.info.commit,
            "head_commit": prepared.info.head,
            "heldout_sha256": prepared.info.heldout_sha256,
            "config_version": deps.config.version,
            "systems_requested": _requested_names(request, deps),
            "ablations_requested": request.ablations,
            "bedrock_authorised_usd": request.authorize_bedrock_usd,
            "results": stem,
        },
    )
    try:
        payload = await run_all(
            prepared=prepared,
            paths=paths,
            request=request,
            deps=deps,
            model=model,
            hobson_model=hobson_model,
            gold=gold,
            labellers=labellers,
            stem=stem,
            date=date,
            progress=progress,
        )
        write_text_lf(
            paths.results_dir / f"{stem}.json", json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
        write_text_lf(paths.results_dir / f"{stem}.md", render_heldout(payload))
    except BaseException as exc:
        _update_marker(paths, status="failed", finished=_utc_now(), error=type(exc).__name__)
        raise
    _update_marker(paths, status="finished", finished=_utc_now())
    return payload


__all__ = [
    "DESCRIPTIONS",
    "MARKER_NAME",
    "FreezeInfo",
    "HeldOutRequest",
    "Prepared",
    "RunDeps",
    "RunRefused",
    "confirm_freeze",
    "execute_heldout",
    "marker_path",
    "not_run",
    "prepare",
    "refuse_if_already_run",
    "run_all",
]
