#!/usr/bin/env python3
"""No em dash (U+2014) or en dash (U+2013) in the files people read.

Scans `*.md`, `*.mdx` (so the user docs under `site/src/content/docs`), `*.yaml`, `*.yml`,
`*.txt`, `*.html`, `*.svg`, `*.webmanifest`, the TypeScript in
`web/src`, the Python in `backend/src` and everything under `config/` and `web/public`. In a git
checkout only tracked files are read, so ignored and local-only files cannot fail the check.
Allow-listed: `evaluation/labels/` and `evaluation/results/`, which quote OpenStreetMap text and
generated reports verbatim.

Use a comma, a colon or a full stop instead. A hyphen-minus is fine.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from common import SKIP_DIR_NAMES, Finding, rel, run_main

DASHES = {"—": "em dash (U+2014)", "–": "en dash (U+2013)"}
ALLOWED_PREFIXES = ("evaluation/labels/", "evaluation/results/")
SUFFIXES = frozenset({".md", ".mdx", ".yaml", ".yml", ".txt", ".html", ".svg", ".webmanifest"})
SOURCE_RULES = (
    ("web/src/", frozenset({".ts", ".tsx", ".css", ".json"})),
    ("backend/src/", frozenset({".py"})),
    ("config/", None),  # every file
    ("web/public/", None),
)
MAX_BYTES = 2 * 1024 * 1024


def _tracked(root: Path) -> list[str] | None:
    """Tracked paths in a git checkout, or None when `root` is not one."""
    try:
        out = subprocess.run(  # noqa: S603 (fixed argv)
            ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    if not (root / ".git").exists():
        return None
    return [p for p in out.decode("utf-8").split("\0") if p]


def _walk(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if path.is_file() and not any(part in SKIP_DIR_NAMES for part in parts[:-1]):
            found.append("/".join(parts))
    return found


def _wanted(path: str) -> bool:
    if path.startswith(ALLOWED_PREFIXES):
        return False
    suffix = Path(path).suffix.lower()
    if suffix in SUFFIXES:
        return True
    for prefix, suffixes in SOURCE_RULES:
        if path.startswith(prefix) and (suffixes is None or suffix in suffixes):
            return True
    return False


def _files(root: Path) -> Iterator[Path]:
    paths = _tracked(root)
    for path in _walk(root) if paths is None else paths:
        if _wanted(path) and (root / path).is_file():
            yield root / path


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file in _files(root):
        if file.stat().st_size > MAX_BYTES:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # a binary file with a text suffix is not prose
        for number, line in enumerate(text.splitlines(), start=1):
            for char, name in DASHES.items():
                if char in line:
                    findings.append(Finding(rel(file, root), number, f"{name} in text"))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("no_dashes", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
