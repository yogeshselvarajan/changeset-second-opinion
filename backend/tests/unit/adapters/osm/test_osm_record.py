from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cso import cli
from cso.adapters.osm import ReplayClient, collect
from cso.adapters.osm.record import Anonymizer, RecordError, record_case
from cso.domain.fixtures import load_case

CS = 920_000_000_001
PII = [
    "Alice Realname",
    "Bob Realname",
    "Carol Realname",
    "123456",
    "654321",
    "alice@example.com",
    "bob@example.org",
    "https://example.com/private",
    "http://bob.example/profile",
    "Dora Realname",
    "Hidden Person",
    "secret hidden words",
    "my private description",
    "https://img.example/me.png",
]


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _element(osm_type: str, osm_id: int, version: int, tags: dict[str, str]) -> dict[str, Any]:
    return {
        "elements": [
            {
                "type": osm_type,
                "id": osm_id,
                "version": version,
                "timestamp": "2024-02-01T00:00:00Z",
                "visible": True,
                "user": "Carol Realname",
                "uid": 111,
                "tags": tags,
            }
        ]
    }


OSC = (
    '<osmChange version="0.6">'
    '<modify><way id="77" version="3" changeset="920000000001" '
    'timestamp="2026-03-01T10:12:00Z" user="Alice Realname" uid="123456">'
    '<nd ref="1"/><tag k="highway" v="path"/><tag k="name" v="New Name"/></way></modify>'
    '<delete><node id="78" version="2" changeset="920000000001" '
    'timestamp="2026-03-01T10:13:00Z" user="Alice Realname" uid="123456"/></delete>'
    '<modify><way id="79" version="4" changeset="920000000001" '
    'timestamp="2026-03-01T10:14:00Z" user="Dora Realname" uid="654321">'
    '<nd ref="2"/><tag k="highway" v="track"/></way></modify>'
    "</osmChange>"
)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """A 'live' source with personal data everywhere, served through ReplayClient."""
    d = tmp_path / "source"
    _write(
        d / "changeset.json",
        {
            "version": "0.6",
            "copyright": "OpenStreetMap and contributors",
            "attribution": "http://www.openstreetmap.org/copyright",
            "license": "http://opendatacommons.org/licenses/odbl/1-0/",
            "changeset": {
                "id": CS,
                "created_at": "2026-03-01T10:10:00Z",
                "closed_at": "2026-03-01T10:20:00Z",
                "open": False,
                "uid": 123456,
                "user": "Alice Realname",
                "comments_count": 2,
                "changes_count": 3,
                "min_lat": 51.5,
                "min_lon": -0.1,
                "max_lat": 51.6,
                "max_lon": 0.0,
                "tags": {
                    "comment": "Fix roads, mail alice@example.com see https://example.com/private",
                    "created_by": "JOSM/1.5",
                    "source": "survey",
                },
                "comments": [
                    {
                        "id": 1,
                        "visible": True,
                        "date": "2026-03-01T11:00:00Z",
                        "uid": 654321,
                        "user": "Bob Realname",
                        "text": "Explain please, bob@example.org http://bob.example/profile",
                    },
                    {
                        "id": 2,
                        "visible": False,
                        "date": "2026-03-01T11:05:00Z",
                        "uid": 777,
                        "user": "Hidden Person",
                        "text": "secret hidden words",
                    },
                ],
            },
        },
    )
    _write(d / "download.osc", OSC)
    _write(d / "prev" / "way_77_2.json", _element("way", 77, 2, {"highway": "path", "name": "Old"}))
    _write(d / "prev" / "node_78_1.__timeout__", b"")
    _write(d / "prev" / "way_79_3.__403__", b"")  # redacted: the history fallback finds v2
    _write(d / "prev" / "way_79_2.json", _element("way", 79, 2, {"highway": "path"}))
    _write(
        d / "user.json",
        {
            "user": {
                "id": 123456,
                "display_name": "Alice Realname",
                "account_created": "2019-05-01T00:00:00Z",
                "description": "my private description",
                "img": {"href": "https://img.example/me.png"},
                "changesets": {"count": 12},
                "blocks": {"received": {"count": 0, "active": 0}},
            }
        },
    )
    _write(
        d / "expected.json",
        {
            "fixture_id": "source",
            "description": "pii source",
            "changeset_id": CS,
            "coverage": {"elements_in_changeset": 3, "elements_detailed": 3, "score": 0.0},
            "flags": [],
            "rules": [],
        },
    )
    return d


async def test_recorded_case_replays_to_the_same_evidence(source_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "fixtures" / "cases" / "09-recorded"
    original = await collect(ReplayClient(source_dir), CS)

    result = await record_case(ReplayClient(source_dir), CS, out)

    replayed = await collect(ReplayClient(out), CS)
    assert replayed.coverage == original.coverage == result.snapshot.coverage
    assert replayed.tag_diffs == original.tag_diffs
    assert [e.model_dump(exclude={"source"}) for e in replayed.elements] == [
        e.model_dump(exclude={"source"}) for e in original.elements
    ]
    assert load_case(out).expected.coverage == original.coverage
    # the redacted v3 became a marker; the history fallback's v2 became an ordinary data file
    assert (out / "prev" / "way_79_3.__403__").exists()
    assert (out / "prev" / "way_79_2.json").exists()
    assert (out / "prev" / "node_78_1.__timeout__").exists()
    assert {g.reason.value for g in replayed.coverage.history_gaps} == {"timeout"}


async def test_nothing_identifying_is_written(source_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    await record_case(ReplayClient(source_dir), CS, out)

    text = "\n".join(
        p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file() and p.suffix != ""
    )
    assert [needle for needle in PII if needle in text] == []
    assert "mapper_A" in text and "[email removed]" in text and "[url removed]" in text
    user = json.loads((out / "user.json").read_text(encoding="utf-8"))["user"]
    changeset = json.loads((out / "changeset.json").read_text(encoding="utf-8"))["changeset"]
    assert user["display_name"] == "mapper_A"  # same person as the changeset author
    assert user["id"] == changeset["uid"]
    assert set(user) == {"id", "display_name", "account_created", "changesets", "blocks"}
    assert [c["id"] for c in changeset["comments"]] == [1]  # the moderated comment is dropped
    osc = (out / "download.osc").read_text(encoding="utf-8")
    assert 'user="mapper_A"' in osc and 'uid="900000001"' in osc
    assert changeset["comments"][0]["uid"] == 900000002  # same real uid -> same fake uid ...
    assert 'uid="900000002"' in osc  # ... in the osmChange too


async def test_existing_non_empty_target_is_refused(source_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "taken"
    out.mkdir()
    (out / "keep.txt").write_text("x", encoding="utf-8")

    with pytest.raises(RecordError, match="non-empty"):
        await record_case(ReplayClient(source_dir), CS, out)
    assert (out / "keep.txt").read_text(encoding="utf-8") == "x"
    assert not (out / "changeset.json").exists()


async def test_user_failure_becomes_a_marker(source_dir: Path, tmp_path: Path) -> None:
    (source_dir / "user.json").unlink()
    (source_dir / "user.__timeout__").write_bytes(b"")
    out = tmp_path / "out"

    await record_case(ReplayClient(source_dir), CS, out)

    assert (out / "user.__timeout__").exists() and not (out / "user.json").exists()
    assert load_case(out).user_marker is not None


def test_anonymizer_is_stable_and_labels_past_z() -> None:
    anon = Anonymizer()
    names = [anon.name(f"person {i}") for i in range(28)]

    assert names[0] == "mapper_A" and names[25] == "mapper_Z" and names[26] == "mapper_AA"
    assert anon.name("person 3") == names[3]
    assert anon.name(None) is None and anon.uid(None) is None
    assert anon.uid(5) == anon.uid(5) == 900_000_001 and anon.uid(6) == 900_000_002
    assert (
        anon.scrub_text("a@b.co and www.x.org/p?q=1 ok") == "[email removed] and [url removed] ok"
    )


# ------------------------------------------------------------------ CLI


class _FakeLiveClient(ReplayClient):
    """Stands in for OsmClient so the CLI test never touches the network."""

    async def aclose(self) -> None:
        return None


def test_cli_record_writes_the_case_without_network(
    source_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_osm_client", lambda: _FakeLiveClient(source_dir))
    out = tmp_path / "09-from-cli"

    assert cli.main(["record", str(CS), "--out", str(out)]) == 0

    assert "recorded changeset" in capsys.readouterr().out
    assert load_case(out).changeset.id == CS


def test_cli_record_reports_errors_and_keeps_existing_files(
    source_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_osm_client", lambda: _FakeLiveClient(source_dir))
    out = tmp_path / "taken"
    out.mkdir()
    (out / "x").write_text("x", encoding="utf-8")

    assert cli.main(["record", str(CS), "--out", str(out)]) == 1
    assert "non-empty" in capsys.readouterr().err

    assert cli.main(["record", "999", "--out", str(tmp_path / "other")]) == 1  # not found
    assert "cso record:" in capsys.readouterr().err
