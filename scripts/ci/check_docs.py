#!/usr/bin/env python3
"""The public documents resolve and read plainly.

Two checks, offline and standard library only:

1. Links. Every relative link in the maintained documents must point at a file or directory that
   exists, and a `#fragment` must match a heading in the target (GitHub's slug rules). Web links
   (`http`, `https`, `mailto`) are not fetched. Links in code blocks and inline code are ignored.
2. Style, on the documents a newcomer reads first. No "leverage", "seamless", "robust",
   "powerful", "cutting-edge" or "AI-powered"; no exclamation marks; no heading that is a
   question; no top-level list longer than seven items.

The dash check is `no_dashes.py`; it covers the same files.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from urllib.parse import unquote

from common import Finding, run_main

# Documents whose links are checked: the root markdown files and the folder readmes. The pages
# under `site/` are built and link-checked by the site's own workflow.
LINK_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "THIRD_PARTY_NOTICES.md",
    "evaluation/README.md",
    "patterns/calibrated_action_gate/README.md",
)
# Documents held to the plain-writing rules.
STYLE_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "patterns/calibrated_action_gate/README.md",
    "evaluation/README.md",
)
MAX_LIST_ITEMS = 7
BANNED_STYLE = re.compile(
    r"\b(leverag(?:e|es|ed|ing)|seamless(?:ly)?|robust(?:ness)?|powerful|"
    r"cutting[- ]edge|AI-powered)\b",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"(?<!\!)\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE = re.compile(r"!\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)")
_HTML_ATTR = re.compile(r"""\b(?:src|href|srcset)\s*=\s*["']([^"']+)["']""")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, no formatting or punctuation, hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links keep their text
    text = text.replace("`", "").replace("*", "").replace("~", "")
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def _prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """(line number, line) outside fenced code blocks."""
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def anchors(text: str) -> set[str]:
    """Every anchor a heading in `text` produces, with GitHub's -1, -2 suffix for repeats."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    for _number, line in _prose_lines(text):
        match = _HEADING.match(line)
        if not match:
            continue
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def _targets(text: str) -> Iterator[tuple[int, str]]:
    for number, line in _prose_lines(text):
        stripped = _INLINE_CODE.sub("", line)
        for pattern in (_LINK, _IMAGE, _HTML_ATTR):
            for match in pattern.finditer(stripped):
                for part in match.group(1).split(","):  # srcset can hold several, comma separated
                    value = part.strip().split(" ")[0]
                    if value:
                        yield number, value
        ref = _REF_DEF.match(stripped)
        if ref:
            yield number, ref.group(1).strip("<>")


def _is_web(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "tel:", "data:", "//"))


def check_links(root: Path, files: Sequence[str] = LINK_FILES) -> list[Finding]:
    findings: list[Finding] = []
    cache: dict[Path, set[str]] = {}

    def anchors_of(path: Path) -> set[str]:
        if path not in cache:
            cache[path] = anchors(path.read_text(encoding="utf-8"))
        return cache[path]

    for name in files:
        source = root / name
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        for number, target in _targets(text):
            if _is_web(target):
                continue
            path_part, _hash, fragment = target.partition("#")
            path_part = unquote(path_part.partition("?")[0])
            if path_part == "":
                resolved = source
            else:
                resolved = (source.parent / path_part).resolve()
                try:
                    resolved.relative_to(root.resolve())
                except ValueError:
                    findings.append(Finding(name, number, f"link leaves the repository: {target}"))
                    continue
                if not resolved.exists():
                    findings.append(Finding(name, number, f"broken link: {target}"))
                    continue
            if fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
                if unquote(fragment).lower() not in anchors_of(resolved):
                    findings.append(Finding(name, number, f"no such heading: {target}"))
    return findings


def check_style(root: Path, files: Sequence[str] = STYLE_FILES) -> list[Finding]:
    findings: list[Finding] = []
    for name in files:
        source = root / name
        if not source.is_file():
            continue
        run = 0
        flagged_run = False
        for number, line in _prose_lines(source.read_text(encoding="utf-8")):
            plain = _INLINE_CODE.sub("", line)
            plain = re.sub(r"\]\([^)]*\)", "]", plain)  # drop link targets
            plain = re.sub(r"<[^>]+>", "", plain)
            for word in BANNED_STYLE.finditer(plain):
                findings.append(Finding(name, number, f"avoid the word {word.group(0)!r}"))
            if re.search(r"[A-Za-z0-9)\]\"'_*]!(?:\s|$)", plain) and "![" not in line:
                findings.append(Finding(name, number, "exclamation mark"))
            heading = _HEADING.match(line)
            if heading and heading.group(2).rstrip().endswith("?"):
                findings.append(Finding(name, number, "heading is a question"))
            # Top-level list length: a paragraph, heading or table row ends the list.
            if _LIST_ITEM.match(line):
                run += 1
                if run > MAX_LIST_ITEMS and not flagged_run:
                    findings.append(
                        Finding(name, number, f"list is longer than {MAX_LIST_ITEMS} items")
                    )
                    flagged_run = True
            elif line.strip() and not line.startswith((" ", "\t")):
                run = 0
                flagged_run = False
    return findings


def check(root: Path) -> list[Finding]:
    return [*check_links(root), *check_style(root)]


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("check_docs", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
