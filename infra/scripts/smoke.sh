#!/usr/bin/env bash
# HOST, run once after every boot by cso-smoke.service: waits up to five minutes for /readyz to
# answer 200 through the stack and logs the outcome (the journal, and CloudWatch through the probe).
# It never fails the boot: a slow first start downloads the model (about 5 GB) and can take longer;
# the ReadyzOk alarm is what pages someone. Exit status is 0 when ready, 1 when the wait ran out.
set -uo pipefail

limit=${CSO_SMOKE_SECONDS:-300}
start=$SECONDS
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

while ((SECONDS - start < limit)); do
  if timeout 20 bash /opt/cso/infra/scripts/compose.sh exec -T api python -c "$check" >/dev/null 2>&1; then
    echo "smoke: /readyz answered 200 after $((SECONDS - start)) s"
    exit 0
  fi
  sleep 10
done
echo "smoke: /readyz did not answer 200 within ${limit} s (the model may still be downloading)" >&2
exit 1
