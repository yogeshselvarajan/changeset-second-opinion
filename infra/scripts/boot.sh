#!/usr/bin/env bash
# HOST, run as root at every boot by cso-secrets.service before the stack starts.
# Reads the secrets from SSM Parameter Store (SecureString, path /cso/<stage>/) and writes them to
# /run/cso/secrets.env. /run is a tmpfs, so nothing secret ever reaches the EBS volume or a snapshot;
# the file is rebuilt at each boot and is readable by root only. Docker Compose loads it for the API
# and the worker (infra/compose/docker-compose.aws.yml). A secret that is not set is simply absent
# (the feature behind it stays off); a failed call to SSM stops the boot so a half-configured stack
# never starts.
#
# Parameters (all optional):
#   /cso/<stage>/osm_oauth_client_secret    SecureString   "Sign in with OpenStreetMap" (ADR-011)
set -euo pipefail

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
: "${CSO_STAGE:?}" "${CSO_AWS_REGION:?}"
export AWS_DEFAULT_REGION="$CSO_AWS_REGION"

dir=/run/cso
file="$dir/secrets.env"
prefix="/cso/${CSO_STAGE}"

# Value of one parameter, empty when it does not exist. Any other failure aborts the boot.
param() {
  local out
  if out=$(aws ssm get-parameter --name "$prefix/$1" --with-decryption \
    --query Parameter.Value --output text 2>&1); then
    printf '%s' "$out"
  elif grep -q ParameterNotFound <<<"$out"; then
    printf ''
  else
    echo "boot: could not read $prefix/$1: ${out%%$'\n'*}" >&2
    return 1
  fi
}

umask 077
install -d -m 0700 "$dir"
tmp=$(mktemp "$dir/secrets.XXXXXX")
trap 'rm -f "$tmp"' EXIT

osm_secret=$(param osm_oauth_client_secret)
if [[ -n $osm_secret ]]; then
  printf 'CSO_OSM_OAUTH_CLIENT_SECRET=%s\n' "$osm_secret" >>"$tmp"
fi
unset osm_secret

mv "$tmp" "$file"
trap - EXIT
chmod 0600 "$file"
echo "boot: wrote $(grep -c . "$file" || true) secret(s) to $file"
