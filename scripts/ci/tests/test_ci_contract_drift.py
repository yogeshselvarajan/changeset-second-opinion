"""Acceptance: the contract drift job fails when `backend/openapi/v1.json` is stale.

Uses a temporary copy, never the committed file. Needs the backend environment (the app is
imported to build the document), so it is skipped when `cso` is not importable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

export = pytest.importorskip("cso.tools.export_openapi")


def test_the_committed_document_matches_the_app() -> None:
    assert export.diff_against_file() == ""


def test_a_stale_copy_produces_a_diff_and_check_exits_non_zero(tmp_path: Path) -> None:
    document = json.loads(Path(export.OPENAPI_PATH).read_text(encoding="utf-8"))
    document["info"]["title"] = "stale"
    stale = tmp_path / "v1.json"
    stale.write_text(export.canonical_json(document), encoding="utf-8")
    assert export.diff_against_file(stale) != ""
    assert export.main(["--check", "--out", str(stale)]) == 1


def test_a_missing_document_is_a_diff_too(tmp_path: Path) -> None:
    assert export.diff_against_file(tmp_path / "absent.json") != ""
