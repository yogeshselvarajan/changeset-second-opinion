#!/usr/bin/env python3
"""Invariant 3: policy-gate inputs are parsed evidence, never model answers.

AST check of `backend/src/cso/domain/policy.py`:
  * it imports nothing from the adapters, agent, jobs, API, persistence or evaluation layers, nor
    from `cso.domain.panel`, `cso.domain.lanes` or `cso.domain.receipt` (where model readings and
    decisions live);
  * `evaluate_rules` takes exactly `(snapshot: EvidenceSnapshot, config: CommunityConfig)`;
  * the rule functions `_r1` to `_r4` and `parsed_facts` take only `snapshot` and `config`, so no
    model output can reach a rule.
The one model-fed helper in the module (`escalation_downgrade_hit`, rule R5) only records a
downgrade that makes a lane more cautious; it is deliberately not part of this signature check.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from common import Finding, rel, run_main

POLICY = Path("backend/src/cso/domain/policy.py")
FORBIDDEN_IMPORTS = (
    "cso.adapters",
    "cso.agent",
    "cso.jobs",
    "cso.api",
    "cso.persistence",
    "cso.evaluation",
    "cso.domain.panel",
    "cso.domain.lanes",
    "cso.domain.receipt",
)
RULE_FUNCTION = re.compile(r"^_r[1-9]\d*$")
EXPECTED_EVALUATE = [("snapshot", "EvidenceSnapshot"), ("config", "CommunityConfig")]


def _annotation(arg: ast.arg) -> str:
    return ast.unparse(arg.annotation) if arg.annotation is not None else ""


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append((node.lineno, node.module))
    return modules


def check(root: Path) -> list[Finding]:
    file = root / POLICY
    path = rel(file, root) if file.exists() else POLICY.as_posix()
    if not file.is_file():
        return [Finding(path, 1, "policy module not found")]
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=path)
    findings: list[Finding] = []
    for line, module in _imported_modules(tree):
        if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_IMPORTS):
            findings.append(Finding(path, line, f"policy imports `{module}`, a model-answer layer"))
    functions = {
        n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    evaluate = functions.get("evaluate_rules")
    if evaluate is None:
        findings.append(Finding(path, 1, "`evaluate_rules` is missing"))
    else:
        actual = [(a.arg, _annotation(a)) for a in evaluate.args.args]
        extras = evaluate.args.kwonlyargs or evaluate.args.vararg or evaluate.args.kwarg
        if actual != EXPECTED_EVALUATE or extras:
            findings.append(
                Finding(
                    path,
                    evaluate.lineno,
                    "`evaluate_rules` must take exactly (snapshot: EvidenceSnapshot, "
                    f"config: CommunityConfig), got {actual}",
                )
            )
    for name, node in functions.items():
        if RULE_FUNCTION.match(name) or name == "parsed_facts":
            params = [a.arg for a in node.args.args]
            if params != ["snapshot", "config"] or node.args.kwonlyargs:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        f"rule function `{name}` may only take (snapshot, config), got {params}",
                    )
                )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("check_policy_inputs", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
