#!/usr/bin/env bash
# HOST first-boot helper, run as root by the instance's UserData after it cloned the repo to /opt/cso.
# Idempotent: safe to run again. Installs Docker (and the NVIDIA container toolkit on GPU types),
# writes /opt/cso/.env from SSM parameters (settings only, no secrets), installs the systemd units
# and starts the stack. Secrets never touch the disk: boot.sh puts them on a tmpfs at every boot.
#
# Prerequisite in SSM Parameter Store (see the "Deploy on AWS" page of the docs site): /cso/<stage>/user_agent (String).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
: "${CSO_DOMAIN:?}" "${CSO_BACKUP_BUCKET:?}" "${CSO_AWS_REGION:?}" "${CSO_INSTANCE_TYPE:?}" "${CSO_STAGE:?}"
export AWS_DEFAULT_REGION="$CSO_AWS_REGION"
repo=/opt/cso
prefix="/cso/${CSO_STAGE}"

log() { printf '[bootstrap] %s\n' "$*"; }

log "packages"
apt-get update -y
apt-get install -y ca-certificates curl git gnupg sqlite3 unzip docker.io docker-compose-v2

if ! command -v aws >/dev/null 2>&1; then
  log "installing the AWS CLI v2"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -q -o /tmp/awscliv2.zip -d /tmp
  /tmp/aws/install --update
fi

case "$CSO_INSTANCE_TYPE" in
  g* | p*)
    if ! command -v nvidia-ctk >/dev/null 2>&1; then
      log "installing the NVIDIA container toolkit"
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
          >/etc/apt/sources.list.d/nvidia-container-toolkit.list
      apt-get update -y
      apt-get install -y nvidia-container-toolkit
    fi
    nvidia-ctk runtime configure --runtime=docker
    ;;
esac
systemctl enable --now docker
systemctl restart docker

log "data directories"
mkdir -p /data/cso /data/models
chown 10001:10001 /data/cso # the backend image runs as uid 10001
chown 10002:10002 /data/models # the decider image runs as uid 10002

# Value of an optional parameter, empty when it does not exist.
optional() {
  aws ssm get-parameter --name "$prefix/$1" --query Parameter.Value --output text 2>/dev/null || true
}

log "environment file"
user_agent=$(aws ssm get-parameter --name "$prefix/user_agent" --query Parameter.Value --output text)
case "$user_agent" in
  *'<REPO_URL>'* | *'<CONTACT_EMAIL>'* | '')
    echo "SSM parameter $prefix/user_agent must hold a real contact (no placeholders)" >&2
    exit 1
    ;;
esac
umask 077
cat >"$repo/.env" <<ENV
CSO_MODE=live
CSO_USER_AGENT=${user_agent}
CSO_SITE_ADDRESS=${CSO_DOMAIN}
CSO_PUBLIC_ORIGIN=https://${CSO_DOMAIN}
CSO_DATA_DIR=/data/cso
CSO_HF_DIR=/data/models
CSO_BACKUP_BUCKET=${CSO_BACKUP_BUCKET}
CSO_BEDROCK_REGION=${CSO_AWS_REGION}
CSO_TRUST_PROXY=true
CSO_COOKIE_SECURE=true
AWS_REGION=${CSO_AWS_REGION}
ENV
# Optional: "Sign in with OpenStreetMap" (ADR-011). Off unless the client id AND the secret exist.
# Only the settings go in this file; the client secret is added at boot from SSM to /run/cso
# (boot.sh) and never written to the disk.
osm_id=$(optional osm_oauth_client_id)
if [ -n "$osm_id" ]; then
  if aws ssm get-parameter --name "$prefix/osm_oauth_client_secret" --query Parameter.Name \
    --output text >/dev/null 2>&1; then
    cat >>"$repo/.env" <<ENV
CSO_OSM_OAUTH_CLIENT_ID=${osm_id}
CSO_OSM_OAUTH_REDIRECT_URL=https://${CSO_DOMAIN}/api/v1/auth/osm/callback
ENV
    osm_uids=$(optional osm_signin_allowed_uids)
    [ -n "$osm_uids" ] && echo "CSO_OSM_SIGNIN_ALLOWED_UIDS=${osm_uids}" >>"$repo/.env"
    # Who may claim the workspace as its admin: OSM user ids, not a secret, so it is a plain parameter.
    admin_uids=$(optional bootstrap_admin_osm_uids)
    [ -n "$admin_uids" ] && echo "CSO_BOOTSTRAP_ADMIN_OSM_UIDS=${admin_uids}" >>"$repo/.env"
  else
    log "an OSM client id exists but no client secret: sign in with OpenStreetMap stays off"
  fi
fi
# Optional: model-written comment drafts through Amazon Bedrock. Off unless the String parameter
# $prefix/live_bedrock holds exactly "1". Any other value (or no parameter) leaves drafts on the
# offline template, because the application only builds a Bedrock client for CSO_LIVE_BEDROCK=1.
# It is a switch, not a secret, so it goes in the settings file like the values above.
live_bedrock=$(optional live_bedrock)
if [ "$live_bedrock" = "1" ]; then
  echo "CSO_LIVE_BEDROCK=1" >>"$repo/.env"
  log "Amazon Bedrock drafts are on (CSO_LIVE_BEDROCK=1)"
fi
umask 022

log "systemd units"
# Order: secrets (tmpfs) -> stack -> boot smoke check. The stack itself starts the Decider before
# the API and the worker (compose depends_on), and the API answers /readyz 503 until the Decider
# answers its own health check.
cat >/etc/systemd/system/cso-secrets.service <<UNIT
[Unit]
Description=Write the CSO secrets from SSM Parameter Store to /run (tmpfs)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/bash ${repo}/infra/scripts/boot.sh
UNIT
cat >/etc/systemd/system/cso.service <<UNIT
[Unit]
Description=Changeset Second Opinion (docker compose)
Requires=docker.service cso-secrets.service
After=docker.service cso-secrets.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${repo}
ExecStart=/usr/bin/bash ${repo}/infra/scripts/compose.sh up -d
ExecStop=/usr/bin/bash ${repo}/infra/scripts/compose.sh stop

[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/cso-smoke.service <<UNIT
[Unit]
Description=Wait for /readyz after boot and log the outcome
After=cso.service
Requires=cso.service

[Service]
Type=oneshot
TimeoutStartSec=420
ExecStart=-/usr/bin/bash ${repo}/infra/scripts/smoke.sh

[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/cso-probe.service <<UNIT
[Unit]
Description=Publish CSO health metrics to CloudWatch

[Service]
Type=oneshot
ExecStart=/usr/bin/bash ${repo}/infra/scripts/probe.sh
UNIT
cat >/etc/systemd/system/cso-probe.timer <<UNIT
[Unit]
Description=Publish CSO health metrics every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/cso-backup.service <<UNIT
[Unit]
Description=Back up the SQLite database to S3

[Service]
Type=oneshot
ExecStart=/usr/bin/bash ${repo}/infra/scripts/backup.sh
UNIT
# 17:00 UTC = 22:30 IST, thirty minutes before the nightly stop.
cat >/etc/systemd/system/cso-backup.timer <<UNIT
[Unit]
Description=Nightly SQLite backup

[Timer]
OnCalendar=*-*-* 17:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload

log "secrets"
bash "$repo/infra/scripts/boot.sh"

log "building and starting the stack (first boot builds images and downloads the model)"
bash "$repo/infra/scripts/compose.sh" up -d --build
systemctl enable cso-secrets.service cso.service cso-smoke.service cso-backup.timer cso-probe.timer
systemctl start cso-backup.timer cso-probe.timer
log "done; check progress with: bash $repo/infra/scripts/healthcheck.sh"
