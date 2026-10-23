#!/usr/bin/env bash
# HOST: deploy a git ref, or go back to the one before it.
#
#   update.sh [GIT_REF]    take a database backup, remember what runs now, fetch and build the ref,
#                          restart the stack and run the health check. If the check fails the previous
#                          release is restored automatically and the exit status is 1.
#   update.sh --rollback   return to the release that ran before the last deploy.
#
# What "previous release" means: the git commit and the three images (backend, Decider, web) that were
# running before the deploy. Their images are kept under the tag :rollback, so going back needs no
# rebuild and no network. The database is NOT rolled back. Most migrations only add tables or
# columns, so the older code usually runs against the newer schema, but that is not guaranteed;
# if a migration has to be undone, restore the database from Litestream or from the backup this
# script takes first (restore.sh).
#
# The stack is one set of containers in one network namespace sharing one SQLite file, so a second
# copy cannot run beside the old one on a side port; the swap is a restart of a few seconds.
# Usage (as root on the host): bash /opt/cso/infra/scripts/update.sh [GIT_REF | --rollback]
set -euo pipefail

repo=/opt/cso
state=/var/lib/cso
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
compose="bash $here/compose.sh"
images=(cso-backend cso-decider cso-web)

log() { printf '[update] %s\n' "$*"; }

keep_images() {
  local image
  for image in "${images[@]}"; do
    if docker image inspect "$image:local" >/dev/null 2>&1; then
      docker tag "$image:local" "$image:rollback"
    fi
  done
}

restore_images() {
  local image
  for image in "${images[@]}"; do
    if docker image inspect "$image:rollback" >/dev/null 2>&1; then
      docker tag "$image:rollback" "$image:local"
    fi
  done
}

go_back() {
  local sha
  [[ -f $state/previous.sha ]] || {
    echo "update: nothing to roll back to (no earlier deploy recorded)" >&2
    return 1
  }
  sha=$(<"$state/previous.sha")
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || {
    echo "update: the recorded commit is not a commit id" >&2
    return 1
  }
  log "going back to ${sha:0:12}"
  cd "$repo"
  git checkout --quiet "$sha"
  restore_images
  $compose up -d --no-build
  bash "$here/healthcheck.sh"
}

ref="${1:-}"
if [[ $ref == --rollback ]]; then
  go_back
  exit
fi
if [[ -n $ref && ! $ref =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "invalid git ref: $ref" >&2
  exit 2
fi

cd "$repo"
install -d -m 0755 "$state"
before=$(git rev-parse HEAD)

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
if [[ ${CSO_PROFILE:-full} == replay ]]; then
  # The replay demo has no backup bucket; its data is the recorded set, which `cso seed` rebuilds.
  log "replay profile: no S3 backup (the nightly EBS snapshot is the copy)"
else
  log "backing up the database first"
  if ! bash "$here/backup.sh"; then
    echo "update: the backup failed, so nothing was changed. Fix it, or set CSO_SKIP_BACKUP=1 to go on." >&2
    [[ ${CSO_SKIP_BACKUP:-} == 1 ]] || exit 1
  fi
fi

git fetch --tags --force origin
if [[ -n $ref ]]; then
  if git rev-parse --verify --quiet "origin/$ref" >/dev/null; then
    git checkout -B "$ref" "origin/$ref"
  else
    git checkout "$ref"
  fi
fi
after=$(git rev-parse HEAD)
if [[ $before == "$after" ]]; then
  log "already at ${after:0:12}; rebuilding and restarting"
fi

keep_images
printf '%s\n' "$before" >"$state/previous.sha"
git log -1 --format='deploying %h %s'
$compose up -d --build

if bash "$here/healthcheck.sh"; then
  log "deployed ${after:0:12}; roll back with: update.sh --rollback"
else
  echo "update: the health check failed; restoring the previous release" >&2
  if go_back; then
    echo "update: back on ${before:0:12}" >&2
  else
    echo "update: ROLLBACK FAILED, the stack needs attention" >&2
  fi
  exit 1
fi
