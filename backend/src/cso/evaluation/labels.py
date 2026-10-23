"""Hand labels: append-only rows per labeller session, plus the adjudication merge.

Labels are immutable rows; a correction is a new row and the latest row per
(labeller, session, changeset) is the effective one. Nothing here imports the Decider: labellers
see rendered evidence only, never model output.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cso.domain.enums import Nature, Response
from cso.domain.panel import PANEL_NOUL_IDS
from cso.evaluation.paths import append_jsonl, read_jsonl
from cso.evaluation.stats import cohen_kappa

AMBIGUOUS = "ambiguous"
NATURE_LABELS: tuple[str, ...] = (*(n.value for n in Nature), AMBIGUOUS)
RESPONSE_LABELS: tuple[str, ...] = (*(r.value for r in Response), AMBIGUOUS)

# Label schema version 2 (fact panel, ADR-009): nature plus yes/no/unknown per composed probe, in
# one pass. `deleted_own_recent_additions` is not labelled yet: the cached evidence snapshots
# predate `ChangedObject.created_by_uid`, so the evidence shown cannot answer it. Re-collect the
# candidates (network) and drop it from UNLABELLED_PROBES to label it. Version 1 rows (nature and
# response, no probes) still load and are never rewritten.
LABEL_VERSION = 2
PROBE_LABELS: tuple[str, ...] = ("yes", "no", "unknown")
NOT_COLLECTED = "not_collected"
UNLABELLED_PROBES: frozenset[str] = frozenset({"deleted_own_recent_additions"})
LABELLED_PROBES: tuple[str, ...] = tuple(i for i in PANEL_NOUL_IDS if i not in UNLABELLED_PROBES)


class LabelError(ValueError):
    """An invalid label or label request."""


@dataclass(frozen=True)
class LabelRow:
    """One labeller's answer for one changeset in one session."""

    set_name: str
    changeset_id: int
    labeller: str
    session: str
    nature: str
    response: str
    ts: str
    version: int = 1
    probes: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "set": self.set_name,
            "changeset_id": self.changeset_id,
            "labeller": self.labeller,
            "session": self.session,
            "nature": self.nature,
            "response": self.response,
            "ts": self.ts,
        }
        if self.version >= 2:
            raw["version"] = self.version
            raw["probes"] = dict(self.probes)
        return raw

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> LabelRow:
        return cls(
            set_name=raw["set"],
            changeset_id=int(raw["changeset_id"]),
            labeller=raw["labeller"],
            session=raw["session"],
            nature=raw["nature"],
            response=raw["response"],
            ts=raw["ts"],
            version=int(raw.get("version", 1)),
            probes=dict(raw.get("probes", {})),
        )


def validate_labels(nature: str, response: str) -> None:
    """Raise `LabelError` unless both labels are from the rubric (`ambiguous` allowed)."""
    if nature not in NATURE_LABELS:
        raise LabelError(f"unknown nature label {nature!r}")
    if response not in RESPONSE_LABELS:
        raise LabelError(f"unknown response label {response!r}")


def validate_probes(probes: Mapping[str, str]) -> None:
    """Raise `LabelError` unless every labelled probe has a yes, no or unknown answer."""
    if set(probes) != set(LABELLED_PROBES):
        raise LabelError(f"probe labels must cover exactly {sorted(LABELLED_PROBES)}")
    for probe_id, answer in probes.items():
        if answer not in PROBE_LABELS:
            raise LabelError(f"probe {probe_id}: unknown answer {answer!r}")


def session_order(ids: Sequence[int], session: str) -> list[int]:
    """Deterministic per-session shuffle (so two sessions see different orders)."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"{session}:{i}".encode()).hexdigest())


class LabelStore:
    """Append-only JSONL store of `LabelRow`s for one set."""

    def __init__(self, path: Path, set_name: str) -> None:
        self.path = path
        self.set_name = set_name

    def rows(self) -> list[LabelRow]:
        return [LabelRow.from_json(r) for r in read_jsonl(self.path)]

    def append(
        self,
        *,
        changeset_id: int,
        labeller: str,
        session: str,
        nature: str,
        response: str = NOT_COLLECTED,
        probes: Mapping[str, str] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> LabelRow:
        """Append one label row; existing rows are never modified.

        With `probes` the row is schema version 2 (nature and probes, response not collected);
        without, it is a version 1 row that needs a rubric response.
        """
        if probes is None:
            validate_labels(nature, response)
        else:
            if nature not in NATURE_LABELS:
                raise LabelError(f"unknown nature label {nature!r}")
            validate_probes(probes)
            response = NOT_COLLECTED
        if not labeller.strip() or not session.strip():
            raise LabelError("labeller and session are required")
        row = LabelRow(
            self.set_name,
            changeset_id,
            labeller,
            session,
            nature,
            response,
            now().isoformat(timespec="seconds"),
            version=LABEL_VERSION if probes is not None else 1,
            probes=dict(probes) if probes is not None else {},
        )
        append_jsonl(self.path, [row.to_json()])
        return row

    def effective(self, labeller: str, session: str) -> dict[int, LabelRow]:
        """Latest row per changeset for one labeller session."""
        latest: dict[int, LabelRow] = {}
        for row in self.rows():
            if row.labeller == labeller and row.session == session:
                latest[row.changeset_id] = row
        return latest

    def sessions(self) -> list[tuple[str, str]]:
        """Distinct (labeller, session) pairs, in first-seen order."""
        seen: list[tuple[str, str]] = []
        for row in self.rows():
            key = (row.labeller, row.session)
            if key not in seen:
                seen.append(key)
        return seen


@dataclass(frozen=True)
class GoldLabel:
    """An adjudicated label. `ambiguous` items are excluded from accuracy and reported as a rate."""

    set_name: str
    changeset_id: int
    nature: str
    response: str
    method: str  # "agree" or "adjudicated"
    adjudicator: str | None
    ts: str
    version: int = 1
    probes: Mapping[str, str] = field(default_factory=dict)

    @property
    def ambiguous(self) -> bool:
        return self.nature == AMBIGUOUS

    def to_json(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "set": self.set_name,
            "changeset_id": self.changeset_id,
            "nature": self.nature,
            "response": self.response,
            "method": self.method,
            "adjudicator": self.adjudicator,
            "ts": self.ts,
        }
        if self.version >= 2:
            raw["version"] = self.version
            raw["probes"] = dict(self.probes)
        return raw

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> GoldLabel:
        return cls(
            set_name=raw["set"],
            changeset_id=int(raw["changeset_id"]),
            nature=raw["nature"],
            response=raw["response"],
            method=raw["method"],
            adjudicator=raw.get("adjudicator"),
            ts=raw["ts"],
            version=int(raw.get("version", 1)),
            probes=dict(raw.get("probes", {})),
        )


@dataclass(frozen=True)
class Agreement:
    """How two sessions agreed before adjudication."""

    items: int
    nature_agree: int
    response_agree: int
    nature_kappa: float | None
    response_kappa: float | None
    probe_agree: Mapping[str, int] = field(default_factory=dict)  # version 2 items only
    probe_items: int = 0


Decide = Callable[[int, LabelRow, LabelRow], tuple[str, str]]
DecideProbes = Callable[[int, LabelRow, LabelRow], tuple[str, dict[str, str]]]


def _gold_v2(
    store: LabelStore,
    changeset_id: int,
    nature: str,
    probes: Mapping[str, str],
    method: str,
    adjudicator: str | None,
    stamp: str,
) -> GoldLabel:
    return GoldLabel(
        store.set_name,
        changeset_id,
        nature,
        NOT_COLLECTED,
        method,
        adjudicator,
        stamp,
        version=LABEL_VERSION,
        probes=dict(probes),
    )


def adjudicate(
    store: LabelStore,
    *,
    session_a: tuple[str, str],
    session_b: tuple[str, str],
    decide: Decide,
    adjudicator: str,
    decide_probes: DecideProbes | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[list[GoldLabel], Agreement]:
    """Merge two sessions: agreeing items pass through, others go to `decide(cs, a, b)`.

    Only items labelled in both sessions are merged. Version 2 rows (probes) agree when nature
    and every probe match; disagreements go to `decide_probes`, which is required for them.
    Returns the new gold rows (not yet written) and the pre-adjudication agreement statistics.
    """
    a_rows = store.effective(*session_a)
    b_rows = store.effective(*session_b)
    common = sorted(set(a_rows) & set(b_rows))
    stamp = now().isoformat(timespec="seconds")
    gold: list[GoldLabel] = []
    probe_agree = dict.fromkeys(LABELLED_PROBES, 0)
    probe_items = 0
    for cs in common:
        a, b = a_rows[cs], b_rows[cs]
        if a.version >= 2 and b.version >= 2:
            probe_items += 1
            for probe_id in LABELLED_PROBES:
                if a.probes.get(probe_id) == b.probes.get(probe_id):
                    probe_agree[probe_id] += 1
            if a.nature == b.nature and dict(a.probes) == dict(b.probes):
                gold.append(_gold_v2(store, cs, a.nature, a.probes, "agree", None, stamp))
                continue
            if decide_probes is None:
                raise LabelError("version 2 labels disagree and no probe adjudication was given")
            nature, probes = decide_probes(cs, a, b)
            if nature not in NATURE_LABELS:
                raise LabelError(f"unknown nature label {nature!r}")
            validate_probes(probes)
            gold.append(_gold_v2(store, cs, nature, probes, "adjudicated", adjudicator, stamp))
            continue
        if (a.nature, a.response) == (b.nature, b.response):
            gold.append(GoldLabel(store.set_name, cs, a.nature, a.response, "agree", None, stamp))
            continue
        nature, response = decide(cs, a, b)
        validate_labels(nature, response)
        gold.append(
            GoldLabel(store.set_name, cs, nature, response, "adjudicated", adjudicator, stamp)
        )
    natures_a = [a_rows[c].nature for c in common]
    natures_b = [b_rows[c].nature for c in common]
    responses_a = [a_rows[c].response for c in common]
    responses_b = [b_rows[c].response for c in common]
    agreement = Agreement(
        probe_agree=probe_agree,
        probe_items=probe_items,
        items=len(common),
        nature_agree=sum(1 for x, y in zip(natures_a, natures_b, strict=True) if x == y),
        response_agree=sum(1 for x, y in zip(responses_a, responses_b, strict=True) if x == y),
        nature_kappa=cohen_kappa(natures_a, natures_b),
        response_kappa=cohen_kappa(responses_a, responses_b),
    )
    return gold, agreement


def write_gold(path: Path, gold: Sequence[GoldLabel]) -> None:
    """Append adjudicated rows (a re-adjudication is a new row; the latest wins on load)."""
    append_jsonl(path, [g.to_json() for g in gold])


def load_gold(path: Path) -> dict[int, GoldLabel]:
    """Effective adjudicated label per changeset (latest row wins)."""
    latest: dict[int, GoldLabel] = {}
    for raw in read_jsonl(path):
        gold = GoldLabel.from_json(raw)
        latest[gold.changeset_id] = gold
    return latest
