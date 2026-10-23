#!/usr/bin/env bash
# OPERATOR: deploy a git ref on the host through SSM Run Command, or go back to the release before it.
# Usage: bash infra/scripts/deploy.sh [GIT_REF]
#        bash infra/scripts/deploy.sh --rollback
# The host takes a database backup first, rebuilds, restarts, runs the health check and rolls itself
# back if the check fails (infra/scripts/update.sh has the details).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$here/lib.sh"

ref="${1:-}"
if [[ -n $ref && $ref != --rollback && ! $ref =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "invalid git ref: $ref" >&2
  exit 2
fi
run_on_host "bash /opt/cso/infra/scripts/update.sh $ref"
