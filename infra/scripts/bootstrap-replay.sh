#!/usr/bin/env bash
# HOST first-boot helper for the REPLAY DEMO instance (infra/cloudformation/cso-replay-demo.yaml).
# Run as root by the instance's UserData after it cloned the repo to /opt/cso. Idempotent.
#
# What it sets up: Docker (from Docker's apt repository, for a current Compose v2), a swap file
# (the web image builds the SPA and the docs site, which is tight on 1 to 2 GiB of memory), the
# settings file /opt/cso/.env, the systemd units and the stack: Caddy (automatic HTTPS), API,
# worker, migrations and `cso seed`. No GPU, no Decider, no Bedrock, no S3, no CloudWatch Logs.
#
# Everything about the domain comes from /etc/cso/bootstrap.env, which the template writes:
#   CSO_DOMAIN       the public name (also CSO_SITE_ADDRESS, CSO_PUBLIC_ORIGIN, the OSM redirect)
#   CSO_APEX_DOMAIN  optional second name that redirects to CSO_DOMAIN
#   CSO_OPEN_HTTP    "true" publishes port 80 (it only redirects to https)
# Optional SSM parameters under /cso/<stage>/ (same names as the full stack): osm_oauth_client_id,
# osm_oauth_client_secret (SecureString, read by boot.sh into a tmpfs), osm_signin_allowed_uids,
# bootstrap_admin_osm_uids.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
: "${CSO_DOMAIN:?}" "${CSO_AWS_REGION:?}" "${CSO_STAGE:?}"
export AWS_DEFAULT_REGION="$CSO_AWS_REGION"
repo=/opt/cso
prefix="/cso/${CSO_STAGE}"

log() { printf '[bootstrap-replay] %s\n' "$*"; }

log "swap file"
if ! swapon --show=NAME --noheadings | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

log "packages"
apt-get update -y
apt-get install -y ca-certificates curl git gnupg unzip
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
if ! command -v aws >/dev/null 2>&1; then
  log "installing the AWS CLI v2 ($(uname -m))"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip
  unzip -q -o /tmp/awscliv2.zip -d /tmp
  /tmp/aws/install --update
fi
systemctl enable --now docker

log "data directory"
mkdir -p /data/cso
chown 10001:10001 /data/cso # the backend image runs as uid 10001

# Value of an optional parameter, empty when it does not exist.
optional() {
  aws ssm get-parameter --name "$prefix/$1" --query Parameter.Value --output text 2>/dev/null || true
}

log "settings file"
http_bind=127.0.0.1
[ "${CSO_OPEN_HTTP:-true}" = "true" ] && http_bind=0.0.0.0
umask 077
cat >"$repo/.env" <<ENV
CSO_MODE=replay
CSO_SITE_ADDRESS=${CSO_DOMAIN}
CSO_PUBLIC_ORIGIN=https://${CSO_DOMAIN}
CSO_DATA_DIR=/data/cso
CSO_HTTP_BIND=${http_bind}
CSO_TRUST_PROXY=true
CSO_COOKIE_SECURE=true
ENV
if [ -n "${CSO_APEX_DOMAIN:-}" ]; then
  echo "CSO_APEX_ADDRESS=${CSO_APEX_DOMAIN}" >>"$repo/.env"
fi
# Optional: "Sign in with OpenStreetMap" (ADR-011). On only when the client id AND the secret exist.
# The secret goes to /run/cso/secrets.env from SSM at every boot (boot.sh), never to this file.
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
    admin_uids=$(optional bootstrap_admin_osm_uids)
    [ -n "$admin_uids" ] && echo "CSO_BOOTSTRAP_ADMIN_OSM_UIDS=${admin_uids}" >>"$repo/.env"
  else
    log "an OSM client id exists but no client secret: sign in with OpenStreetMap stays off"
  fi
fi
umask 022

log "systemd units"
cat >/etc/systemd/system/cso-secrets.service <<UNIT
[Unit]
Description=Write the optional CSO secrets from SSM Parameter Store to /run (tmpfs)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/bash ${repo}/infra/scripts/boot.sh
UNIT
cat >/etc/systemd/system/cso.service <<UNIT
[Unit]
Description=Changeset Second Opinion replay demo (docker compose)
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
systemctl daemon-reload

log "secrets"
bash "$repo/infra/scripts/boot.sh"

log "building and starting the stack (first boot builds two images, 10 to 25 minutes)"
bash "$repo/infra/scripts/compose.sh" up -d --build
systemctl enable cso-secrets.service cso.service
log "done; check progress with: bash $repo/infra/scripts/healthcheck.sh --public"
