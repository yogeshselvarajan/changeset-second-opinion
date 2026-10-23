#!/usr/bin/env bash
# HOST wrapper: docker compose with the right profile files for this instance type.
# Usage (as root on the host): bash /opt/cso/infra/scripts/compose.sh up -d --build
set -euo pipefail

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env

cd /opt/cso/infra/compose

# The replay demo host (cso-replay-demo.yaml) has no Decider, no S3 and no CloudWatch Logs.
if [[ ${CSO_PROFILE:-full} == replay ]]; then
  exec docker compose --env-file /opt/cso/.env \
    -f docker-compose.yml -f docker-compose.demo.yml -f docker-compose.replay-aws.yml "$@"
fi

case "$CSO_INSTANCE_TYPE" in
  g* | p*) profile=gpu ;;
  *) profile=cpu ;;
esac

exec docker compose --env-file /opt/cso/.env \
  -f docker-compose.yml -f "docker-compose.${profile}.yml" -f docker-compose.aws.yml "$@"
