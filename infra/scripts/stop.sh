#!/usr/bin/env bash
# OPERATOR: stop the host (compute billing ends; the volume and the Elastic IP are kept).
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$here/lib.sh"

id=$(instance_id)
aws ec2 stop-instances --instance-ids "$id" --query 'StoppingInstances[0].CurrentState.Name' --output text
aws ec2 wait instance-stopped --instance-ids "$id"
echo "stopped $id"
