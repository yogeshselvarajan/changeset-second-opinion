#!/usr/bin/env bash
# Decides which parts of the repository a change touches, for path filtering in ci.yml.
# Writes `name=true|false` lines to $GITHUB_OUTPUT. Anything unclear turns every filter on, because a
# skipped check is worse than an extra one. Inputs (environment): EVENT_NAME, BASE_REF, BEFORE_SHA.
set -euo pipefail

out="${GITHUB_OUTPUT:-/dev/stdout}"
all=false
files=""

case "${EVENT_NAME:-}" in
  pull_request)
    base="$(git merge-base "origin/${BASE_REF}" HEAD)" || all=true
    [ "$all" = true ] || files="$(git diff --name-only "$base" HEAD)"
    ;;
  push)
    before="${BEFORE_SHA:-}"
    if [ -z "$before" ] || [ "${before//0/}" = "" ] || ! git cat-file -e "${before}^{commit}" 2>/dev/null; then
      all=true
    else
      files="$(git diff --name-only "$before" HEAD)"
    fi
    ;;
  *) all=true ;;
esac

match() { # match REGEX: true when any changed file matches
  if [ "$all" = true ]; then echo true; return; fi
  if printf '%s\n' "$files" | grep -Eq "$1"; then echo true; else echo false; fi
}

shared='^(\.github/(workflows/ci\.yml|actions/|scripts/)|scripts/ci/)'
{
  echo "backend=$(match "^(backend/|config/|${shared#^})")"
  echo "web=$(match "^(web/|site/|backend/openapi/|evaluation/|${shared#^})")"
  echo "site=$(match "^(site/|web/|backend/(src|openapi)/|docs/|${shared#^})")"
  echo "infra=$(match "^(infra/|scripts/|backend/pyproject\\.toml|${shared#^})")"
  echo "lockfiles=$(match '^(backend/(pyproject\.toml|uv\.lock)|web/package(-lock)?\.json|site/package(-lock)?\.json|\.github/license-allowlist\.txt)')"
  echo "workflows=$(match '^\.github/')"
} >>"$out"
