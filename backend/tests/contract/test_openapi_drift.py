"""The committed OpenAPI file is the contract: the app must equal it (CI fails with a diff)."""

from __future__ import annotations

import json

from cso.tools.export_openapi import (
    OPENAPI_PATH,
    build_openapi,
    canonical_json,
    diff_against_file,
    main,
)


def test_committed_openapi_matches_the_app() -> None:
    diff = diff_against_file()
    assert diff == "", (
        "backend/openapi/v1.json is out of date. Regenerate it with "
        "`uv run python -m cso.tools.export_openapi` (integration owner) and commit it.\n"
        + diff[:4000]
    )


def test_committed_file_is_canonical_text() -> None:
    raw = OPENAPI_PATH.read_bytes()
    assert b"\r" not in raw, "line endings must be LF"
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    document = json.loads(raw.decode("utf-8"))
    assert canonical_json(document) == raw.decode("utf-8")  # sorted keys, two-space indent


def test_check_mode_exits_zero_when_current_and_one_when_not(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert main(["--check"]) == 0
    stale = tmp_path / "v1.json"
    stale.write_text(canonical_json({**build_openapi(), "info": {"title": "x", "version": "0"}}))
    assert main(["--check", "--out", str(stale)]) == 1
    missing = tmp_path / "absent.json"
    assert main(["--check", "--out", str(missing)]) == 1


def test_export_writes_the_same_bytes_twice(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert main(["--out", str(first)]) == 0 and main(["--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes() == OPENAPI_PATH.read_bytes()
