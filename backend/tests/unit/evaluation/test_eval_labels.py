from __future__ import annotations

from pathlib import Path

import pytest

from cso.evaluation.labels import (
    AMBIGUOUS,
    LabelError,
    LabelRow,
    LabelStore,
    adjudicate,
    load_gold,
    session_order,
    write_gold,
)


def _store(tmp_path: Path) -> LabelStore:
    return LabelStore(tmp_path / "labels" / "dev.jsonl", "dev")


def test_labels_are_appended_and_existing_lines_never_change(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(
        changeset_id=1,
        labeller="a",
        session="s1",
        nature="consistent_edit",
        response="no_action_suggested",
    )
    before = store.path.read_bytes()
    store.append(changeset_id=2, labeller="a", session="s1", nature=AMBIGUOUS, response=AMBIGUOUS)
    after = store.path.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)
    assert b"\r" not in after


def test_a_correction_is_a_new_row_and_the_latest_is_effective(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(
        changeset_id=1,
        labeller="a",
        session="s1",
        nature="consistent_edit",
        response="no_action_suggested",
    )
    store.append(
        changeset_id=1,
        labeller="a",
        session="s1",
        nature="possible_deliberate_damage",
        response="escalate_to_experienced_reviewer",
    )
    assert len(store.rows()) == 2  # both rows are kept
    effective = store.effective("a", "s1")
    assert effective[1].nature == "possible_deliberate_damage"


def test_invalid_labels_and_missing_identity_are_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LabelError):
        store.append(changeset_id=1, labeller="a", session="s", nature="vandal", response=AMBIGUOUS)
    with pytest.raises(LabelError):
        store.append(
            changeset_id=1, labeller="a", session="s", nature=AMBIGUOUS, response="stop_everything"
        )
    with pytest.raises(LabelError):
        store.append(
            changeset_id=1, labeller=" ", session="s", nature=AMBIGUOUS, response=AMBIGUOUS
        )
    assert not store.path.exists()


def test_session_order_is_deterministic_and_differs_between_sessions() -> None:
    ids = list(range(1, 41))
    assert session_order(ids, "s1") == session_order(ids, "s1")
    assert session_order(ids, "s1") != session_order(ids, "s2")
    assert sorted(session_order(ids, "s1")) == ids


def _label(store: LabelStore, session: str, cs: int, nature: str, response: str) -> None:
    store.append(changeset_id=cs, labeller="me", session=session, nature=nature, response=response)


def test_adjudicate_passes_agreements_and_asks_about_disagreements(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for cs, na, ra, nb, rb in [
        (1, "consistent_edit", "no_action_suggested", "consistent_edit", "no_action_suggested"),
        (2, "consistent_edit", "welcome_and_tips", "likely_good_faith_mistake", "welcome_and_tips"),
        (3, AMBIGUOUS, AMBIGUOUS, AMBIGUOUS, AMBIGUOUS),
        (
            4,
            "needs_local_knowledge",
            "request_local_check",
            "needs_local_knowledge",
            "request_local_check",
        ),
    ]:
        _label(store, "s1", cs, na, ra)
        _label(store, "s2", cs, nb, rb)
    _label(store, "s1", 99, "consistent_edit", "no_action_suggested")  # only in one session
    asked: list[int] = []

    def decide(cs: int, a: LabelRow, b: LabelRow) -> tuple[str, str]:
        asked.append(cs)
        return b.nature, b.response

    gold, agreement = adjudicate(
        store, session_a=("me", "s1"), session_b=("me", "s2"), decide=decide, adjudicator="adj"
    )
    assert asked == [2]
    by_cs = {g.changeset_id: g for g in gold}
    assert sorted(by_cs) == [1, 2, 3, 4]  # 99 is not in both sessions
    assert by_cs[1].method == "agree" and by_cs[1].adjudicator is None
    assert by_cs[2].method == "adjudicated" and by_cs[2].nature == "likely_good_faith_mistake"
    assert by_cs[3].ambiguous
    assert (agreement.items, agreement.nature_agree, agreement.response_agree) == (4, 3, 4)
    assert agreement.nature_kappa is not None and agreement.nature_kappa < 1.0


def test_gold_is_append_only_and_latest_row_wins(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _label(store, "s1", 1, "consistent_edit", "no_action_suggested")
    _label(store, "s2", 1, "consistent_edit", "no_action_suggested")
    gold, _ = adjudicate(
        store,
        session_a=("me", "s1"),
        session_b=("me", "s2"),
        decide=lambda *_: (AMBIGUOUS, AMBIGUOUS),
        adjudicator="adj",
    )
    path = tmp_path / "labels" / "dev.adjudicated.jsonl"
    write_gold(path, gold)
    first = path.read_bytes()
    _label(store, "s1", 1, "needs_local_knowledge", "request_local_check")
    gold2, _ = adjudicate(
        store,
        session_a=("me", "s1"),
        session_b=("me", "s2"),
        decide=lambda *_: ("needs_local_knowledge", "request_local_check"),
        adjudicator="adj",
    )
    write_gold(path, gold2)
    assert path.read_bytes().startswith(first)  # appended, not rewritten
    assert load_gold(path)[1].nature == "needs_local_knowledge"
