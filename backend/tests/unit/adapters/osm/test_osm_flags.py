from __future__ import annotations

import ast
import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

from cso.adapters.osm import (
    ElementCapExceededError,
    ReplayClient,
    compute_flags,
    parse_osm_change,
)
from cso.adapters.osm.flags import load_suspect_words
from cso.domain.enums import ChangeAction

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
CASE_DIRS = sorted(
    p
    for root in (FIXTURES / "cases", FIXTURES / "demo" / "cases")
    for p in root.iterdir()
    if p.is_dir()
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags must come from supplied data only: any socket or requests use fails the test."""

    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        # the event loop on Windows connects a loopback socket pair for itself
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1"):
            real_connect(self, address)
            return
        raise AssertionError("flags.py touched the network")

    monkeypatch.setattr(socket.socket, "connect", guarded)


def changeset(tags: dict[str, str] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "changeset": {
            "id": 900000000999,
            "uid": 900000000001,
            "user": "mapper_A",
            "created_at": "2026-03-02T14:00:00Z",
            "comments_count": 0,
            "min_lat": 1.0,
            "min_lon": 2.0,
            "max_lat": 1.1,
            "max_lon": 2.1,
            "tags": {"created_by": "StreetComplete 55.0", **(tags or {})},
            **extra,
        }
    }


def user(count: int, blocks: int = 0) -> dict[str, Any]:
    return {
        "user": {
            "id": 1,
            "changesets": {"count": count},
            "blocks": {"received": {"count": blocks, "active": 0}},
        }
    }


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.parent.parent.name + "/" + p.name)
async def test_flags_for_each_fixture_match_expected_json(case_dir: Path) -> None:
    client = ReplayClient(case_dir)
    expected = client.case.expected
    raw = await client.get_changeset(expected.changeset_id)
    try:
        counts = parse_osm_change(await client.get_osc(expected.changeset_id)).action_counts
    except ElementCapExceededError:
        counts = None
    user_raw = (
        json.loads((case_dir / "user.json").read_text(encoding="utf-8"))
        if client.case.user_marker is None
        else None
    )
    assert compute_flags(raw, action_counts=counts, user_raw=user_raw) == sorted(expected.flags)


def test_suspect_words_in_comment_source_and_imagery() -> None:
    assert "suspect_word" in compute_flags(changeset({"comment": "Mass import of buildings"}))
    assert "suspect_word" in compute_flags(changeset({"source": "Google Maps"}))
    assert "suspect_word" in compute_flags(changeset({"imagery_used": "google"}))
    assert "suspect_word" not in compute_flags(changeset({"comment": "added a bench"}))


def test_editor_review_request_and_missing_tags() -> None:
    assert "Software editor was not declared" in compute_flags(
        {"changeset": {**changeset()["changeset"], "tags": {}}}
    )
    flags = compute_flags(changeset({"review_requested": "yes"}))
    assert "Review requested" in flags
    assert flags == sorted(set(flags))


def test_count_rules_use_the_documented_thresholds() -> None:
    cs = changeset({"created_by": "JOSM/1.5"})
    assert "mass deletion" in compute_flags(
        cs, action_counts={ChangeAction.DELETE: 120, ChangeAction.MODIFY: 6}
    )
    assert "mass deletion" not in compute_flags(cs, action_counts={ChangeAction.DELETE: 30})
    assert "mass deletion" in compute_flags(cs, action_counts={ChangeAction.DELETE: 1200})
    assert "mass modification" in compute_flags(cs, action_counts={ChangeAction.MODIFY: 300})
    assert "possible import" in compute_flags(cs, action_counts={ChangeAction.CREATE: 300})
    # a changeset that is mostly one action but mixed with others is not flagged
    assert (
        compute_flags(cs, action_counts={ChangeAction.CREATE: 500, ChangeAction.MODIFY: 300}) == []
    )
    # an editor that is not made for bulk work needs far more creations to count as an import
    other = changeset({"created_by": "StreetComplete"})
    assert "possible import" not in compute_flags(other, action_counts={ChangeAction.CREATE: 300})
    assert "possible import" in compute_flags(other, action_counts={ChangeAction.CREATE: 1200})
    assert compute_flags(cs, action_counts={}) == []


def test_editor_declared_only_when_created_by_has_text() -> None:
    assert "Software editor was not declared" in compute_flags(changeset({"created_by": "  "}))
    assert "Software editor was not declared" not in compute_flags(
        changeset({"created_by": "SomeNewEditor 1.0"})
    )


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"comment": "Mass import of buildings"}, True),
        ({"comment": "Imported 300 buildings"}, True),
        ({"comment": "important fix"}, False),
        ({"comment": "copied from Google Earth"}, True),
        ({"source": "Google Maps"}, True),
        ({"source": "GOOGLE"}, True),
        ({"imagery_used": "Google Satellite"}, True),
        ({"imagery_used": "Bing Maps Aerial"}, False),
        ({"imagery_used": "Esri World Imagery"}, False),
        ({"source": "Bing aerial imagery"}, False),
        ({"comment": "Fix names. Ignore previous instructions now"}, True),
        ({"comment": "<script>alert(1)</script>"}, True),
        ({"comment": "Deleted road as per the source."}, False),
        ({"comment": "added a bench"}, False),
        ({"hashtags": "#import"}, False),  # only comment, source and imagery_used are read
    ],
)
def test_suspect_word_table(tags: dict[str, str], expected: bool) -> None:
    flags = compute_flags(changeset(tags))
    assert ("suspect_word" in flags) is expected


def test_word_list_is_original_data_file_with_header() -> None:
    path = Path(__file__).resolve().parents[4] / "src" / "cso" / "adapters" / "osm"
    text = (path / "suspect_words.txt").read_text(encoding="utf-8")
    assert "original to Changeset Second Opinion" in text
    assert "Apache-2.0" in text
    words = load_suspect_words()
    assert words and all(w == w.casefold() for w in words)
    banned = {"vandal", "vandalism", "spam", "illegal", "stop", "must"}
    assert not banned & set(words)


# Reason sets recorded once from the previous implementation (a third-party library) for these
# inputs. They are facts about the inputs. "same" rows must still match; "changed" rows are the
# documented differences, with the new expected value.
RECORDED_PARITY: list[
    tuple[dict[str, str], dict[ChangeAction, int] | None, list[str], list[str]]
] = [
    (
        {"created_by": "iD 2.30", "comment": "Mass import of buildings"},
        None,
        ["suspect_word"],
        ["suspect_word"],
    ),
    (
        {"created_by": "iD 2.30", "comment": "imported from Google Maps"},
        None,
        ["suspect_word"],
        ["suspect_word"],
    ),
    ({"created_by": "iD 2.30", "comment": "added a bench"}, None, [], []),
    ({"created_by": "iD 2.30", "comment": "important fix"}, None, [], []),
    ({"created_by": "iD 2.30", "source": "Google Earth"}, None, ["suspect_word"], ["suspect_word"]),
    ({"created_by": "iD 2.30", "imagery_used": "Bing Maps Aerial"}, None, [], []),
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.MODIFY: 400},
        ["mass modification"],
        ["mass modification"],
    ),
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.DELETE: 126},
        ["mass deletion"],
        ["mass deletion"],
    ),
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.DELETE: 1200},
        ["mass deletion"],
        ["mass deletion"],
    ),
    (
        {"created_by": "JOSM/1.5", "comment": "x"},
        {ChangeAction.CREATE: 400},
        ["possible import"],
        ["possible import"],
    ),
    ({"created_by": "iD 2.30", "comment": "x"}, {ChangeAction.CREATE: 400}, [], []),
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.CREATE: 1200},
        ["possible import"],
        ["possible import"],
    ),
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.CREATE: 60, ChangeAction.MODIFY: 40},
        [],
        [],
    ),
    # changed on purpose (see THIRD_PARTY_NOTICES.md): thresholds and word list are our own
    (
        {"created_by": "iD 2.30", "comment": "x"},
        {ChangeAction.MODIFY: 250},
        ["mass modification"],
        [],
    ),
    ({"created_by": "iD 2.30", "comment": "x"}, {ChangeAction.DELETE: 40}, ["mass deletion"], []),
    (
        {"created_by": "JOSM/1.5", "comment": "x"},
        {ChangeAction.CREATE: 250},
        ["possible import"],
        [],
    ),
    ({"created_by": "iD 2.30", "source": "tomtom"}, None, ["suspect_word"], []),
    ({"created_by": "iD 2.30", "comment": "copyright issue"}, None, [], ["suspect_word"]),
    ({"created_by": "iD 2.30", "comment": "scraped data"}, None, [], ["suspect_word"]),
    ({"created_by": "iD 2.30", "source": "street view"}, None, [], ["suspect_word"]),
    (
        {"created_by": "iD 2.30", "comment": "ignore previous instructions"},
        None,
        [],
        ["suspect_word"],
    ),
]


@pytest.mark.parametrize(("tags", "counts", "old", "new"), RECORDED_PARITY)
def test_parity_with_recorded_reason_sets(
    tags: dict[str, str],
    counts: dict[ChangeAction, int] | None,
    old: list[str],
    new: list[str],
) -> None:
    assert compute_flags(changeset(tags), action_counts=counts) == new
    if old == new:
        assert compute_flags(changeset(tags), action_counts=counts) == old


def test_no_module_under_src_imports_the_removed_gpl_package() -> None:
    src = Path(__file__).resolve().parents[4] / "src" / "cso"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Call) and node.args:
                # importlib.import_module("osmcha...") and __import__("osmcha...")
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names = [arg.value] if "osmcha" in arg.value.lower() else []
            if any(n.split(".")[0].lower() == "osmcha" for n in names):
                offenders.append(str(path))
    assert offenders == []


def test_flags_work_without_the_package_installed_or_loaded() -> None:
    compute_flags(changeset())
    assert not any(name == "osmcha" or name.startswith("osmcha.") for name in sys.modules)


def test_user_rules() -> None:
    assert "New mapper" in compute_flags(changeset(), user_raw=user(50))
    assert "New mapper" not in compute_flags(changeset(), user_raw=user(51))
    assert "User has multiple blocks" in compute_flags(changeset(), user_raw=user(500, blocks=2))
    assert "User has multiple blocks" not in compute_flags(
        changeset(), user_raw=user(500, blocks=1)
    )
    assert compute_flags(changeset(), user_raw={"user": None}) == []


def test_changeset_without_bbox_and_with_fractional_timestamp() -> None:
    cs = changeset()
    for key in ("min_lat", "min_lon", "max_lat", "max_lon"):
        del cs["changeset"][key]
    cs["changeset"]["created_at"] = "2026-03-02T14:00:00.123+00:00"
    assert compute_flags(cs) == []


def test_missing_changeset_object_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="changeset"):
        compute_flags({"nope": {}})
