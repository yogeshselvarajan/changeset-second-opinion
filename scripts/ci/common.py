"""Shared helpers for the CI invariant checks (standard library only).

Each check exposes `check(root: Path) -> list[Finding]` and a `main()` that prints one line per
finding as `path:line: message` and exits 1 when there is any. `root` is the repository root, so
tests can point a check at a temporary tree with a planted violation.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules", ".venv", "dist", ".git", ".mypy_cache"})


@dataclass(frozen=True)
class Finding:
    """One violation: where it is and what rule it breaks."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def default_root() -> Path:
    """The repository root (two levels above `scripts/ci/`)."""
    return Path(__file__).resolve().parents[2]


def iter_files(
    base: Path, suffixes: Sequence[str], skip_dirs: Sequence[str] = ()
) -> Iterator[Path]:
    """Files under `base` with one of `suffixes`, skipping build, cache and listed directories."""
    if not base.is_dir():
        return
    skip = SKIP_DIR_NAMES | set(skip_dirs)
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in skip for part in path.relative_to(base).parts[:-1]):
            continue
        yield path


def rel(path: Path, root: Path) -> str:
    """A stable, forward-slash path relative to `root` for messages."""
    return path.relative_to(root).as_posix()


def run_main(name: str, check: Callable[[Path], list[Finding]], argv: Sequence[str]) -> int:
    """Shared entry point: `--root DIR` selects the tree; prints findings; returns the exit code."""
    root = default_root()
    args = list(argv)
    if "--root" in args:
        idx = args.index("--root")
        root = Path(args[idx + 1]).resolve()
    findings = check(root)
    for finding in findings:
        print(finding)
    if findings:
        print(f"{name}: FAILED with {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print(f"{name}: ok")
    return 0
