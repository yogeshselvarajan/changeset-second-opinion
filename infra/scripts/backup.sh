#!/usr/bin/env bash
# HOST: consistent SQLite backup to S3 (sqlite3 .backup, integrity check, gzip, upload).
# Run by cso-backup.timer; run by hand with: bash /opt/cso/infra/scripts/backup.sh
# The instance role may only s3:PutObject under backups/ and publish CSO metrics.
set -euo pipefail

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
: "${CSO_BACKUP_BUCKET:?}" "${CSO_AWS_REGION:?}"
export AWS_DEFAULT_REGION="$CSO_AWS_REGION"

db="${CSO_DB_PATH:-/data/cso/cso.db}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
work=$(mktemp -d)

metric() {
  aws cloudwatch put-metric-data --namespace CSO --metric-name BackupSuccess --value "$1" \
    --unit Count >/dev/null 2>&1 || true
}
cleanup() {
  rm -rf "$work"
}
fail() {
  metric 0
  echo "backup failed" >&2
}
trap cleanup EXIT
trap fail ERR

if [[ ! -f $db ]]; then
  echo "no database at $db" >&2
  false
fi
sqlite3 "$db" ".backup '$work/cso.db'"
[[ $(sqlite3 "$work/cso.db" 'PRAGMA integrity_check;') == ok ]]
gzip -9 "$work/cso.db"

key="backups/$(date -u +%Y/%m)/cso-${stamp}.db.gz"
aws s3 cp "$work/cso.db.gz" "s3://${CSO_BACKUP_BUCKET}/${key}" --sse AES256 --only-show-errors
metric 1
echo "backup ok: s3://${CSO_BACKUP_BUCKET}/${key}"
