#!/usr/bin/env python3
"""Invariant 6: UI copy and drafts never use the banned words.

Mirrors `web/src/test/banned-words.test.ts` so CI fails even if that test were skipped, and extends
the same rules to `config/` (community config text shown to reviewers).

Rules:
  * `vandal*`, `spam*`, `illegal*` must not appear anywhere in a `web/src` source file
    (ts, tsx, css, json) or in `web/index.html`;
  * `stop` and `must` must not appear inside string literals of `web/src` ts/tsx files, nor in any
    value of the message catalogue;
  * in `config/**/*.yaml`, every string value is checked with both rules, except the subtree under
    a `banned_words` key, which exists to list the words.
Excluded from the web scan: generated client (`api/`), vendored `fonts/`, `test/` helpers and
`*.test.ts(x)` files, which need the words to assert on them.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from common import Finding, iter_files, rel, run_main

ALWAYS = re.compile(r"\b(vandal\w*|spam\w*|illegal\w*)\b", re.IGNORECASE)
IN_STRINGS = re.compile(r"\b(stop|must)\b", re.IGNORECASE)
STRING_LITERAL = re.compile(r"([\"'`])((?:\\.|(?!\1)[^\\\n])*)\1")
WEB_SKIP_DIRS = ("api", "fonts", "test")
BANNED_WORDS_KEY = "banned_words"


def _is_test_file(path: Path) -> bool:
    return bool(re.search(r"\.test\.tsx?$", path.name))


def _web_files(root: Path) -> Iterator[Path]:
    for file in iter_files(root / "web" / "src", (".ts", ".tsx", ".css", ".json"), WEB_SKIP_DIRS):
        if not _is_test_file(file):
            yield file
    index = root / "web" / "index.html"
    if index.is_file():
        yield index


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _scan_web_file(file: Path, root: Path) -> list[Finding]:
    text = file.read_text(encoding="utf-8")
    path = rel(file, root)
    findings: list[Finding] = []
    for match in ALWAYS.finditer(text):
        findings.append(
            Finding(path, _line_of(text, match.start()), f"banned word {match.group(0)!r}")
        )
    if file.suffix in {".ts", ".tsx"}:
        for literal in STRING_LITERAL.finditer(text):
            found = IN_STRINGS.search(literal.group(2))
            if found:
                findings.append(
                    Finding(
                        path,
                        _line_of(text, literal.start()),
                        f"banned word {found.group(0)!r} in a string literal",
                    )
                )
    if file.suffix == ".json" and file.parent.name == "messages":
        findings.extend(_scan_catalogue(text, path))
    return findings


def _scan_catalogue(text: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [Finding(path, 1, "message catalogue is not valid JSON")]
    for key, value in data.items():
        if isinstance(value, str) and IN_STRINGS.search(value):
            findings.append(Finding(path, 1, f"banned word in message {key!r}"))
    return findings


def _strings(node: Any, trail: str = "") -> Iterator[tuple[str, str]]:
    """(dotted path, text) for every string value, skipping the `banned_words` subtree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == BANNED_WORDS_KEY:
                continue
            yield from _strings(value, f"{trail}.{key}" if trail else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{trail}[{index}]")
    elif isinstance(node, str):
        yield trail, node


def _scan_yaml_without_pyyaml(text: str, path: str) -> list[Finding]:
    """Line-based fallback: skip the indented block under a `banned_words:` key."""
    findings: list[Finding] = []
    skip_indent: int | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_indent is not None:
            if stripped and indent <= skip_indent and not stripped.startswith("-"):
                skip_indent = None
            elif stripped:
                continue
        if stripped.startswith(f"{BANNED_WORDS_KEY}:"):
            skip_indent = indent
            continue
        body = stripped.lstrip("- ").split("#", 1)[0]
        if ALWAYS.search(body) or IN_STRINGS.search(body):
            findings.append(Finding(path, number, "banned word in config text"))
    return findings


def _scan_config(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file in iter_files(root / "config", (".yaml", ".yml")):
        path = rel(file, root)
        text = file.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore[import-untyped,unused-ignore]
        except ImportError:
            findings.extend(_scan_yaml_without_pyyaml(text, path))
            continue
        for trail, value in _strings(yaml.safe_load(text)):
            if ALWAYS.search(value) or IN_STRINGS.search(value):
                findings.append(Finding(path, 1, f"banned word in config value {trail!r}"))
    return findings


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file in _web_files(root):
        findings.extend(_scan_web_file(file, root))
    findings.extend(_scan_config(root))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("check_forbidden_strings", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
