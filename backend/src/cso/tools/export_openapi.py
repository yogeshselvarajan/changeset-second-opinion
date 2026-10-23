"""Write the canonical OpenAPI document: `uv run python -m cso.tools.export_openapi`.

The committed `backend/openapi/v1.json` is the machine-readable contract; the TypeScript client is
generated from it. `--check` compares the app with the file and exits 1 on any difference (CI uses
the contract test for the same comparison). Output is deterministic: sorted keys, two-space indent,
LF line endings, one trailing newline.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

from cso.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "v1.json"


def build_openapi() -> dict[str, Any]:
    """The OpenAPI document of the application as served."""
    return create_app().openapi()


def canonical_json(document: dict[str, Any]) -> str:
    """Stable text form of a document (what is committed)."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def diff_against_file(path: Path = OPENAPI_PATH) -> str:
    """Unified diff between the committed file and the app; empty when they agree."""
    current = canonical_json(build_openapi())
    committed = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = difflib.unified_diff(
        committed.splitlines(keepends=True),
        current.splitlines(keepends=True),
        fromfile=str(path.name),
        tofile="app",
    )
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_openapi", description=__doc__)
    parser.add_argument("--out", type=Path, default=OPENAPI_PATH, help="where to write")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    args = parser.parse_args(argv)

    if args.check:
        diff = diff_against_file(args.out)
        if diff:
            sys.stderr.write(diff)
            return 1
        return 0
    text = canonical_json(build_openapi())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    operations = sum(len(methods) for methods in json.loads(text)["paths"].values())
    print(f"wrote {args.out} ({operations} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
