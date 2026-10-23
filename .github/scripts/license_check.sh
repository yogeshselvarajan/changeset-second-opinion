#!/usr/bin/env bash
# Installs the runtime (no dev) dependencies from the lock file into a scratch environment and fails
# on GPL or AGPL licences, apart from the names in .github/license-allowlist.txt.
# Run from the repository root. Needs uv.
set -euo pipefail

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

UV_PROJECT_ENVIRONMENT="$work/venv" uv sync --project backend --frozen --no-dev
python_bin="$work/venv/bin/python"
[ -x "$python_bin" ] || python_bin="$work/venv/Scripts/python.exe"

uvx pip-licenses==5.5.5 --python "$python_bin" --format=json --with-system --output-file "$work/report.json"
"${PYTHON:-python3}" .github/scripts/check_licenses.py "$work/report.json" .github/license-allowlist.txt
