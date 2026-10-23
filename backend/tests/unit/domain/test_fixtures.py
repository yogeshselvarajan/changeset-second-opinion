import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cso.domain.enums import OsmType
from cso.domain.fixtures import (
    SYNTHETIC_ID_FLOOR,
    FixtureError,
    Marker,
    changeset_from_api,
    count_osc_elements,
    discussion_from_api,
    load_case,
    user_from_api,
)

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"
CASE_NAMES = ["01-legitimate", "02-good-faith-mistake"]


@pytest.fixture
def case_copy(tmp_path: Path) -> Path:
    target = tmp_path / "01-legitimate"
    shutil.copytree(CASES / "01-legitimate", target)
    return target


@pytest.mark.parametrize("name", CASE_NAMES)
def test_shipped_fixtures_load(name: str) -> None:
    case = load_case(CASES / name)
    assert case.name == name
    assert case.changeset.id >= SYNTHETIC_ID_FLOOR
    assert case.osc_element_count == case.expected.coverage.elements_in_changeset
    assert case.user is not None and case.user.display_name is not None
    assert case.user.display_name.startswith("mapper_")


def test_legitimate_fixture_details() -> None:
    case = load_case(CASES / "01-legitimate")
    assert case.changeset.id == 900000000001
    assert case.changeset.comment == "Specify road surfaces"
    assert case.changeset.bbox is not None and not case.changeset.bbox_wraps
    assert case.user is not None
    assert case.user.changesets_count == 1200
    assert case.user.account_age_days == 2496  # 2019-05-01 -> 2026-03-01 10:10Z
    assert case.discussion == []
    assert sorted(k[1] for k in case.prev) == [900000000101, 900000000102, 900000000103]
    assert case.prev_markers == {}
    assert case.changeset.attribution["license"].endswith("odbl/1-0/")


def test_good_faith_fixture_details() -> None:
    case = load_case(CASES / "02-good-faith-mistake")
    assert case.changeset.id == 900000000002
    assert case.user is not None and case.user.account_age_days == 2
    assert [d.author_display for d in case.discussion] == ["mapper_C"]
    prev = case.prev[(OsmType.WAY, 900000000111, 3)]
    assert prev["elements"][0]["tags"]["name"] == "Elm Street"
    assert case.expected.flags == ["New mapper"]


def test_element_count_mismatch_is_rejected(case_copy: Path) -> None:
    expected_path = case_copy / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    data["coverage"]["elements_in_changeset"] = 99
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FixtureError, match="download.osc has 3"):
        load_case(case_copy)


def test_truncated_fixture_skips_count_check(case_copy: Path) -> None:
    expected_path = case_copy / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    data["coverage"].update(elements_in_changeset=99, snapshot_truncated=True)
    expected_path.write_text(json.dumps(data), encoding="utf-8")
    assert load_case(case_copy).expected.coverage.elements_in_changeset == 99


def test_fixture_id_must_match_directory(tmp_path: Path) -> None:
    target = tmp_path / "99-renamed"
    shutil.copytree(CASES / "01-legitimate", target)
    with pytest.raises(FixtureError, match="fixture_id"):
        load_case(target)


def test_missing_file_is_reported(case_copy: Path) -> None:
    (case_copy / "download.osc").unlink()
    with pytest.raises(FixtureError, match="download.osc"):
        load_case(case_copy)


def test_not_a_directory(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="not a directory"):
        load_case(tmp_path / "missing")


def test_prev_contents_must_match_name(case_copy: Path) -> None:
    path = case_copy / "prev" / "way_900000000101_2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["elements"][0]["version"] = 7
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(FixtureError, match="do not match"):
        load_case(case_copy)


def test_markers_are_loaded(case_copy: Path) -> None:
    (case_copy / "prev" / "way_900000000101_2.json").unlink()
    (case_copy / "prev" / "way_900000000101_2.__403__").write_text("", encoding="utf-8")
    (case_copy / "user.json").unlink()
    (case_copy / "user.__timeout__").write_text("", encoding="utf-8")
    case = load_case(case_copy)
    assert case.prev_markers == {(OsmType.WAY, 900000000101, 2): Marker.FORBIDDEN}
    assert case.user is None and case.user_marker is Marker.TIMEOUT


def test_data_and_marker_clash_is_rejected(case_copy: Path) -> None:
    (case_copy / "prev" / "way_900000000101_2.__timeout__").write_text("", encoding="utf-8")
    with pytest.raises(FixtureError, match="both data and marker"):
        load_case(case_copy)


def test_user_json_and_marker_clash_is_rejected(case_copy: Path) -> None:
    (case_copy / "user.__403__").write_text("", encoding="utf-8")
    with pytest.raises(FixtureError, match="both user.json"):
        load_case(case_copy)


def test_billion_laughs_osc_is_rejected() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE osmChange [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><osmChange><modify>&b;</modify></osmChange>'
    )
    with pytest.raises(FixtureError, match="unsafe or malformed"):
        count_osc_elements(bomb)


def test_osc_structure_is_validated() -> None:
    with pytest.raises(FixtureError, match="root element"):
        count_osc_elements("<osm/>")
    with pytest.raises(FixtureError, match="unexpected block"):
        count_osc_elements("<osmChange><weird/></osmChange>")
    assert count_osc_elements("<osmChange><modify><node/><way/></modify></osmChange>") == 2


def test_antimeridian_bbox_flag() -> None:
    raw: dict[str, Any] = {
        "changeset": {
            "id": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "min_lat": -17.0,
            "min_lon": 179.5,
            "max_lat": -16.0,
            "max_lon": -179.5,
        }
    }
    meta = changeset_from_api(raw)
    assert meta.bbox_wraps is True and meta.bbox == (179.5, -17.0, -179.5, -16.0)


def test_empty_changeset_has_no_bbox_and_review_flag() -> None:
    meta = changeset_from_api(
        {
            "changeset": {
                "id": 2,
                "created_at": "2026-01-01T00:00:00Z",
                "open": True,
                "tags": {"review_requested": "yes"},
            }
        }
    )
    assert meta.bbox is None and meta.open and meta.review_requested


def test_hidden_comments_are_dropped() -> None:
    raw = {
        "changeset": {
            "comments": [
                {
                    "id": 1,
                    "visible": False,
                    "date": "2026-01-01T00:00:00Z",
                    "user": "a",
                    "text": "x",
                },
                {
                    "id": 2,
                    "visible": True,
                    "date": "2026-01-01T00:00:00Z",
                    "user": "b",
                    "text": "y",
                },
            ]
        }
    }
    assert [d.id for d in discussion_from_api(raw)] == [2]


def test_user_from_api_handles_missing_fields() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    facts = user_from_api({"user": {"id": 5, "display_name": "mapper_X"}}, as_of=as_of)
    assert facts.account_age_days is None and facts.changesets_count is None
    with pytest.raises(FixtureError, match="missing 'user'"):
        user_from_api({}, as_of=as_of)
