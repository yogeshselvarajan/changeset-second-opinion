#!/usr/bin/env bash
# OPERATOR: start the host and wait until the application answers. Containers come back on their own
# (systemd unit cso.service plus restart policy); the model cache lives on the data volume.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$here/lib.sh"

id=$(instance_id)
aws ec2 start-instances --instance-ids "$id" --query 'StartingInstances[0].CurrentState.Name' --output text
aws ec2 wait instance-status-ok --instance-ids "$id"
echo "instance is up; waiting for the application"
for attempt in $(seq 1 30); do
  if run_on_host "bash /opt/cso/infra/scripts/healthcheck.sh" >/dev/null 2>&1; then
    echo "ready: https://$(stack_output DomainName)"
    exit 0
  fi
  echo "attempt $attempt: not ready yet"
  sleep 20
done
echo "the application did not become ready; run: aws ssm start-session --target $id" >&2
exit 1
