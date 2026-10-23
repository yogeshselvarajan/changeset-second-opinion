"""Fixture case loader and OSM API response converters (layout: backend/fixtures/schema.md)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as SafeET  # type: ignore[import-untyped]
from pydantic import ValidationError

from cso.domain.enums import Lane, Nature, OsmType, Response
from cso.domain.models import (
    BBox,
    ChangesetMeta,
    Coverage,
    DiscussionEntry,
    FrozenModel,
    UserFacts,
)

SYNTHETIC_ID_FLOOR = 900_000_000_000
_PREV_NAME = re.compile(r"^(node|way|relation)_(\d+)_(\d+)$")
_OSC_ELEMENTS = frozenset({"node", "way", "relation"})
_OSC_ACTIONS = frozenset({"create", "modify", "delete"})

type PrevKey = tuple[OsmType, int, int]  # (type, id, version)


class FixtureError(ValueError):
    """A fixture directory is missing files or violates backend/fixtures/schema.md."""


class Marker(StrEnum):
    """Marker file suffix simulating a provider failure for one prior version or the user."""

    TIMEOUT = "__timeout__"
    FORBIDDEN = "__403__"


class ExpectedOutcome(FrozenModel):
    """Contents of expected.json: what replay must reproduce and the expected conclusion."""

    fixture_id: str
    description: str
    changeset_id: int
    coverage: Coverage
    flags: list[str]
    rules: list[str]
    nature: Nature | None = None
    response: Response | None = None
    lane: Lane | None = None
    notes: str = ""
    place_label: str | None = None
    receipt: dict[str, Any] | None = None


class FixtureCase(FrozenModel):
    """A fully loaded and validated fixture case."""

    name: str
    changeset: ChangesetMeta
    discussion: list[DiscussionEntry]
    changeset_raw: dict[str, Any]
    osc_xml: str
    osc_element_count: int
    prev: dict[PrevKey, dict[str, Any]]
    prev_markers: dict[PrevKey, Marker]
    user: UserFacts | None
    user_marker: Marker | None
    expected: ExpectedOutcome


# ----------------------------------------------------------------------- API converters


def parse_edit_time_count(tags: dict[str, Any]) -> int | None:
    """The `changesets_count` changeset tag as a non-negative int; anything else is ignored."""
    value = tags.get("changesets_count")
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 9:
        return int(value)
    return None


def plausible_edit_time_count(tag: int | None, current_total: int | None) -> int | None:
    """The mapper-written `changesets_count` tag, only when it can be true.

    A count taken when the edit was made never exceeds the account's total now, so a tag above the
    known total (or a negative one) is a claim we do not trust and is ignored. With no known total
    there is nothing to check it against and the tag stands. The mapper chooses the tag, so it must
    never make the evidence less cautious than the API-derived total would (review F-M5).
    """
    if tag is None or tag < 0:
        return None
    if current_total is not None and tag > current_total:
        return None
    return tag


def apply_edit_time_count(user: UserFacts | None, meta: ChangesetMeta) -> UserFacts | None:
    """Prefer the changeset's edit-time count over the account's current total, when plausible.

    The tag is used only if `0 <= tag <= the account's current total` (when that total is known).
    Otherwise it is ignored and the current total is kept, labelled as such; nothing is invented.
    """
    if user is None:
        return None
    tag = plausible_edit_time_count(meta.changesets_count, user.changesets_count)
    if tag is not None:
        update: dict[str, Any] = {
            "changesets_count": tag,
            "changesets_count_basis": "edit_time",
        }
        return user.model_copy(update=update)
    if user.changesets_count is not None:
        return user.model_copy(update={"changesets_count_basis": "current"})
    return user


def changeset_from_api(raw: dict[str, Any]) -> ChangesetMeta:
    """Convert a `changeset.json` response (envelope with a `changeset` object) to ChangesetMeta."""
    cs = raw.get("changeset")
    if not isinstance(cs, dict):
        raise FixtureError("changeset.json: missing 'changeset' object")
    tags: dict[str, str] = cs.get("tags") or {}
    bbox: BBox | None = None
    wraps = False
    if all(k in cs for k in ("min_lat", "min_lon", "max_lat", "max_lon")):
        bbox = (cs["min_lon"], cs["min_lat"], cs["max_lon"], cs["max_lat"])
        wraps = cs["min_lon"] > cs["max_lon"]  # antimeridian crossing
    attribution: dict[str, str] = {
        k: str(raw[k]) for k in ("copyright", "attribution", "license") if k in raw
    }
    try:
        return ChangesetMeta(
            id=cs["id"],
            uid=cs.get("uid"),
            user_display=cs.get("user"),
            comment=tags.get("comment"),
            source=tags.get("source"),
            created_by=tags.get("created_by"),
            locale=tags.get("locale"),
            imagery_used=tags.get("imagery_used"),
            review_requested=tags.get("review_requested") == "yes",
            created_at=cs["created_at"],
            closed_at=cs.get("closed_at"),
            open=bool(cs.get("open", False)),
            bbox=bbox,
            bbox_wraps=wraps,
            comments_count=cs.get("comments_count", 0),
            changes_count=cs.get("changes_count", 0),
            changesets_count=parse_edit_time_count(tags),
            attribution=attribution,
        )
    except (KeyError, ValidationError) as exc:
        raise FixtureError(f"changeset.json: invalid changeset: {exc}") from exc


def discussion_from_api(raw: dict[str, Any]) -> list[DiscussionEntry]:
    """Convert the `comments` list of a `changeset.json` response; hidden comments are skipped."""
    cs = raw.get("changeset") or {}
    entries: list[DiscussionEntry] = []
    for item in cs.get("comments") or []:
        if item.get("visible", True) is False:
            continue
        try:
            entries.append(
                DiscussionEntry(
                    id=item["id"],
                    author_display=item.get("user") or "",
                    date=item["date"],
                    text=item.get("text") or "",
                )
            )
        except (KeyError, ValidationError) as exc:
            raise FixtureError(f"changeset.json: invalid comment: {exc}") from exc
    return entries


def user_from_api(raw: dict[str, Any], *, as_of: datetime) -> UserFacts:
    """Convert a `user/{uid}.json` response; account age is measured at `as_of` (timezone-aware)."""
    user = raw.get("user")
    if not isinstance(user, dict):
        raise FixtureError("user.json: missing 'user' object")
    age: int | None = None
    created = user.get("account_created")
    if created:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age = max(0, (as_of - created_dt).days)
    user_count = (user.get("changesets") or {}).get("count")
    try:
        return UserFacts(
            uid=user.get("id"),
            display_name=user.get("display_name"),
            account_age_days=age,
            changesets_count=user_count,
            changesets_count_basis="current" if user_count is not None else None,
            blocks_active=((user.get("blocks") or {}).get("received") or {}).get("active"),
        )
    except ValidationError as exc:
        raise FixtureError(f"user.json: invalid user: {exc}") from exc


# ----------------------------------------------------------------------- loader


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"{path}: cannot read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FixtureError(f"{path}: top level must be an object")
    return data


def count_osc_elements(xml_text: str, *, source: str = "download.osc") -> int:
    """Count node/way/relation elements inside create/modify/delete blocks (safe XML parsing)."""
    try:
        root = SafeET.fromstring(xml_text, forbid_dtd=True, forbid_entities=True)
    except Exception as exc:  # defusedxml raises several parse/forbidden types
        raise FixtureError(f"{source}: unsafe or malformed XML: {exc}") from exc
    if root.tag != "osmChange":
        raise FixtureError(f"{source}: root element must be osmChange, got {root.tag!r}")
    total = 0
    for block in root:
        if block.tag not in _OSC_ACTIONS:
            raise FixtureError(f"{source}: unexpected block <{block.tag}>")
        total += sum(1 for el in block if el.tag in _OSC_ELEMENTS)
    return total


def _parse_key(stem: str, path: Path) -> PrevKey:
    match = _PREV_NAME.match(stem)
    if not match:
        raise FixtureError(f"{path}: name must be <type>_<id>_<version>")
    return OsmType(match.group(1)), int(match.group(2)), int(match.group(3))


def _load_prev(case_dir: Path) -> tuple[dict[PrevKey, dict[str, Any]], dict[PrevKey, Marker]]:
    prev: dict[PrevKey, dict[str, Any]] = {}
    markers: dict[PrevKey, Marker] = {}
    prev_dir = case_dir / "prev"
    if not prev_dir.is_dir():
        return prev, markers
    for path in sorted(prev_dir.iterdir()):
        suffix = path.suffix.removeprefix(".")
        if path.suffix == ".json":
            key = _parse_key(path.stem, path)
            data = _read_json(path)
            elements = data.get("elements")
            if not isinstance(elements, list) or len(elements) != 1:
                raise FixtureError(f"{path}: expected exactly one entry in 'elements'")
            el = elements[0]
            if (el.get("type"), el.get("id"), el.get("version")) != (key[0].value, key[1], key[2]):
                raise FixtureError(f"{path}: contents do not match file name {path.stem}")
            prev[key] = data
        elif suffix in {m.value for m in Marker}:
            markers[_parse_key(path.stem, path)] = Marker(suffix)
        else:
            raise FixtureError(f"{path}: unexpected file in prev/")
    clash = prev.keys() & markers.keys()
    if clash:
        raise FixtureError(f"{prev_dir}: both data and marker for {sorted(clash)}")
    return prev, markers


def load_case(path: Path | str) -> FixtureCase:
    """Load and validate one fixture directory; raises FixtureError with the offending path."""
    case_dir = Path(path)
    if not case_dir.is_dir():
        raise FixtureError(f"{case_dir}: not a directory")

    changeset_raw = _read_json(case_dir / "changeset.json")
    changeset = changeset_from_api(changeset_raw)
    discussion = discussion_from_api(changeset_raw)

    osc_path = case_dir / "download.osc"
    try:
        osc_xml = osc_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FixtureError(f"{osc_path}: cannot read: {exc}") from exc
    osc_count = count_osc_elements(osc_xml, source=str(osc_path))

    user: UserFacts | None = None
    user_marker: Marker | None = None
    user_path = case_dir / "user.json"
    marker_paths = [(m, case_dir / f"user.{m.value}") for m in Marker]
    present_markers = [m for m, p in marker_paths if p.exists()]
    if user_path.exists() and present_markers:
        raise FixtureError(f"{case_dir}: both user.json and a user marker are present")
    if user_path.exists():
        user = user_from_api(_read_json(user_path), as_of=changeset.created_at)
    elif present_markers:
        user_marker = present_markers[0]
    else:
        raise FixtureError(f"{case_dir}: needs user.json or a user.__timeout__/__403__ marker")

    prev, prev_markers = _load_prev(case_dir)

    expected_path = case_dir / "expected.json"
    try:
        expected = ExpectedOutcome.model_validate(_read_json(expected_path))
    except ValidationError as exc:
        raise FixtureError(f"{expected_path}: invalid: {exc}") from exc

    if expected.fixture_id != case_dir.name:
        raise FixtureError(
            f"{expected_path}: fixture_id {expected.fixture_id!r} != {case_dir.name!r}"
        )
    if expected.changeset_id != changeset.id:
        raise FixtureError(f"{expected_path}: changeset_id differs from changeset.json")
    if not expected.coverage.snapshot_truncated and (
        expected.coverage.elements_in_changeset != osc_count
    ):
        raise FixtureError(
            f"{case_dir}: expected elements_in_changeset={expected.coverage.elements_in_changeset} "
            f"but download.osc has {osc_count}"
        )

    return FixtureCase(
        name=case_dir.name,
        changeset=changeset,
        discussion=discussion,
        changeset_raw=changeset_raw,
        osc_xml=osc_xml,
        osc_element_count=osc_count,
        prev=prev,
        prev_markers=prev_markers,
        user=user,
        user_marker=user_marker,
        expected=expected,
    )
