#!/usr/bin/env python3
"""Validate infra/caddy/Caddyfile with the stock Caddy image.

The edge image is built with a rate-limit module that stock Caddy lacks, so the stock image
rejects `order rate_limit ...` and every `rate_limit { ... }` block. This script removes exactly
those (the snippets stay defined and imported, so the rest of the structure is still checked),
writes the result to a temporary directory and runs `caddy validate` on it in a container.

    python scripts/ci/validate_caddy.py                  # validate with docker
    python scripts/ci/validate_caddy.py --print          # show the stripped file, run nothing
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from common import default_root

IMAGE = "caddy:2"
ORDER_LINE = re.compile(r"^\s*order\s+rate_limit\b.*\n", re.MULTILINE)
BLOCK_START = re.compile(r"^[ \t]*rate_limit[ \t]*\{[ \t]*\n", re.MULTILINE)


def strip_rate_limit(text: str) -> str:
    """The Caddyfile without the module-only directives (brace matched, so nested zones go too)."""
    text = ORDER_LINE.sub("", text)
    while True:
        match = BLOCK_START.search(text)
        if match is None:
            return text
        depth, pos = 1, match.end()
        while depth and pos < len(text):
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
            pos += 1
        if depth:
            raise ValueError("unbalanced braces after a rate_limit block")
        line_end = text.find("\n", pos)
        end = len(text) if line_end == -1 else line_end + 1
        text = text[: match.start()] + text[end:]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    source = default_root() / "infra" / "caddy" / "Caddyfile"
    stripped = strip_rate_limit(source.read_text(encoding="utf-8"))
    if "--print" in args:
        print(stripped, end="")
        return 0
    if shutil.which("docker") is None:
        print("validate_caddy: docker is not available", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Caddyfile").write_text(stripped, encoding="utf-8")
        command = [
            "docker", "run", "--rm", "-v", f"{tmp}:/etc/caddy:ro", IMAGE,
            "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        ]  # fmt: skip
        return subprocess.run(command, check=False).returncode  # noqa: S603 (fixed argv)


if __name__ == "__main__":
    sys.exit(main())
