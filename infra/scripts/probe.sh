#!/usr/bin/env bash
# HOST, run every minute by cso-probe.timer: publishes three CloudWatch metrics in namespace CSO.
#   ReadyzOk           1 when the API answers /readyz with 200 (database and Decider both fine), else 0
#   DiskUsedPercent    percent of the root volume in use
#   GpuMemoryPercent   percent of GPU memory in use (only on a GPU instance type)
# The alarms in the CloudFormation template read these. The instance role may publish metrics in
# the CSO namespace only. A failed probe must not look like a healthy one, so every step that cannot
# run reports its own failure (ReadyzOk 0) instead of exiting quietly.
set -uo pipefail

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
: "${CSO_AWS_REGION:?}" "${CSO_INSTANCE_TYPE:?}"
export AWS_DEFAULT_REGION="$CSO_AWS_REGION"

put() {
  aws cloudwatch put-metric-data --namespace CSO --metric-name "$1" --value "$2" --unit "$3" \
    >/dev/null 2>&1 || echo "probe: could not publish $1" >&2
}

# The API listens on loopback inside the stack's network namespace, so ask from inside it.
check=$(
  cat <<'PY'
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=5) as response:
        sys.exit(0 if response.status == 200 else 1)
except (urllib.error.URLError, OSError):
    sys.exit(1)
PY
)
if timeout 20 bash /opt/cso/infra/scripts/compose.sh exec -T api python -c "$check" >/dev/null 2>&1; then
  put ReadyzOk 1 Count
else
  put ReadyzOk 0 Count
fi

used=$(df --output=pcent / | tail -n 1 | tr -dc '0-9')
[[ -n $used ]] && put DiskUsedPercent "$used" Percent

case "$CSO_INSTANCE_TYPE" in
  g* | p*)
    if memory=$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null |
      head -n 1); then
      used_mib=${memory%%,*}
      total_mib=${memory##*,}
      used_mib=${used_mib//[[:space:]]/}
      total_mib=${total_mib//[[:space:]]/}
      if [[ $used_mib =~ ^[0-9]+$ && $total_mib =~ ^[0-9]+$ && $total_mib -gt 0 ]]; then
        put GpuMemoryPercent "$((100 * used_mib / total_mib))" Percent
      fi
    fi
    ;;
esac
