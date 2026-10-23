from __future__ import annotations

import json

import pytest

from calibrated_action_gate import ChoiceSpec, NoulSpec, RequestPlan, build_request, rotations


@pytest.mark.parametrize("n", [2, 3, 4, 5, 7])
def test_rotations_put_every_option_in_a_different_position(n: int) -> None:
    options = [f"o{i}" for i in range(n)]
    k = min(3, n)
    orders = rotations(options, k)
    assert len(orders) == k
    assert orders[0] == options
    for option in options:
        positions = [o.index(option) for o in orders]
        assert len(set(positions)) == k
    assert all(sorted(o) == sorted(options) for o in orders)


def test_rotations_reject_bad_input() -> None:
    with pytest.raises(ValueError):
        rotations(["only"], 1)
    with pytest.raises(ValueError):
        rotations(["a", "b"], 3)
    with pytest.raises(ValueError):
        rotations(["a", "b", "c"], 0)


def test_request_shape_matches_the_recorded_request(
    plan: RequestPlan, recorded_request: dict
) -> None:
    assert plan.request == recorded_request
    names = list(plan.request["questions"])
    assert names == [
        "nature_p0",
        "nature_p1",
        "nature_p2",
        "response_p0",
        "response_p1",
        "response_p2",
        "comment_matches_changes",
        "mature_feature_deleted_probe",
    ]
    assert plan.groups["nature"] == ("nature_p0", "nature_p1", "nature_p2")
    assert plan.nouls == ("comment_matches_changes", "mature_feature_deleted_probe")


def test_option_order_is_carried_by_criteria_key_order(plan: RequestPlan) -> None:
    q = plan.request["questions"]
    for name, order in plan.orders.items():
        assert tuple(q[name]["criteria"]) == order
    assert len({plan.orders[n] for n in plan.groups["nature"]}) == 3


def test_state_never_leaks_into_questions_and_hash_ignores_state() -> None:
    choices = [ChoiceSpec("q", "Pick one.", {"a": "first", "b": "second", "c": "third"})]
    one = build_request("state ONE", choices, [NoulSpec("n", "True?")])
    two = build_request("state TWO", choices, [NoulSpec("n", "True?")])
    assert "state ONE" not in json.dumps(one.request["questions"])
    assert one.questions_hash == two.questions_hash
    changed = build_request("s", [ChoiceSpec("q", "Pick one.", {"a": "x", "b": "y", "c": "z"})])
    assert changed.questions_hash != one.questions_hash
    assert one.questions_hash.startswith("sha256:")


def test_option_order_changes_the_hash() -> None:
    a = build_request("s", [ChoiceSpec("q", "i", {"a": "1", "b": "2"})], permutations=1)
    b = build_request("s", [ChoiceSpec("q", "i", {"b": "2", "a": "1"})], permutations=1)
    assert a.questions_hash != b.questions_hash


def test_duplicate_question_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_request(
            "s", [ChoiceSpec("q", "i", {"a": "1", "b": "2", "c": "3"})], [NoulSpec("q_p0", "t")]
        )
