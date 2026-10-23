#!/usr/bin/env python3
"""Invariant 2: nothing is hidden from reviewers, and nothing posts or closes automatically.

Lanes only order the queue. There is no auto-close, no auto-post and no silent dismissal, so no
function, variable or attribute may be named for one. The scan tokenises identifiers in
`backend/src` (Python) and `web/src` (ts, tsx) and rejects names such as `auto_post`, `autoClose`,
`post_to_osm`, `close_changeset`, `hide_case` or `suppress_case`. Prose and comments that use a
hyphenated phrase (for example "no auto-post") are not identifiers and are not flagged.
Test files and the generated client are skipped, so a test can name what it forbids.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from common import Finding, iter_files, rel, run_main

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FORBIDDEN = re.compile(
    r"auto_?(?:post|close|comment|resolve|hide|reject|dismiss|submit)"
    r"|post_?to_?osm"
    r"|(?:post|submit)_?(?:changeset_?)?comment_?to_?osm"
    r"|close_?changeset"
    r"|hide_?(?:case|changeset)"
    r"|suppress_?(?:case|changeset)"
    r"|silently_?(?:drop|skip|hide)",
    re.IGNORECASE,
)
WEB_SKIP_DIRS = ("api", "fonts", "test")


def _targets(root: Path) -> Iterator[Path]:
    yield from iter_files(root / "backend" / "src", (".py",))
    for file in iter_files(root / "web" / "src", (".ts", ".tsx"), WEB_SKIP_DIRS):
        if not re.search(r"\.test\.tsx?$", file.name):
            yield file


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file in _targets(root):
        path = rel(file, root)
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            for token in IDENTIFIER.findall(line):
                if FORBIDDEN.search(token):
                    findings.append(
                        Finding(path, number, f"name `{token}` suggests an automatic action")
                    )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("check_no_auto_actions", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
