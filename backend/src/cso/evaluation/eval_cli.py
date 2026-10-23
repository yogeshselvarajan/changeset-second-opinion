"""`cso eval ...` subcommands: candidates, label, adjudicate, split, spike, run, report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio

from cso.adapters.decider import GPU_TIMEOUT_S, DeciderClient, DeciderError
from cso.adapters.osm import MapRouletteClient, OsmClient, ReplayClient, collect
from cso.adapters.osm.errors import OsmError
from cso.domain.config import CommunityConfig
from cso.domain.fixtures import load_case
from cso.domain.models import EvidenceSnapshot
from cso.evaluation import candidates as candidates_mod
from cso.evaluation.ablate_model import (
    ModelRun,
    compare_models,
    load_run_file,
    render_ablation,
    render_chart,
)
from cso.evaluation.backfill import backfill, render_report
from cso.evaluation.candidates_io import Candidate
from cso.evaluation.combined_report import render_combined
from cso.evaluation.haiku_baseline import build_haiku_baseline
from cso.evaluation.heldout import (
    HeldOutRequest,
    RunDeps,
    RunRefused,
    execute_heldout,
    prepare,
)
from cso.evaluation.label_cli import (
    adjudication_prompt,
    adjudication_prompt_probes,
    label_panel_session,
    label_session,
)
from cso.evaluation.labels import (
    LABELLED_PROBES,
    NOT_COLLECTED,
    GoldLabel,
    LabelError,
    LabelStore,
    adjudicate,
    load_gold,
    write_gold,
)
from cso.evaluation.panel_compare import compare as compare_probe
from cso.evaluation.panel_compare import render_section
from cso.evaluation.panel_eval import (
    PanelItemRun,
    diagnose_panel,
    evaluate_panel_gate,
    run_panel_items,
    summarise_panel,
)
from cso.evaluation.panel_report import (
    label_provenance,
    render_diagnostic,
    render_panel_run,
    render_panel_spike,
)
from cso.evaluation.paths import EvalPaths, read_jsonl, write_text_lf
from cso.evaluation.report import SMOKE_BANNER, render_not_run, render_run, render_spike
from cso.evaluation.runner import ItemRun, run_items
from cso.evaluation.snapshots import SnapshotCache, snapshot_for
from cso.evaluation.spike import (
    REQUIRED_LABELS,
    Summary,
    evaluate_gate,
    not_run_line,
    summarise,
)
from cso.evaluation.split import (
    DEV,
    HELDOUT,
    SplitError,
    build_split,
    check_disjoint,
    ids_hash,
    load_ids,
    splits_exist,
    write_frozen,
)
from cso.settings import SettingsError, get_settings

FIXTURE_CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _fail(message: str) -> int:
    print(f"cso eval: {message}", file=sys.stderr)
    return 1


def _config() -> CommunityConfig:
    return CommunityConfig.load()


def _cache_lookup(paths: EvalPaths) -> Callable[[int], EvidenceSnapshot]:
    cache = SnapshotCache(paths.snapshot_cache)

    def lookup(cs: int) -> EvidenceSnapshot:
        snapshot = cache.get(cs)
        if snapshot is None:
            raise LookupError(f"no cached evidence for changeset {cs}; run `cso eval candidates`")
        return snapshot

    return lookup


def _load_candidates(paths: EvalPaths) -> list[Candidate]:
    return [Candidate.from_json(r) for r in read_jsonl(paths.candidates)]


# --- candidates -----------------------------------------------------------------------------


def _cmd_candidates(args: argparse.Namespace) -> int:
    paths = EvalPaths.default()
    if splits_exist(paths.root):
        return _fail("a frozen split exists; candidates are not regenerated after the freeze")
    settings = get_settings()

    async def run() -> candidates_mod.GatherReport:
        osm = OsmClient.from_settings(settings)
        roulette = MapRouletteClient(user_agent=settings.user_agent)
        try:
            return await candidates_mod.gather(
                osm,
                roulette,
                SnapshotCache(paths.snapshot_cache),
                limit=args.limit,
                max_minutes=args.max_minutes,
                progress=print,
            )
        finally:
            await osm.aclose()
            await roulette.aclose()

    report = anyio.run(run)
    existing = {c.changeset_id: c for c in _load_candidates(paths)}
    for cand in report.candidates:
        existing.setdefault(cand.changeset_id, cand)
    merged = sorted(existing.values(), key=lambda c: c.changeset_id)
    write_text_lf(
        paths.candidates,
        "".join(json.dumps(c.to_json(), sort_keys=True) + "\n" for c in merged),
    )
    print(
        f"maproulette: {report.maproulette_tasks} tasks listed, "
        f"{report.maproulette_collected} collected | recent changesets scanned: "
        f"{report.recent_scanned}, new accounts: {report.recent_new_accounts}, "
        f"collected: {report.recent_collected} | candidates written: {len(merged)}"
        + (" | STOPPED EARLY (time limit)" if report.stopped_early else "")
    )
    if report.errors:
        print(f"errors: {report.errors}")
    return 0


# --- split ----------------------------------------------------------------------------------


def _cmd_split(args: argparse.Namespace) -> int:
    paths = EvalPaths.default()
    candidates = _load_candidates(paths)
    if not candidates:
        return _fail(f"{paths.candidates} is empty; run `cso eval candidates` first")
    split = build_split(candidates, args.dev, args.heldout)
    check_disjoint(split, candidates)
    if args.dry_run:
        print(
            f"dry run (nothing written): dev={len(split.dev)} heldout={len(split.heldout)} "
            f"reserve={len(split.reserve)} heldout_sha256={ids_hash(split.heldout)}"
        )
        if len(split.dev) < args.dev or len(split.heldout) < args.heldout:
            print("warning: fewer candidates than requested; collect more first", file=sys.stderr)
        return 0
    try:
        digest = write_frozen(paths, split)
    except SplitError as exc:
        return _fail(str(exc))
    print(
        f"dev={len(split.dev)} heldout={len(split.heldout)} reserve={len(split.reserve)} "
        f"heldout_sha256={digest}"
    )
    if len(split.dev) < args.dev or len(split.heldout) < args.heldout:
        print("warning: fewer candidates than requested; sizes are below target", file=sys.stderr)
    print("Commit evaluation/splits/ now: that commit is the freeze.")
    return 0


# --- label / adjudicate ---------------------------------------------------------------------


def _cmd_label(args: argparse.Namespace) -> int:
    paths = EvalPaths.default()
    try:
        # Labelling shows evidence only and runs no system, so held-out ids may be labelled.
        ids = load_ids(paths, args.set, released=True)
    except SplitError as exc:
        return _fail(str(exc))
    store = LabelStore(paths.labels(args.set), args.set)
    session_fn = label_session if args.legacy else label_panel_session
    try:
        session_fn(
            store=store,
            ids=ids,
            snapshots=_cache_lookup(paths),
            config=_config(),
            labeller=args.labeller,
            session=args.session,
            limit=args.limit,
        )
    except (LookupError, LabelError) as exc:
        return _fail(str(exc))
    return 0


def _parse_session(raw: str) -> tuple[str, str]:
    labeller, _, session = raw.partition(":")
    if not labeller or not session:
        raise argparse.ArgumentTypeError("expected LABELLER:SESSION")
    return labeller, session


def _cmd_adjudicate(args: argparse.Namespace) -> int:
    paths = EvalPaths.default()
    store = LabelStore(paths.labels(args.set), args.set)
    try:
        gold, agreement = adjudicate(
            store,
            session_a=args.a,
            session_b=args.b,
            decide=adjudication_prompt(snapshots=_cache_lookup(paths), config=_config()),
            decide_probes=adjudication_prompt_probes(
                snapshots=_cache_lookup(paths), config=_config()
            ),
            adjudicator=args.adjudicator,
        )
    except (LookupError, LabelError) as exc:
        return _fail(str(exc))
    write_gold(paths.adjudicated(args.set), gold)
    kappa_n = "n/a" if agreement.nature_kappa is None else f"{agreement.nature_kappa:.2f}"
    kappa_r = "n/a" if agreement.response_kappa is None else f"{agreement.response_kappa:.2f}"
    ambiguous = sum(1 for g in gold if g.ambiguous)
    if agreement.probe_items:
        worst = min(agreement.probe_agree.items(), key=lambda kv: kv[1])
        print(
            f"probe agreement over {agreement.probe_items} items: lowest "
            f"{worst[0]} {worst[1]}/{agreement.probe_items}"
        )
    print(
        f"adjudicated {len(gold)} items | nature agreement {agreement.nature_agree}/"
        f"{agreement.items} (kappa {kappa_n}) | response agreement "
        f"{agreement.response_agree}/{agreement.items} (kappa {kappa_r}) | ambiguous: {ambiguous}"
    )
    return 0


# --- run / spike ----------------------------------------------------------------------------


def _fixture_gold() -> dict[int, GoldLabel]:
    """Hint labels from fixtures' expected.json. Synthetic: for the pipeline smoke test only."""
    gold: dict[int, GoldLabel] = {}
    stamp = _today()
    for case_dir in sorted(FIXTURE_CASES.iterdir()):
        case = load_case(case_dir)
        expected = case.expected
        if expected.nature is None or expected.response is None:
            continue
        gold[expected.changeset_id] = GoldLabel(
            "fixtures",
            expected.changeset_id,
            expected.nature.value,
            expected.response.value,
            "synthetic_hint",
            None,
            stamp,
        )
    return gold


def _run_json(
    *, set_name: str, config: CommunityConfig, model: str, runs: list[ItemRun], summary: Summary
) -> str:
    payload: dict[str, Any] = {
        "date": _today(),
        "set": set_name,
        "config_version": config.version,
        "model": model,
        "items": [asdict(r) for r in runs],
        "summary": asdict(summary),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


async def _decider_runs(
    *, ids: list[int], snapshots: Any, config: CommunityConfig, receipts: Path
) -> tuple[list[ItemRun], str]:
    client = DeciderClient.from_settings(get_settings())
    try:
        identity = await client.health()
        runs = await run_items(
            ids, snapshots, config, client, receipts_dir=receipts, progress=print
        )
    finally:
        await client.aclose()
    return runs, f"{identity.model} ({identity.device})"


def _need_decider() -> str | None:
    if not get_settings().decider_url:
        return "CSO_DECIDER_URL is not set (e.g. http://127.0.0.1:8099 through the SSM tunnel)"
    return None


def _cmd_run(args: argparse.Namespace) -> int:
    if args.set == HELDOUT:  # every guard runs before anything else, even the Decider check
        return _run_heldout(args)
    if args.contract == "panel":
        return _run_panel(args)
    paths = EvalPaths.default()
    config = _config()
    problem = _need_decider()
    if problem:
        return _fail(problem)
    date = _today()
    try:
        if args.set == "fixtures":
            gold = _fixture_gold()
            ids = sorted(gold)

            async def fixture_snapshot(cs: int) -> EvidenceSnapshot:
                for case_dir in FIXTURE_CASES.iterdir():
                    if load_case(case_dir).expected.changeset_id == cs:
                        return await collect(ReplayClient(case_dir), cs)
                raise LookupError(cs)

            snapshots: Any = fixture_snapshot
            title, banner = "Pipeline smoke test", SMOKE_BANNER
            stem = f"smoke-{date}"
        else:
            ids = load_ids(paths, args.set, released=args.released)
            gold = load_gold(paths.adjudicated(args.set))
            missing = [i for i in ids if i not in gold]
            if missing:
                return _fail(f"{len(missing)} {args.set} items have no adjudicated label yet")
            cache = SnapshotCache(paths.snapshot_cache)

            async def cached_snapshot(cs: int) -> EvidenceSnapshot:
                return await snapshot_for(None, cs, cache)

            snapshots = cached_snapshot
            title, banner = f"Run on the {args.set} set", None
            stem = f"{date}-{args.set}-{config.version[:8]}"
        receipts = paths.results_dir / "receipts" / stem
        runs, model = anyio.run(
            partial(_decider_runs, ids=ids, snapshots=snapshots, config=config, receipts=receipts)
        )
    except (SplitError, LookupError, DeciderError, OsmError) as exc:
        return _fail(str(exc))
    summary = summarise(runs, gold, order_sensitivity_cap=config.bands.order_sensitivity_max)
    write_text_lf(
        paths.results_dir / f"{stem}.md",
        render_run(
            summary,
            title=title,
            banner=banner,
            date=date,
            config_version=config.version,
            model=model,
        ),
    )
    write_text_lf(
        paths.results_dir / f"{stem}.json",
        _run_json(set_name=args.set, config=config, model=model, runs=runs, summary=summary),
    )
    print(f"wrote {paths.results_dir / (stem + '.md')} ({summary.n_scored} scored items)")
    return 0


def _cmd_spike(args: argparse.Namespace) -> int:
    if args.contract == "panel":
        return _spike_panel()
    paths = EvalPaths.default()
    config = _config()
    date = _today()
    report_path = paths.results_dir / f"spike-{date}.md"
    try:
        ids = load_ids(paths, DEV)
    except SplitError:
        ids = []  # no split yet means no labelled dev items
    gold = load_gold(paths.adjudicated(DEV))
    labelled = [i for i in ids if i in gold]
    if len(labelled) < REQUIRED_LABELS:
        line = not_run_line(len(labelled))
        print(line)
        if not (report_path.exists() and "VERDICT:" in report_path.read_text(encoding="utf-8")):
            write_text_lf(report_path, render_not_run(len(labelled), date=date))
        return 0
    problem = _need_decider()
    if problem:
        return _fail(problem)
    cache = SnapshotCache(paths.snapshot_cache)

    async def cached_snapshot(cs: int) -> EvidenceSnapshot:
        return await snapshot_for(None, cs, cache)

    try:
        runs, model = anyio.run(
            partial(
                _decider_runs,
                ids=labelled,
                snapshots=cached_snapshot,
                config=config,
                receipts=paths.results_dir / "receipts" / f"spike-{date}",
            )
        )
    except (LookupError, DeciderError) as exc:
        return _fail(str(exc))
    summary = summarise(runs, gold, order_sensitivity_cap=config.bands.order_sensitivity_max)
    gate = evaluate_gate(summary)
    write_text_lf(
        report_path,
        render_spike(summary, gate, date=date, config_version=config.version, model=model),
    )
    write_text_lf(
        paths.results_dir / f"spike-{date}.json",
        _run_json(set_name=DEV, config=config, model=model, runs=runs, summary=summary),
    )
    print(f"wrote {report_path}")
    print(
        next(
            line
            for line in report_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("VERDICT:")
        )
    )
    return 0


# --- fact-panel contract (ADR-009) -----------------------------------------------------------


def _panel_json(
    *,
    set_name: str,
    config: CommunityConfig,
    model: str,
    profile: str,
    runs: list[PanelItemRun],
    includes_heldout: bool = False,
) -> str:
    payload: dict[str, Any] = {
        "date": _today(),
        "set": set_name,
        "includes_heldout": includes_heldout,
        "config_version": config.version,
        "model": model,
        "profile": profile,
        "items": [asdict(r) for r in runs],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


async def _panel_runs(
    *,
    ids: list[int],
    snapshots: Any,
    config: CommunityConfig,
    receipts: Path,
    profile: Any,
) -> tuple[list[PanelItemRun], str]:
    client = DeciderClient.from_settings(get_settings())
    try:
        identity = await client.health()
        runs = await run_panel_items(
            ids,
            snapshots,
            config,
            client,
            profile=profile,
            receipts_dir=receipts,
            progress=print,
        )
    finally:
        await client.aclose()
    return runs, f"{identity.model} ({identity.device})"


def _cached_snapshots(paths: EvalPaths) -> Any:
    cache = SnapshotCache(paths.snapshot_cache)

    async def cached_snapshot(cs: int) -> EvidenceSnapshot:
        return await snapshot_for(None, cs, cache)

    return cached_snapshot


HELDOUT_DIAGNOSTIC_NOTE = (
    "HELD-OUT IDS INCLUDED (explicit --include-heldout): this run sent the held-out items through "
    "the Decider and committed the per-item answers. It read no labels and tuned nothing, but it "
    "means the held-out items are no longer unseen by the model, and a person must record that "
    "wherever held-out results are reported."
)


def diagnostic_heldout_problem(set_name: str, include_heldout: bool, *, frozen: bool) -> str | None:
    """Why a panel-diagnostic run must be refused, or None.

    `--set heldout` always touches the held-out ids; `--set all` does once the split is frozen.
    Unlike `eval run --set heldout`, this command needs no freeze commit, no `--released` and leaves
    no once-only marker, so the explicit flag is the only guard: it makes the decision visible.
    """
    touches = set_name == HELDOUT or (set_name == "all" and frozen)
    if touches and not include_heldout:
        return (
            f"--set {set_name} would send the held-out ids through the Decider "
            "(they would stop being unseen). Use --set dev, or pass --include-heldout to do it "
            "on purpose; the report then says so."
        )
    return None


def _cmd_panel_diagnostic(args: argparse.Namespace) -> int:
    """Run the panel over candidate items without labels; writes a report that is not a verdict."""
    include_heldout = bool(getattr(args, "include_heldout", False))
    refusal = diagnostic_heldout_problem(
        args.set, include_heldout, frozen=splits_exist(EvalPaths.default().root)
    )
    if refusal:
        return _fail(refusal)
    try:
        get_settings().require_real_user_agent()
    except SettingsError as exc:
        return _fail(str(exc))
    problem = _need_decider()
    if problem:
        return _fail(problem)
    paths = EvalPaths.default()
    config = _config()
    try:
        if args.set == "all":
            ids = sorted(c.changeset_id for c in _load_candidates(paths))
        else:  # label-free statistics only, so the frozen held-out ids may be read
            ids = load_ids(paths, args.set, released=True)
    except SplitError as exc:
        return _fail(str(exc))
    if not ids:
        return _fail(f"no items for set {args.set!r}; run `cso eval candidates` first")
    split_status = (
        "frozen (dev and held-out files exist)"
        if splits_exist(paths.root)
        else "not frozen yet; all candidate items are used"
    )
    touches_heldout = args.set == HELDOUT or (args.set == "all" and splits_exist(paths.root))
    if touches_heldout:
        split_status = f"{split_status}. {HELDOUT_DIAGNOSTIC_NOTE}"
    date = _today()
    stem = f"panel-diagnostic-{date}{getattr(args, 'tag', '')}"
    try:
        runs, model = anyio.run(
            partial(
                _panel_runs,
                ids=ids,
                snapshots=_cached_snapshots(paths),
                config=config,
                receipts=paths.results_dir / "receipts" / stem,
                profile=args.profile,
            )
        )
    except (LookupError, DeciderError, OsmError) as exc:
        return _fail(str(exc))
    diag = diagnose_panel(runs, config)
    write_text_lf(
        paths.results_dir / f"{stem}.md",
        render_diagnostic(
            diag,
            date=date,
            config_version=config.version,
            model=model,
            profile=args.profile,
            split_status=split_status,
        ),
    )
    write_text_lf(
        paths.results_dir / f"{stem}.json",
        _panel_json(
            set_name=args.set,
            config=config,
            model=model,
            profile=args.profile,
            runs=runs,
            includes_heldout=touches_heldout,
        ),
    )
    compare_with = getattr(args, "compare_with", None)
    if compare_with:
        before_dir = paths.results_dir / "receipts" / compare_with
        if not before_dir.is_dir():
            return _fail(f"--compare-with: no receipts at {before_dir}")
        section = render_section(compare_probe(before_dir, paths.results_dir / "receipts" / stem))
        report_path = paths.results_dir / f"{stem}.md"
        body = report_path.read_text(encoding="utf-8").rstrip()
        write_text_lf(report_path, body + "\n" + section)
    print(
        f"wrote {paths.results_dir / (stem + '.md')} "
        f"({diag.n_answered}/{diag.n_items} answered, {diag.n_failures} failures)"
    )
    return 0


LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
LABEL_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,40}")
ABLATION_TIMEOUT_S = 180.0  # a larger checkpoint on a shared GPU can be slow; fail rather than wait


def ablation_problem(label: str, url: str) -> str | None:
    """Why `ablate-model` must refuse these arguments, or None.

    The second server must be on this machine (invariant 7: Decider servers bind loopback only;
    reach a remote host through an SSM port forward), and the label becomes part of a file name.
    """
    if not LABEL_PATTERN.fullmatch(label):
        return "--label may hold letters, digits, dot, dash and underscore only (at most 40)"
    host = urlsplit(url).hostname or ""
    if urlsplit(url).scheme not in ("http", "https") or host not in LOOPBACK:
        return (
            "--decider-url must point at this machine (127.0.0.1, localhost or ::1); "
            "forward the port with `aws ssm start-session` instead of exposing the server"
        )
    return None


async def _ablation_runs(
    *,
    url: str,
    ids: list[int],
    snapshots: Any,
    config: CommunityConfig,
    receipts: Path,
) -> tuple[list[PanelItemRun], str]:
    client = DeciderClient(url, timeout_s=ABLATION_TIMEOUT_S)
    try:
        identity = await client.health()
        runs = await run_panel_items(
            ids, snapshots, config, client, profile="compact", receipts_dir=receipts, progress=print
        )
    finally:
        await client.aclose()
    return runs, f"{identity.model} ({identity.device})"


def _cmd_ablate_model(args: argparse.Namespace) -> int:
    """Ask a second Decider server the identical panel questions; write the side-by-side report."""
    refusal = ablation_problem(args.label, args.decider_url)
    if refusal:
        return _fail(refusal)
    try:
        get_settings().require_real_user_agent()
    except SettingsError as exc:
        return _fail(str(exc))
    paths = EvalPaths.default()
    config = _config()
    try:
        ids = load_ids(paths, DEV)
    except SplitError as exc:
        return _fail(str(exc))
    if not ids:
        return _fail("no dev items; run `cso eval candidates` and `cso eval split` first")
    date = _today()
    stem = f"ablation-model-{args.label}-{date}"
    snapshots = _cached_snapshots(paths)
    try:
        if args.baseline_json:
            base_model, _version, base_runs = load_run_file(Path(args.baseline_json))
        else:
            problem = _need_decider()
            if problem:
                return _fail(problem)
            base_runs, base_model = anyio.run(
                partial(
                    _panel_runs,
                    ids=ids,
                    snapshots=snapshots,
                    config=config,
                    receipts=paths.results_dir / "receipts" / f"ablation-model-base-{date}",
                    profile="compact",
                )
            )
        other_runs, other_model = anyio.run(
            partial(
                _ablation_runs,
                url=args.decider_url,
                ids=ids,
                snapshots=snapshots,
                config=config,
                receipts=paths.results_dir / "receipts" / stem,
            )
        )
    except (LookupError, DeciderError, OSError, KeyError, ValueError) as exc:
        return _fail(f"{type(exc).__name__}: {exc}")
    gold = load_gold(paths.adjudicated(DEV))
    provenance = (
        label_provenance(
            (row.labeller for row in LabelStore(paths.labels(DEV), DEV).rows()),
            (g.adjudicator for g in gold.values() if g.adjudicator),
        )
        if gold
        else "LABELS: NONE. No adjudicated labels cover these items; only label-free columns "
        "are filled."
    )
    result = compare_models(
        ModelRun(args.baseline_label, base_model, tuple(base_runs)),
        ModelRun(args.label, other_model, tuple(other_runs)),
        gold,
    )
    write_text_lf(paths.results_dir / f"{stem}.svg", render_chart(result))
    write_text_lf(
        paths.results_dir / f"{stem}.md",
        render_ablation(
            result,
            date=date,
            config_version=config.version,
            provenance=provenance,
            chart_name=f"{stem}.svg",
        ),
    )
    write_text_lf(
        paths.results_dir / f"{stem}.json",
        _panel_json(
            set_name=DEV, config=config, model=other_model, profile="compact", runs=other_runs
        ),
    )
    print(f"wrote {paths.results_dir / (stem + '.md')} ({result.n_items} items)")
    return 0


def _cmd_backfill_counts(_args: argparse.Namespace) -> int:
    """Patch cached snapshots with the edit-time changeset count (one read-only GET each)."""
    settings = get_settings()
    try:
        settings.require_real_user_agent()
    except SettingsError as exc:
        return _fail(str(exc))
    paths = EvalPaths.default()
    cache = SnapshotCache(paths.snapshot_cache)

    async def run() -> Any:
        osm = OsmClient.from_settings(settings)
        try:
            return await backfill(osm, cache, progress=print)
        finally:
            await osm.aclose()

    report = anyio.run(run)
    date = _today()
    out = paths.results_dir / f"backfill-counts-{date}.md"
    write_text_lf(out, render_report(report, date=date))
    print(
        f"backfill: {report.total} cached, {report.with_tag} with tag, "
        f"{report.without_tag} without, {report.failed} failed, "
        f"{report.already_done} already done"
    )
    return 0 if report.failed == 0 else 1


def _spike_panel() -> int:
    paths = EvalPaths.default()
    config = _config()
    date = _today()
    report_path = paths.results_dir / f"spike-{date}.md"
    try:
        ids = load_ids(paths, DEV)
    except SplitError:
        ids = []  # no split yet means no labelled dev items
    gold = load_gold(paths.adjudicated(DEV))
    labelled = [i for i in ids if i in gold and gold[i].version >= 2]
    if len(labelled) < REQUIRED_LABELS:
        line = not_run_line(len(labelled))
        print(line)
        if not (report_path.exists() and "VERDICT:" in report_path.read_text(encoding="utf-8")):
            write_text_lf(report_path, render_not_run(len(labelled), date=date))
        return 0
    problem = _need_decider()
    if problem:
        return _fail(problem)
    try:
        runs, model = anyio.run(
            partial(
                _panel_runs,
                ids=labelled,
                snapshots=_cached_snapshots(paths),
                config=config,
                receipts=paths.results_dir / "receipts" / f"spike-{date}",
                profile="compact",
            )
        )
    except (LookupError, DeciderError) as exc:
        return _fail(str(exc))
    summary = summarise_panel(runs, gold)
    gate = evaluate_panel_gate(summary)
    provenance = label_provenance(
        (row.labeller for row in LabelStore(paths.labels(DEV), DEV).rows()),
        (g.adjudicator for g in gold.values() if g.adjudicator),
    )
    write_text_lf(
        report_path,
        render_panel_spike(
            summary,
            gate,
            date=date,
            config_version=config.version,
            model=model,
            provenance=provenance,
        ),
    )
    write_text_lf(
        paths.results_dir / f"spike-{date}.json",
        _panel_json(set_name=DEV, config=config, model=model, profile="compact", runs=runs),
    )
    print(f"wrote {report_path}")
    print(
        next(
            line
            for line in report_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("VERDICT:")
        )
    )
    return 0


def _fixture_panel_gold() -> dict[int, GoldLabel]:
    """Synthetic nature hints as version 2 rows with all probes unknown (smoke test only)."""
    gold: dict[int, GoldLabel] = {}
    stamp = _today()
    for case_dir in sorted(FIXTURE_CASES.iterdir()):
        expected = load_case(case_dir).expected
        if expected.nature is None:
            continue
        gold[expected.changeset_id] = GoldLabel(
            "fixtures",
            expected.changeset_id,
            expected.nature.value,
            NOT_COLLECTED,
            "synthetic_hint",
            None,
            stamp,
            version=2,
            probes=dict.fromkeys(LABELLED_PROBES, "unknown"),
        )
    return gold


def _run_panel(args: argparse.Namespace) -> int:
    paths = EvalPaths.default()
    config = _config()
    problem = _need_decider()
    if problem:
        return _fail(problem)
    date = _today()
    try:
        if args.set == "fixtures":
            gold = _fixture_panel_gold()
            ids = sorted(gold)

            async def fixture_snapshot(cs: int) -> EvidenceSnapshot:
                for case_dir in FIXTURE_CASES.iterdir():
                    if load_case(case_dir).expected.changeset_id == cs:
                        return await collect(ReplayClient(case_dir), cs)
                raise LookupError(cs)

            snapshots: Any = fixture_snapshot
            title, banner = "Pipeline smoke test, fact panel", SMOKE_BANNER
            stem = f"smoke-panel-{date}"
        else:
            ids = load_ids(paths, args.set, released=args.released)
            gold = load_gold(paths.adjudicated(args.set))
            missing = [i for i in ids if i not in gold or gold[i].version < 2]
            if missing:
                return _fail(f"{len(missing)} {args.set} items have no adjudicated panel label yet")
            snapshots = _cached_snapshots(paths)
            title, banner = f"Panel run on the {args.set} set", None
            stem = f"{date}-{args.set}-panel-{config.version[:8]}"
        runs, model = anyio.run(
            partial(
                _panel_runs,
                ids=ids,
                snapshots=snapshots,
                config=config,
                receipts=paths.results_dir / "receipts" / stem,
                profile="compact",
            )
        )
    except (SplitError, LookupError, DeciderError, OsmError) as exc:
        return _fail(str(exc))
    summary = summarise_panel(runs, gold)
    write_text_lf(
        paths.results_dir / f"{stem}.md",
        render_panel_run(
            summary,
            title=title,
            banner=banner,
            date=date,
            config_version=config.version,
            model=model,
            synthetic=args.set == "fixtures",
        ),
    )
    write_text_lf(
        paths.results_dir / f"{stem}.json",
        _panel_json(set_name=args.set, config=config, model=model, profile="compact", runs=runs),
    )
    print(f"wrote {paths.results_dir / (stem + '.md')} ({summary.n_labelled} labelled items)")
    return 0


# --- the guarded held-out run and the combined report --------------------------------


def _run_heldout(args: argparse.Namespace) -> int:
    """The once-only held-out evaluation: guards, preflight, marker, every system, results."""
    paths = EvalPaths.default()
    config = _config()
    if args.contract != "panel":
        return _fail("the held-out run uses the fact-panel contract only (ADR-009)")
    request = HeldOutRequest(
        released=args.released,
        confirm_freeze=args.confirm_freeze,
        ablations=args.ablations,
        authorize_bedrock_usd=args.authorize_bedrock_usd,
        hobson_url=args.hobson_url,
        expect_config_version=args.expect_config_version,
    )
    try:
        prepared = prepare(paths, request, config_version=config.version)
    except RunRefused as exc:
        return _fail(str(exc))
    problem = _need_decider()
    if problem:
        return _fail(problem)
    settings = get_settings()
    haiku, haiku_reason = build_haiku_baseline(
        settings, config, authorize_usd=request.authorize_bedrock_usd
    )
    held_ids = set(prepared.ids)
    gold = {
        cs: g
        for cs, g in load_gold(paths.adjudicated(HELDOUT)).items()
        if cs in held_ids and g.version >= 2
    }
    labellers = [row.labeller for row in LabelStore(paths.labels(HELDOUT), HELDOUT).rows()]
    date = _today()

    async def go() -> dict[str, Any]:
        client = DeciderClient.from_settings(settings)
        hobson: DeciderClient | None = None
        hobson_model: str | None = None
        hobson_reason: str | None = None
        try:
            identity = await client.health()  # preflight: a down Decider must not burn the run
            model = f"{identity.model} ({identity.device})"
            if request.hobson_url:
                hobson = DeciderClient(request.hobson_url, timeout_s=GPU_TIMEOUT_S)
                try:
                    hid = await hobson.health()
                    hobson_model = f"{hid.model} ({hid.device})"
                except DeciderError as exc:
                    hobson_reason = f"the hobson-v21 server is not usable ({type(exc).__name__})"
                    await hobson.aclose()
                    hobson = None
            deps = RunDeps(
                client=client,
                snapshots=_cached_snapshots(paths),
                config=config,
                hobson_client=hobson,
                haiku=haiku,
                haiku_reason=haiku_reason,
                hobson_reason=hobson_reason,
            )
            return await execute_heldout(
                prepared=prepared,
                paths=paths,
                request=request,
                deps=deps,
                model=model,
                hobson_model=hobson_model,
                gold=gold,
                labellers=labellers,
                date=date,
                progress=print,
            )
        finally:
            await client.aclose()
            if hobson is not None:
                await hobson.aclose()

    try:
        payload = anyio.run(go)
    except (RunRefused, DeciderError, LookupError) as exc:
        return _fail(str(exc))
    print(f"wrote {paths.results_dir / (payload['stem'] + '.md')} ({payload['n_items']} items)")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Render the combined report from the latest results files (nothing is run)."""
    text = render_combined(EvalPaths.default(), _config())
    if args.out:
        write_text_lf(Path(args.out), text)
        print(f"wrote {args.out}")
        return 0
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        print(text)
    return 0


# --- parser ---------------------------------------------------------------------------------


def add_eval_parser(sub: Any) -> None:
    """Register `cso eval` with its subcommands on the top-level subparsers."""
    eval_parser = sub.add_parser("eval", help="evaluation harness and Day-1 spike")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)

    cand = eval_sub.add_parser(
        "candidates", help="collect up to 200 candidate changesets (read-only GETs, polite)"
    )
    cand.add_argument("--limit", type=int, default=200)
    cand.add_argument("--max-minutes", type=float, default=25.0)
    cand.set_defaults(func=_cmd_candidates)

    split = eval_sub.add_parser("split", help="freeze the dev/held-out split (written once)")
    split.add_argument("--dev", type=int, default=60)
    split.add_argument("--heldout", type=int, default=120)
    split.add_argument(
        "--dry-run", action="store_true", help="show sizes and hash without freezing anything"
    )
    split.set_defaults(func=_cmd_split)

    label = eval_sub.add_parser(
        "label", help="label items from rendered evidence (no model output)"
    )
    label.add_argument("--set", choices=[DEV, HELDOUT], default=DEV)
    label.add_argument("--labeller", required=True)
    label.add_argument("--session", required=True)
    label.add_argument("--limit", type=int, default=None)
    label.add_argument(
        "--legacy",
        action="store_true",
        help="schema version 1: nature and response only, no probes",
    )
    label.set_defaults(func=_cmd_label)

    adj = eval_sub.add_parser("adjudicate", help="merge two labelling sessions")
    adj.add_argument("--set", choices=[DEV, HELDOUT], default=DEV)
    adj.add_argument("--a", type=_parse_session, required=True, metavar="LABELLER:SESSION")
    adj.add_argument("--b", type=_parse_session, required=True, metavar="LABELLER:SESSION")
    adj.add_argument("--adjudicator", required=True)
    adj.set_defaults(func=_cmd_adjudicate)

    spike = eval_sub.add_parser("spike", help="Day-1 go/no-go on the 60 dev items")
    spike.add_argument("--contract", choices=["panel", "permutation"], default="panel")
    spike.set_defaults(func=_cmd_spike)

    diag = eval_sub.add_parser(
        "panel-diagnostic", help="run the fact panel over items without labels (not a verdict)"
    )
    diag.add_argument("--set", choices=["all", DEV, HELDOUT], default="all")
    diag.add_argument("--profile", choices=["compact", "full"], default="compact")
    diag.add_argument(
        "--include-heldout",
        action="store_true",
        help="required for --set heldout, and for --set all once the split is frozen: sends the "
        "held-out ids through the Decider (no labels read) and says so in the report",
    )
    diag.add_argument("--tag", default="", help="suffix for the output names, e.g. -v2")
    diag.add_argument(
        "--compare-with",
        default=None,
        metavar="RECEIPTS_DIR_NAME",
        help="append a before/after section for new_account_first_edits against this run",
    )
    diag.set_defaults(func=_cmd_panel_diagnostic)

    ablate = eval_sub.add_parser(
        "ablate-model",
        help="ask a second Decider server the same panel questions and compare (dev set only)",
    )
    ablate.add_argument("--set", choices=[DEV], default=DEV)
    ablate.add_argument(
        "--decider-url", required=True, metavar="URL", help="second server, on this machine"
    )
    ablate.add_argument("--label", required=True, help="short model name used in file names")
    ablate.add_argument("--baseline-label", default="2B", help="name for the default server's run")
    ablate.add_argument(
        "--baseline-json",
        default=None,
        metavar="PATH",
        help="reuse a saved run (a results .json) instead of asking the default server again",
    )
    ablate.set_defaults(func=_cmd_ablate_model)

    backfill_cmd = eval_sub.add_parser(
        "backfill-counts", help="patch cached snapshots with the edit-time changeset count"
    )
    backfill_cmd.set_defaults(func=_cmd_backfill_counts)

    run = eval_sub.add_parser("run", help="run all systems; heldout needs --released")
    run.add_argument("--set", choices=[DEV, HELDOUT, "fixtures"], default=DEV)
    run.add_argument(
        "--released",
        action="store_true",
        help="required for heldout, after the freeze commit; use for the one final run",
    )
    run.add_argument("--contract", choices=["panel", "permutation"], default="panel")
    run.add_argument(
        "--confirm-freeze",
        default=None,
        metavar="COMMIT",
        help="heldout only: the commit hash that froze evaluation/splits/ (verified against git)",
    )
    run.add_argument(
        "--ablations",
        action="store_true",
        help="heldout only: also run the without-cues and three paraphrase ablations",
    )
    run.add_argument(
        "--authorize-bedrock-usd",
        type=float,
        default=None,
        metavar="USD",
        help="heldout only: dollar ceiling that allows the Haiku baselines (also needs "
        "CSO_MODE=live and CSO_LIVE_BEDROCK=1); without it they are reported as not run",
    )
    run.add_argument(
        "--hobson-url",
        default=None,
        metavar="URL",
        help="heldout only: a second Decider server running hobson-v21 for that ablation",
    )
    run.add_argument(
        "--expect-config-version",
        default=None,
        metavar="PREFIX",
        help="heldout only: refuse unless the community config version starts with this",
    )
    run.set_defaults(func=_cmd_run)

    report = eval_sub.add_parser(
        "report", help="render one markdown report from the latest results files (runs nothing)"
    )
    report.add_argument("--latest", action="store_true", required=True)
    report.add_argument("--out", default=None, metavar="PATH", help="write here instead of stdout")
    report.set_defaults(func=_cmd_report)
