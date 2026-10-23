#!/usr/bin/env python3
"""Run every invariant check and print one summary line per check: `python scripts/ci/run_all.py`.

Exit status is 1 if any check has a finding. `--root DIR` points the checks at another tree.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

import check_docs
import check_forbidden_strings
import check_no_auto_actions
import check_no_osm_writes
import check_policy_inputs
import no_dashes

CHECKS = (
    check_no_osm_writes,
    check_forbidden_strings,
    check_no_auto_actions,
    check_policy_inputs,
    no_dashes,
    check_docs,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    failed = [module.__name__ for module in CHECKS if module.main(args) != 0]
    if failed:
        print(f"run_all: failed checks: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"run_all: all {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
