#!/usr/bin/env python3
"""Fail when a runtime Python dependency is under a strong copyleft licence (GPL or AGPL).

Usage: python .github/scripts/check_licenses.py REPORT.json [ALLOWLIST]

REPORT.json is `pip-licenses --format=json` run against an environment installed with
`uv sync --frozen --no-dev`. LGPL, MPL and weak copyleft are not flagged. A package that is
flagged but listed in the allow list (one `name  # reason` per line) is reported and passes, so a
known exception stays visible and a new one cannot appear without a reviewed change to that file.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# GPL or AGPL, but not LGPL ("Lesser" or "Library" variants).
STRONG = re.compile(r"(?<![A-Za-z])A?GPL|GNU (Affero )?General Public License", re.IGNORECASE)
WEAK = re.compile(r"LGPL|Lesser|Library General", re.IGNORECASE)


def read_allowlist(path: Path) -> set[str]:
    names: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = line.split("#", 1)[0].strip().lower().replace("_", "-")
            if entry:
                names.add(entry)
    return names


def flagged(licence: str) -> bool:
    parts = [p.strip() for p in re.split(r"[;/]| OR ", licence)]
    # A dual licence passes when one option is not strong copyleft.
    options = [p for p in parts if p]
    if not options:
        return False
    return all(STRONG.search(p) and not WEAK.search(p) for p in options)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    report = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    allow = read_allowlist(Path(argv[1])) if len(argv) > 1 else set()
    failures: list[str] = []
    for item in report:
        name = str(item["Name"]).lower().replace("_", "-")
        licence = str(item.get("License", ""))
        if not flagged(licence):
            continue
        line = f"{item['Name']} {item.get('Version', '')}: {licence}"
        if name in allow:
            print(f"allowed exception: {line}")
        else:
            failures.append(line)
    print(f"checked {len(report)} runtime packages")
    for line in failures:
        print(f"::error::strong copyleft runtime dependency: {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
