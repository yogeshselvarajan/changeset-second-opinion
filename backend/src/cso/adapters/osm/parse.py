"""Safe osmChange parsing and grouping of element versions by (type, id).

Safety: defusedxml with DTDs, entities and external references forbidden, a byte cap
(default 10 MB) and an element cap (default 5,000 raw `<node|way|relation>` entries).
Text is returned as-is; sanitising for display or the model is the evidence renderer's job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import ParseError as _StdParseError

import defusedxml.ElementTree as SafeET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from cso.adapters.osm.errors import (
    ElementCapExceededError,
    ParseError,
    TooLargeError,
    XmlSafetyError,
)
from cso.domain.enums import ChangeAction, OsmType

MAX_OSC_BYTES = 10 * 1024 * 1024
MAX_OSC_ELEMENTS = 5_000
_ACTIONS = {a.value: a for a in ChangeAction}
_TYPES = {t.value: t for t in OsmType}


@dataclass(frozen=True, slots=True)
class OscMember:
    """A relation member."""

    ref_type: OsmType
    ref: int
    role: str


@dataclass(frozen=True, slots=True)
class OscElement:
    """One element version as written in the osmChange (deletions carry no tags or geometry)."""

    osm_type: OsmType
    osm_id: int
    action: ChangeAction
    version: int
    timestamp: datetime | None
    changeset: int | None
    uid: int | None
    user: str | None
    visible: bool
    lat: float | None = None
    lon: float | None = None
    tags: dict[str, str] = field(default_factory=dict)
    nodes: tuple[int, ...] = ()
    members: tuple[OscMember, ...] = ()


@dataclass(frozen=True, slots=True)
class GroupedElement:
    """All versions of one element touched by the changeset.

    `before_version` is first.version - 1 (the prior version to fetch), or None when the first
    version in this changeset is 1 (a creation: nothing to reconstruct). `action` is the action of
    the last entry (an element created then deleted in one changeset reports `delete` with
    before_version None). `after` is the last entry.
    """

    osm_type: OsmType
    osm_id: int
    first: OscElement
    last: OscElement
    before_version: int | None

    @property
    def action(self) -> ChangeAction:
        """Net action: the action of the last entry."""
        return self.last.action

    @property
    def after_version(self) -> int:
        """Version written by the changeset's last edit of this element."""
        return self.last.version

    @property
    def key(self) -> tuple[OsmType, int]:
        """(type, id)."""
        return (self.osm_type, self.osm_id)


@dataclass(frozen=True, slots=True)
class ParsedOsmChange:
    """Result of parse_osm_change.

    `elements` is grouped by (type, id) in order of first appearance. `raw_element_count` counts
    element entries before grouping (what download.osc contains; used for
    coverage.elements_in_changeset). `action_counts` counts raw entries per action.
    """

    elements: tuple[GroupedElement, ...]
    raw_element_count: int
    action_counts: dict[ChangeAction, int]


def _int(el: Element, name: str, *, required: bool = True) -> int | None:
    raw = el.get(name)
    if raw is None:
        if required:
            raise ParseError(f"<{el.tag}> is missing attribute {name!r}")
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ParseError(f"<{el.tag}> attribute {name}={raw!r} is not an integer") from exc


def _float(el: Element, name: str) -> float | None:
    raw = el.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ParseError(f"<{el.tag}> attribute {name}={raw!r} is not a number") from exc


def _timestamp(el: Element) -> datetime | None:
    raw = el.get("timestamp")
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParseError(f"<{el.tag}> has an invalid timestamp {raw!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _element(el: Element, action: ChangeAction) -> OscElement:
    osm_type = _TYPES[el.tag]
    osm_id, version = _int(el, "id"), _int(el, "version")
    if osm_id is None or version is None or osm_id <= 0 or version <= 0:
        raise ParseError(f"<{el.tag}> needs positive id and version")
    tags: dict[str, str] = {}
    nodes: list[int] = []
    members: list[OscMember] = []
    for child in el:
        if child.tag == "tag":
            key = child.get("k")
            if key is None:
                raise ParseError(f"<tag> without k in {el.tag} {osm_id}")
            tags[key] = child.get("v") or ""
        elif child.tag == "nd":
            ref = _int(child, "ref")
            if ref is not None:
                nodes.append(ref)
        elif child.tag == "member":
            member_type = _TYPES.get(child.get("type") or "")
            ref = _int(child, "ref")
            if member_type is None or ref is None:
                raise ParseError(f"invalid <member> in {el.tag} {osm_id}")
            members.append(OscMember(member_type, ref, child.get("role") or ""))
    return OscElement(
        osm_type=osm_type,
        osm_id=osm_id,
        action=action,
        version=version,
        timestamp=_timestamp(el),
        changeset=_int(el, "changeset", required=False),
        uid=_int(el, "uid", required=False),
        user=el.get("user"),
        visible=(el.get("visible") or "true").lower() != "false",
        lat=_float(el, "lat"),
        lon=_float(el, "lon"),
        tags=tags,
        nodes=tuple(nodes),
        members=tuple(members),
    )


def _safe_root(data: bytes | str) -> Element:
    try:
        root: Element = SafeET.fromstring(
            data, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except DefusedXmlException as exc:
        raise XmlSafetyError(f"unsafe XML rejected: {type(exc).__name__}") from exc
    except (_StdParseError, ValueError) as exc:
        raise ParseError(f"malformed osmChange XML: {exc}") from exc
    return root


def parse_osm_change(
    data: bytes | str,
    *,
    max_bytes: int = MAX_OSC_BYTES,
    max_elements: int = MAX_OSC_ELEMENTS,
) -> ParsedOsmChange:
    """Parse and group an osmChange document.

    Raises TooLargeError (bytes), ElementCapExceededError (too many elements; callers set
    coverage.snapshot_truncated), XmlSafetyError (DTD/entities/external references) or ParseError.
    """
    size = len(data.encode("utf-8")) if isinstance(data, str) else len(data)
    if size > max_bytes:
        raise TooLargeError(f"osmChange is {size} bytes (cap {max_bytes})", limit=max_bytes)
    root = _safe_root(data)
    if root.tag != "osmChange":
        raise ParseError(f"root element must be osmChange, got {root.tag!r}")

    total = 0
    for block in root:
        if block.tag not in _ACTIONS:
            raise ParseError(f"unexpected block <{block.tag}> in osmChange")
        total += sum(1 for el in block if el.tag in _TYPES)
        if total > max_elements:  # fail before building any objects
            raise ElementCapExceededError(
                f"osmChange has more than {max_elements} elements", limit=max_elements
            )

    versions: dict[tuple[OsmType, int], dict[int, OscElement]] = {}
    counts = dict.fromkeys(ChangeAction, 0)
    for block in root:
        action = _ACTIONS[block.tag]
        for el in block:
            if el.tag not in _TYPES:
                continue
            parsed = _element(el, action)
            counts[action] += 1
            # a duplicate (type, id, version) keeps the later entry
            versions.setdefault((parsed.osm_type, parsed.osm_id), {})[parsed.version] = parsed

    grouped: list[GroupedElement] = []
    for (osm_type, osm_id), by_version in versions.items():
        first, last = by_version[min(by_version)], by_version[max(by_version)]
        before = first.version - 1 if first.version > 1 else None
        grouped.append(GroupedElement(osm_type, osm_id, first, last, before))
    return ParsedOsmChange(tuple(grouped), total, counts)
