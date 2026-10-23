#!/usr/bin/env bash
# Lints every Dockerfile in the repository with a pinned, checksum-verified hadolint binary.
# Run from the repository root. Findings of level warning or above fail the run; style and info
# notes are printed. Set HADOLINT=/path/to/hadolint to use an installed copy (local runs).
set -euo pipefail

version="v2.15.1"
sha256="c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507"

bin="${HADOLINT:-}"
if [ -z "$bin" ]; then
  bin="${RUNNER_TEMP:-/tmp}/hadolint"
  curl -fsSL -o "$bin" "https://github.com/hadolint/hadolint/releases/download/${version}/hadolint-linux-x86_64"
  echo "${sha256}  ${bin}" | sha256sum -c -
  chmod +x "$bin"
fi

mapfile -t files < <(git ls-files '*Dockerfile' '*.Dockerfile' 'Dockerfile*')
echo "hadolint: ${#files[@]} Dockerfiles"
"$bin" --failure-threshold warning "${files[@]}"
