#!/usr/bin/env bash
# Restore the SQLite database from a backup.
#
#   restore.sh remote [S3_KEY]   run on YOUR workstation (needs s3:GetObject and SSM access). Picks the
#                                latest backup unless a key is given, presigns it for 15 minutes and has
#                                the host apply it. The instance role never needs read access to S3.
#   restore.sh local FILE.db.gz  run on the host as root: stop the app, keep the old file, swap, start.
#   restore.sh local-url URL     host: download a presigned URL, then do `local`.
#   restore.sh remote-litestream [TIME]   run on YOUR workstation: have the host rebuild the database
#                                from the continuous replica (latest, or as of TIME, UTC RFC 3339).
#   restore.sh litestream [TIME] host: the same, run as root on the host.
set -euo pipefail

mode="${1:-}"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

case "$mode" in
  remote)
    # shellcheck source=lib.sh
    . "$here/lib.sh"
    bucket=$(stack_output BackupBucket)
    key="${2:-}"
    if [[ -z $key ]]; then
      key=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix backups/ \
        --query 'sort_by(Contents,&LastModified)[-1].Key' --output text)
    fi
    if [[ $key != backups/* ]]; then
      echo "unexpected key: $key" >&2
      exit 2
    fi
    echo "restoring s3://$bucket/$key"
    url=$(aws s3 presign "s3://$bucket/$key" --expires-in 900)
    run_on_host "bash /opt/cso/infra/scripts/restore.sh local-url '$url'"
    ;;
  local-url)
    url="${2:?presigned URL required}"
    tmp=$(mktemp --suffix=.db.gz)
    curl -fsSL -o "$tmp" "$url"
    exec bash "$0" local "$tmp"
    ;;
  local)
    file="${2:?backup file required}"
    db="${CSO_DB_PATH:-/data/cso/cso.db}"
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    gunzip -c "$file" >"$work/restored.db"
    if [[ $(sqlite3 "$work/restored.db" 'PRAGMA integrity_check;') != ok ]]; then
      echo "backup failed the integrity check" >&2
      exit 1
    fi
    compose="bash /opt/cso/infra/scripts/compose.sh"
    $compose stop caddy api worker litestream
    if [[ -f $db ]]; then
      cp -p "$db" "${db}.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    rm -f "${db}-wal" "${db}-shm"
    rm -rf "$(dirname "$db")/.cso.db-litestream" # a swapped file starts a new replication history
    install -o 10001 -g 10001 -m 0640 "$work/restored.db" "$db"
    $compose up -d
    echo "restored $db from $file"
    ;;
  remote-litestream)
    # shellcheck source=lib.sh
    . "$here/lib.sh"
    at="${2:-}"
    if [[ -n $at && ! $at =~ ^[0-9TZ:.+-]+$ ]]; then
      echo "the time must look like 2026-10-19T08:30:00Z" >&2
      exit 2
    fi
    run_on_host "bash /opt/cso/infra/scripts/restore.sh litestream $at"
    ;;
  litestream)
    # Rebuild the database from the continuous replica (Litestream) and swap it in. Without a
    # time it takes the latest state; with one (UTC, RFC 3339) it takes the state at that moment.
    at="${2:-}"
    if [[ -n $at && ! $at =~ ^[0-9TZ:.+-]+$ ]]; then
      echo "the time must look like 2026-10-19T08:30:00Z" >&2
      exit 2
    fi
    # shellcheck disable=SC1091
    . /etc/cso/bootstrap.env
    : "${CSO_BACKUP_BUCKET:?}" "${CSO_AWS_REGION:?}"
    data="${CSO_DATA_DIR:-/data/cso}"
    db="${CSO_DB_PATH:-$data/cso.db}"
    compose="bash /opt/cso/infra/scripts/compose.sh"
    image=litestream/litestream:0.3.13
    out="$data/restored-from-replica.db"
    rm -f "$out"
    args=(restore -config /etc/litestream.yml -o /data/restored-from-replica.db)
    [[ -n $at ]] && args+=(-timestamp "$at")
    # Restore into a side file first: the live database is not touched until the copy checks out.
    docker run --rm --user 10001:10001 \
      -e CSO_BACKUP_BUCKET="$CSO_BACKUP_BUCKET" -e AWS_REGION="$CSO_AWS_REGION" \
      -v "$data:/data" -v /opt/cso/infra/litestream/litestream.yml:/etc/litestream.yml:ro \
      "$image" "${args[@]}" /data/cso.db
    if [[ $(sqlite3 "$out" 'PRAGMA integrity_check;') != ok ]]; then
      echo "the restored copy failed the integrity check; the live database was not touched" >&2
      rm -f "$out"
      exit 1
    fi
    $compose stop caddy api worker litestream
    if [[ -f $db ]]; then
      cp -p "$db" "${db}.pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    rm -f "${db}-wal" "${db}-shm"
    # A new database file needs a new replication history, or Litestream would refuse to continue.
    rm -rf "$data/.cso.db-litestream"
    install -o 10001 -g 10001 -m 0640 "$out" "$db"
    rm -f "$out"
    $compose up -d
    echo "restored $db from the replica${at:+ as of $at}"
    ;;
  *)
    echo "usage: restore.sh remote [S3_KEY] | remote-litestream [TIME] | local FILE.db.gz | local-url URL | litestream [TIME]" >&2
    exit 2
    ;;
esac
