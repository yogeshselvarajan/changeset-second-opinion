import argparse
import sys
from pathlib import Path

import anyio
import uvicorn

from cso.adapters.osm import OsmClient
from cso.adapters.osm.errors import OsmError
from cso.adapters.osm.record import RecordError, record_case
from cso.evaluation.eval_cli import add_eval_parser
from cso.settings import get_settings


def _api(args: argparse.Namespace) -> int:
    # The app writes its own access line (with request ids), so uvicorn's is switched off.
    uvicorn.run("cso.main:app", host=args.host, port=args.port, access_log=False)
    return 0


def _worker(args: argparse.Namespace) -> int:
    from cso.adapters.osm.errors import NotFoundError
    from cso.jobs import run_worker_cli
    from cso.observability import configure_from_settings

    configure_from_settings(get_settings())
    try:
        return anyio.run(
            lambda: run_worker_cli(
                get_settings(),
                once=args.once,
                fixture=args.fixture,
                concurrency=args.concurrency,
            )
        )
    except (NotFoundError, ValueError) as exc:
        print(f"cso worker: {exc}", file=sys.stderr)
        return 1


def _osm_client() -> OsmClient:
    return OsmClient.from_settings(get_settings())


def _record(args: argparse.Namespace) -> int:
    async def run() -> int:
        client = _osm_client()
        try:
            result = await record_case(client, args.changeset_id, Path(args.out))
        finally:
            await client.aclose()
        coverage = result.snapshot.coverage
        print(
            f"recorded changeset {args.changeset_id} to {result.out} "
            f"({len(result.files)} files, {client.calls} API calls, "
            f"{coverage.elements_detailed}/{coverage.elements_in_changeset} elements detailed, "
            f"{len(coverage.history_gaps)} gaps)"
        )
        return 0

    try:
        return anyio.run(run)
    except (OsmError, RecordError) as exc:
        print(f"cso record: {exc}", file=sys.stderr)
        return 1


def _db_upgrade(args: argparse.Namespace) -> int:
    from cso.persistence.admin import upgrade_database

    url = get_settings().database_url
    upgrade_database(url, args.revision)
    print(f"database at {args.revision}: {url}")
    return 0


def _seed(args: argparse.Namespace) -> int:
    from cso.persistence.admin import seed_fixtures, upgrade_database
    from cso.persistence.db import make_engine, make_sessionmaker

    async def run() -> int:
        url = get_settings().database_url
        await anyio.to_thread.run_sync(upgrade_database, url)
        engine = make_engine(url)
        try:
            report = await seed_fixtures(make_sessionmaker(engine), Path(args.fixtures))
        finally:
            await engine.dispose()
        print(
            f"seeded {report.cases_created} new and {report.cases_existing} existing cases "
            f"({report.snapshots_created} snapshots, {report.runs_created} runs)"
        )
        for skipped in report.runs_skipped:
            print(f"skipped run: {skipped}", file=sys.stderr)
        return 0

    try:
        return anyio.run(run)
    except (OSError, ValueError) as exc:
        print(f"cso seed: {exc}", file=sys.stderr)
        return 1


def _auth_create_invite(args: argparse.Namespace) -> int:
    """Create an invite code; the plaintext code goes to stdout once and is never stored."""
    from datetime import timedelta

    from cso.api.auth_core import AuthConfig, InviteHasher, create_invite
    from cso.persistence.admin import upgrade_database
    from cso.persistence.db import make_engine, make_sessionmaker, session_scope

    async def run() -> int:
        settings = get_settings()
        await anyio.to_thread.run_sync(upgrade_database, settings.database_url)
        engine = make_engine(settings.database_url)
        try:
            hasher = InviteHasher(AuthConfig.from_settings(settings))
            ttl = timedelta(hours=args.ttl_hours) if args.ttl_hours else None
            async with session_scope(make_sessionmaker(engine)) as db:
                code, row = await create_invite(
                    db, hasher, role=args.role, label=args.label, max_uses=args.max_uses, ttl=ttl
                )
        finally:
            await engine.dispose()
        print(code)
        uses = row.max_uses if row.max_uses is not None else "unlimited"
        expires = row.expires_at.isoformat() if row.expires_at else "never"
        print(
            f"role={row.role} label={row.label!r} max_uses={uses} expires={expires}; "
            "this code is shown once and cannot be recovered",
            file=sys.stderr,
        )
        return 0

    try:
        return anyio.run(run)
    except (OSError, ValueError) as exc:
        print(f"cso auth create-invite: {exc}", file=sys.stderr)
        return 1


def _calibrate(args: argparse.Namespace) -> int:
    """Report what reviewers' decisions say about a pack's cut points; `--apply` stores it."""
    from cso.calibrate import UnknownPackError, run_calibration
    from cso.persistence.admin import upgrade_database
    from cso.persistence.db import make_engine, make_sessionmaker

    async def run() -> int:
        settings = get_settings()
        await anyio.to_thread.run_sync(upgrade_database, settings.database_url)
        engine = make_engine(settings.database_url)
        try:
            result = await run_calibration(
                make_sessionmaker(engine),
                pack_id=args.pack,
                apply=bool(args.apply) and not args.dry_run,
                actor="cli",
            )
        finally:
            await engine.dispose()
        report = result.report
        print(
            f"pack {result.pack_id}: {report.n_outcomes} decisions counted, "
            f"{report.n_labelled_outcomes} gave labels"
        )
        for p in report.probes:
            old = p.default_accuracy.value
            new = p.tuned_accuracy.value
            print(
                f"  {p.probe:<32} n={p.n:<4} {p.status:<18} "
                f"cuts {p.default_low:.2f}/{p.default_high:.2f} -> {p.low:.2f}/{p.high:.2f}  "
                f"accuracy {'n/a' if old is None else f'{old:.2f}'} -> "
                f"{'n/a' if new is None else f'{new:.2f}'}"
            )
        for b in report.bands:
            print(f"  band {b.band:<12} n={b.n:<4} {b.status}")
        if result.applied:
            print(f"applied: calibration {result.calibration_id}, version {result.config_version}")
        elif result.reason:
            print(f"not applied: {result.reason}")
        else:
            print("dry run: nothing was changed (use --apply to store the new cut points)")
        return 0

    try:
        return anyio.run(run)
    except (OSError, UnknownPackError) as exc:
        print(f"cso calibrate: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cso")
    sub = parser.add_subparsers(dest="command", required=True)

    calibrate = sub.add_parser(
        "calibrate", help="refit probe cut points from reviewers' decisions (dry run by default)"
    )
    calibrate.add_argument("--pack", help="pack id (default: the active pack)")
    calibrate.add_argument("--dry-run", action="store_true", help="report only (the default)")
    calibrate.add_argument("--apply", action="store_true", help="store and activate the result")
    calibrate.set_defaults(func=_calibrate)

    api = sub.add_parser("api", help="run the HTTP API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.set_defaults(func=_api)

    worker = sub.add_parser("worker", help="run the job worker")
    worker.add_argument("--once", action="store_true", help="process due jobs, then exit")
    worker.add_argument(
        "--fixture",
        help="replay demo: enqueue this fixture (e.g. 02-good-faith-mistake) and run it",
    )
    worker.add_argument("--concurrency", type=int, default=2, help="jobs in flight at once")
    worker.set_defaults(func=_worker)

    record = sub.add_parser(
        "record", help="record an anonymized replay fixture from the live OSM API (GET only)"
    )
    record.add_argument("changeset_id", type=int)
    record.add_argument("--out", required=True, help="new directory, e.g. fixtures/cases/09-name")
    record.set_defaults(func=_record)

    db = sub.add_parser("db", help="database maintenance")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    upgrade = db_sub.add_parser("upgrade", help="apply migrations (default: head)")
    upgrade.add_argument("--revision", default="head")
    upgrade.set_defaults(func=_db_upgrade)

    seed = sub.add_parser("seed", help="load fixture cases and snapshots for replay mode")
    seed.add_argument(
        "--fixtures",
        default="fixtures/demo",
        help="directory containing cases/ (default: the recorded demo set)",
    )
    seed.set_defaults(func=_seed)

    auth = sub.add_parser("auth", help="reviewer access")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    invite = auth_sub.add_parser(
        "create-invite", help="create an invite code (printed once, stored only as a hash)"
    )
    invite.add_argument("--role", choices=("reviewer", "admin"), default="reviewer")
    invite.add_argument("--label", default="", help="who the code is for (not secret)")
    invite.add_argument(
        "--max-uses", type=int, default=None, help="logins allowed; default no limit"
    )
    invite.add_argument(
        "--ttl-hours", type=float, default=None, help="hours until the code expires; default never"
    )
    invite.set_defaults(func=_auth_create_invite)

    add_eval_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
