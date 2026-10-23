"""Fixture recorder: runs `collect` against a source and writes a replayable, anonymized case.

The recorder wraps the source, captures every response and failure `collect` triggers, then writes
the layout of backend/fixtures/schema.md so `ReplayClient(out)` reproduces the same coverage:
403 -> `__403__` marker, timeout or other provider failure -> `__timeout__` marker, 404 -> absence.
Versions returned by a history fallback or age lookup are written as ordinary `prev/` data files.

Anonymization (people and personal text, not map data): every display name becomes `mapper_A`,
`mapper_B`, ... and every uid a fake id (900000001, ...), consistently across changeset, comments,
osmChange, element versions and the user profile; emails and URLs in changeset tags and discussion
text are replaced by `[email removed]` / `[url removed]`; user profiles are cut down to the fields
the evidence uses. Changeset and element ids are real; record only changesets you may redistribute
under ODbL (backend/fixtures/README.md).

Known limit: a history call that timed out is recorded as a redacted gap (schema has no marker for
it), so replay of that element reports `redacted`, not `timeout`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import unescape

from cso.adapters.osm.collect import CollectBudget, collect
from cso.adapters.osm.errors import NotFoundError, OsmError, OsmTimeoutError, Redacted403
from cso.adapters.osm.protocol import OsmSource
from cso.domain.enums import OsmType
from cso.domain.fixtures import ExpectedOutcome, FixtureError, Marker, load_case
from cso.domain.models import EvidenceSnapshot

SYNTHETIC_UID_BASE = 900_000_000
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_XML_USER = re.compile(r' user="([^"]*)"')
_XML_UID = re.compile(r' uid="(\d+)"')
_ENVELOPE_KEYS = ("version", "copyright", "attribution", "license")


class RecordError(ValueError):
    """The recording could not be written (for example the target directory is not empty)."""


class Anonymizer:
    """Stable pseudonyms for display names and uids."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._uids: dict[int, int] = {}

    @staticmethod
    def _label(index: int) -> str:
        label = ""
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            label = chr(ord("A") + rem) + label
        return label

    def name(self, display_name: str | None) -> str | None:
        """Pseudonym for a display name (None stays None)."""
        if display_name is None:
            return None
        if display_name not in self._names:
            self._names[display_name] = f"mapper_{self._label(len(self._names))}"
        return self._names[display_name]

    def uid(self, uid: int | None) -> int | None:
        """Fake uid for a real uid (None stays None)."""
        if uid is None:
            return None
        if uid not in self._uids:
            self._uids[uid] = SYNTHETIC_UID_BASE + 1 + len(self._uids)
        return self._uids[uid]

    def scrub_text(self, text: str) -> str:
        """Remove emails and URLs from free text."""
        return _URL.sub("[url removed]", _EMAIL.sub("[email removed]", text))


class _Recorder:
    """OsmSource wrapper that remembers everything the collector asked for."""

    def __init__(self, inner: OsmSource) -> None:
        self._inner = inner
        self.changeset: dict[str, Any] | None = None
        self.osc: bytes | None = None
        self.versions: dict[tuple[OsmType, int, int], dict[str, Any] | Marker] = {}
        self.histories: dict[tuple[OsmType, int], list[dict[str, Any]]] = {}
        self.user: dict[str, Any] | Marker | None = None

    @property
    def calls(self) -> int:
        return self._inner.calls

    @calls.setter
    def calls(self, value: int) -> None:  # protocol declares a settable attribute
        raise AttributeError("calls is owned by the wrapped source")

    async def get_changeset(self, changeset_id: int) -> dict[str, Any]:
        self.changeset = await self._inner.get_changeset(changeset_id)
        return self.changeset

    async def get_osc(self, changeset_id: int) -> bytes:
        self.osc = await self._inner.get_osc(changeset_id)
        return self.osc

    async def get_element_version(
        self, osm_type: OsmType, osm_id: int, version: int
    ) -> dict[str, Any]:
        key = (osm_type, osm_id, version)
        try:
            found = await self._inner.get_element_version(osm_type, osm_id, version)
        except Redacted403:
            self.versions[key] = Marker.FORBIDDEN
            raise
        except NotFoundError:
            raise  # absence replays as not found
        except OsmError:
            self.versions[key] = Marker.TIMEOUT
            raise
        self.versions[key] = found
        return found

    async def get_element_history(self, osm_type: OsmType, osm_id: int) -> list[dict[str, Any]]:
        found = await self._inner.get_element_history(osm_type, osm_id)
        self.histories[(osm_type, osm_id)] = found
        return found

    async def get_elements(
        self, osm_type: OsmType, osm_ids: Sequence[int]
    ) -> dict[int, dict[str, Any]]:
        return await self._inner.get_elements(osm_type, osm_ids)

    async def get_user(self, uid: int) -> dict[str, Any]:
        try:
            self.user = await self._inner.get_user(uid)
        except Redacted403:
            self.user = Marker.FORBIDDEN
            raise
        except OsmTimeoutError:
            self.user = Marker.TIMEOUT
            raise
        except OsmError:
            self.user = Marker.TIMEOUT
            raise
        return self.user


@dataclass(frozen=True, slots=True)
class RecordResult:
    """What was recorded: the snapshot collect produced and where the case was written."""

    snapshot: EvidenceSnapshot
    out: Path
    files: list[str]


def _dump(data: object) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")


def _envelope(raw: dict[str, Any]) -> dict[str, Any]:
    return {"generator": "cso record", **{k: raw[k] for k in _ENVELOPE_KEYS if k in raw}}


def _anonymize_changeset(raw: dict[str, Any], anon: Anonymizer) -> dict[str, Any]:
    cs = dict(raw["changeset"])
    cs["user"] = anon.name(cs.get("user")) if "user" in cs else None
    cs["uid"] = anon.uid(cs.get("uid")) if "uid" in cs else None
    if cs["user"] is None:
        cs.pop("user", None)
    if cs["uid"] is None:
        cs.pop("uid", None)
    cs["tags"] = {k: anon.scrub_text(str(v)) for k, v in (cs.get("tags") or {}).items()}
    comments = []
    for item in cs.get("comments") or []:
        if item.get("visible", True) is False:
            continue  # moderated comments are not redistributed
        comment = dict(item)
        comment["user"] = anon.name(item.get("user"))
        comment["uid"] = anon.uid(item.get("uid"))
        comment["text"] = anon.scrub_text(str(item.get("text") or ""))
        comments.append({k: v for k, v in comment.items() if v is not None})
    cs["comments"] = comments
    return {**_envelope(raw), "changeset": cs}


def _anonymize_osc(osc: bytes, anon: Anonymizer) -> bytes:
    text = osc.decode("utf-8")
    text = _XML_USER.sub(lambda m: f' user="{anon.name(unescape(m.group(1)))}"', text)
    text = _XML_UID.sub(lambda m: f' uid="{anon.uid(int(m.group(1)))}"', text)
    return text.encode("utf-8")


def _anonymize_element(element: dict[str, Any], anon: Anonymizer) -> dict[str, Any]:
    result = dict(element)
    if "user" in result:
        result["user"] = anon.name(result["user"])
    if "uid" in result:
        result["uid"] = anon.uid(result["uid"])
    return result


def _anonymize_user(raw: dict[str, Any], anon: Anonymizer) -> dict[str, Any]:
    user = raw.get("user") or {}
    received = (user.get("blocks") or {}).get("received") or {}
    return {
        **_envelope(raw),
        "user": {
            "id": anon.uid(user.get("id")),
            "display_name": anon.name(user.get("display_name")),
            "account_created": user.get("account_created"),
            "changesets": {"count": (user.get("changesets") or {}).get("count")},
            "blocks": {
                "received": {"count": received.get("count"), "active": received.get("active")}
            },
        },
    }


def _check_target(out: Path) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise RecordError(f"{out}: refusing to write into an existing non-empty path")


async def record_case(
    source: OsmSource,
    changeset_id: int,
    out: Path,
    *,
    budget: CollectBudget | None = None,
) -> RecordResult:
    """Collect a changeset and write an anonymized fixture directory at `out` (must be empty/new).

    Raises RecordError if `out` is not empty, OsmError subclasses for fatal fetch failures, and
    FixtureError if the written case does not validate (a recorder bug; files stay in place).
    """
    out = Path(out)
    _check_target(out)
    recorder = _Recorder(source)
    snapshot = await collect(recorder, changeset_id, budget)
    if recorder.changeset is None or recorder.osc is None:
        raise RecordError("changeset or osmChange was not fetched")  # collect would have raised

    anon = Anonymizer()
    files: dict[str, bytes] = {}
    changeset_json = _anonymize_changeset(recorder.changeset, anon)
    files["changeset.json"] = _dump(changeset_json)
    files["download.osc"] = _anonymize_osc(recorder.osc, anon)

    envelope = _envelope(recorder.changeset)
    written: dict[tuple[OsmType, int, int], dict[str, Any]] = {}
    for (osm_type, osm_id, version), found in sorted(
        recorder.versions.items(), key=lambda kv: (kv[0][0].value, kv[0][1], kv[0][2])
    ):
        stem = f"prev/{osm_type.value}_{osm_id}_{version}"
        if isinstance(found, Marker):
            files[f"{stem}.{found.value}"] = b""
        else:
            written[(osm_type, osm_id, version)] = found
    marked = {k for k, v in recorder.versions.items() if isinstance(v, Marker)}
    for (osm_type, osm_id), history in sorted(
        recorder.histories.items(), key=lambda kv: (kv[0][0].value, kv[0][1])
    ):
        for element in history:
            if element.get("version") is None:
                continue
            key = (osm_type, osm_id, int(element["version"]))
            if key not in written and key not in marked:
                written[key] = element
    for (osm_type, osm_id, version), element in sorted(
        written.items(), key=lambda kv: (kv[0][0].value, kv[0][1], kv[0][2])
    ):
        payload = {**envelope, "elements": [_anonymize_element(element, anon)]}
        files[f"prev/{osm_type.value}_{osm_id}_{version}.json"] = _dump(payload)

    if isinstance(recorder.user, dict):
        files["user.json"] = _dump(_anonymize_user(recorder.user, anon))
    else:  # failed fetch, or no author id to look up: schema needs one of the two markers
        marker = recorder.user if isinstance(recorder.user, Marker) else Marker.FORBIDDEN
        files[f"user.{marker.value}"] = b""

    expected = ExpectedOutcome(
        fixture_id=out.name,
        description=f"Recorded from changeset {changeset_id}; review before committing",
        changeset_id=changeset_id,
        coverage=snapshot.coverage,
        flags=snapshot.flags,
        rules=[],
        notes="Recorded by `cso record`; rules and the expected conclusion are left for a human.",
    )
    files["expected.json"] = _dump(expected.model_dump(mode="json"))

    for rel, data in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    try:
        load_case(out)
    except FixtureError as exc:
        raise FixtureError(f"recorded case does not validate: {exc}") from exc
    return RecordResult(snapshot=snapshot, out=out, files=sorted(files))
