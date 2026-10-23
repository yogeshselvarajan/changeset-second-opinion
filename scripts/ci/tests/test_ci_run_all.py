from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import run_all

Write = Callable[[str, str], Path]


def test_all_checks_pass_on_the_real_repository(repo_root: Path) -> None:
    assert run_all.main(["--root", str(repo_root)]) == 0


def test_run_all_fails_when_any_check_fails(tmp_path: Path, write: Write) -> None:
    write(
        "backend/src/cso/domain/policy.py",
        "def evaluate_rules(snapshot, config):\n    pass\n",
    )
    write("web/src/a.ts", "// spam\n")
    assert run_all.main(["--root", str(tmp_path)]) == 1
