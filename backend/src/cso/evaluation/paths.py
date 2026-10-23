"""Where the evaluation harness keeps its data (repo-root `evaluation/` by default)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVAL_DIR_ENV = "CSO_EVAL_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[4]  # backend/src/cso/evaluation/ -> repo root


@dataclass(frozen=True)
class EvalPaths:
    """Directory layout. Committed: candidates, labels, splits, results. Local only: `.cache`."""

    root: Path

    @classmethod
    def default(cls) -> EvalPaths:
        return cls(Path(os.environ.get(EVAL_DIR_ENV) or (_REPO_ROOT / "evaluation")))

    @property
    def candidates(self) -> Path:
        return self.root / "candidates.jsonl"

    @property
    def labels_dir(self) -> Path:
        return self.root / "labels"

    @property
    def splits_dir(self) -> Path:
        return self.root / "splits"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def snapshot_cache(self) -> Path:
        """Raw evidence snapshots (contain mapper names); git-ignored via evaluation/.gitignore."""
        return self.root / ".cache" / "snapshots"

    def labels(self, set_name: str) -> Path:
        return self.labels_dir / f"{set_name}.jsonl"

    def adjudicated(self, set_name: str) -> Path:
        return self.labels_dir / f"{set_name}.adjudicated.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """All JSON objects of a JSON-lines file ([] if the file does not exist)."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rows (never rewrites existing lines); always LF line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_text_lf(path: Path, text: str) -> None:
    """Write text with LF endings, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def iter_ids(path: Path) -> Iterator[int]:
    """Integer ids, one per line, from a text file."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield int(line)
