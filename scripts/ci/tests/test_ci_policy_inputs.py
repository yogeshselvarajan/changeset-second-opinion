from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_policy_inputs as check

Write = Callable[[str, str], Path]
POLICY = "backend/src/cso/domain/policy.py"
GOOD = (
    "from cso.domain.config import CommunityConfig\n"
    "from cso.domain.models import EvidenceSnapshot, RuleHit\n"
    "def _r1(snapshot, config):\n    return None\n"
    "def _r4(snapshot, config):\n    return None\n"
    "def evaluate_rules(snapshot: EvidenceSnapshot, config: CommunityConfig) -> list[RuleHit]:\n"
    "    return []\n"
    "def parsed_facts(snapshot, config):\n    return None\n"
    "def escalation_downgrade_hit(config, *, damage_probability, original, downgraded_to):\n"
    "    return None\n"
)


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_a_clean_policy_module_passes(tmp_path: Path, write: Write) -> None:
    write(POLICY, GOOD)
    assert messages(tmp_path) == []


def test_importing_a_model_answer_layer_is_flagged(tmp_path: Path, write: Write) -> None:
    for module in (
        "cso.domain.panel",
        "cso.adapters.decider",
        "cso.domain.receipt",
        "cso.jobs",
    ):
        write(POLICY, f"from {module} import X\n" + GOOD)
        assert any(f"imports `{module}`" in m for m in messages(tmp_path)), module


def test_an_extra_parameter_on_evaluate_rules_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        POLICY,
        GOOD.replace(
            "def evaluate_rules(snapshot: EvidenceSnapshot, config: CommunityConfig)",
            "def evaluate_rules(snapshot: EvidenceSnapshot, config: CommunityConfig, panel)",
        ),
    )
    assert any("evaluate_rules" in m for m in messages(tmp_path))


def test_a_changed_annotation_on_evaluate_rules_is_flagged(tmp_path: Path, write: Write) -> None:
    write(POLICY, GOOD.replace("snapshot: EvidenceSnapshot", "snapshot: PanelReadings"))
    assert any("evaluate_rules" in m for m in messages(tmp_path))


def test_a_rule_function_taking_model_output_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        POLICY,
        GOOD.replace("def _r4(snapshot, config)", "def _r4(snapshot, config, readings)"),
    )
    found = messages(tmp_path)
    assert any("`_r4`" in m for m in found)


def test_parsed_facts_may_not_take_model_output(tmp_path: Path, write: Write) -> None:
    write(
        POLICY,
        GOOD.replace("def parsed_facts(snapshot, config)", "def parsed_facts(panel)"),
    )
    assert any("parsed_facts" in m for m in messages(tmp_path))


def test_a_missing_policy_module_is_reported(tmp_path: Path) -> None:
    assert any("policy module not found" in m for m in messages(tmp_path))


def test_a_missing_evaluate_rules_is_reported(tmp_path: Path, write: Write) -> None:
    write(POLICY, "def helper(snapshot, config):\n    return None\n")
    assert any("`evaluate_rules` is missing" in m for m in messages(tmp_path))
