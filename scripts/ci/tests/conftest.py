"""Make the check scripts importable and give tests a tiny repo-tree builder."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def write(tmp_path: Path) -> Callable[[str, str], Path]:
    """Create `relative/path` under a temporary repo root with the given text."""

    def _write(relative: str, text: str) -> Path:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    return _write
