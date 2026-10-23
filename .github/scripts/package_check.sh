#!/usr/bin/env bash
# Builds the backend sdist and wheel, checks the metadata, inspects the wheel and installs it into a
# clean virtual environment. The release workflow runs the same script, so a pull request finds a
# packaging problem before a tag does.
#   bash .github/scripts/package_check.sh backend /path/to/outdir
# Needs uv. Run from the repository root.
set -euo pipefail

project="${1:?project directory}"
out="${2:?output directory}"
rm -rf "$out"
mkdir -p "$out"

uv build "$project" --out-dir "$out"
uvx twine==7.0.0 check --strict "$out"/*

wheel="$(ls "$out"/*.whl)"
sdist="$(ls "$out"/*.tar.gz)"

"${PYTHON:-python3}" - "$wheel" "$sdist" <<'PY'
import sys
import tarfile
import zipfile

wheel, sdist = sys.argv[1:3]
names = zipfile.ZipFile(wheel).namelist()
errors = []

def need(prefix: str, label: str) -> None:
    if not any(n.startswith(prefix) for n in names):
        errors.append(f"wheel has no {label} ({prefix})")

need("cso/persistence/migrations/versions/", "migrations")
need("cso/_data/fixtures/demo/", "demo fixtures")
if not any(n.endswith(".dist-info/licenses/LICENSE") for n in names):
    errors.append("wheel has no licence file")
if not any(n.endswith(".dist-info/entry_points.txt") for n in names):
    errors.append("wheel has no entry points (the cso command)")

blocked = ("tests/", ".env", ".db", ".pem", ".key", "secret", "credentials", ".github/", "node_modules")
for name in names + tarfile.open(sdist).getnames():
    lowered = name.lower()
    if any(part in lowered for part in blocked):
        errors.append(f"unexpected file in a distribution: {name}")
if errors:
    print("\n".join(errors), file=sys.stderr)
    sys.exit(1)
print(f"wheel ok: {len(names)} files")
PY

venv="$(mktemp -d)"
trap 'rm -rf "$venv"' EXIT
uv venv --python 3.13 "$venv/v"
uv pip install --python "$venv/v" "$wheel"
if [ -x "$venv/v/bin/cso" ]; then cso_bin="$venv/v/bin/cso"; else cso_bin="$venv/v/Scripts/cso.exe"; fi
if [ -x "$venv/v/bin/python" ]; then py="$venv/v/bin/python"; else py="$venv/v/Scripts/python.exe"; fi
"$cso_bin" --help >/dev/null
# Import from a neutral directory so the source tree cannot satisfy the import.
(cd "$venv" && "$py" -I -c "import cso.main, cso.persistence.admin; print('import ok')")
echo "package check passed: $(basename "$wheel")"
