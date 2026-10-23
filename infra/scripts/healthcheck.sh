#!/usr/bin/env bash
# HOST: container state, listeners, API readiness and Decider health. Exit 1 when anything is wrong.
# Usage (as root on the host): bash /opt/cso/infra/scripts/healthcheck.sh [--public]
#   --public also requests https://$CSO_DOMAIN/healthz through the edge (needs DNS and a certificate).
set -euo pipefail

# shellcheck disable=SC1091
. /etc/cso/bootstrap.env
compose="bash /opt/cso/infra/scripts/compose.sh"
status=0

echo "== containers"
$compose ps

echo "== listeners inside the shared namespace"
listeners=$($compose exec -T stack netstat -ltn)
echo "$listeners"
# The Decider (8099) and the API (8000) must only listen on 127.0.0.1.
if grep -E '(0\.0\.0\.0|:::?|\*):(8099|8000)[[:space:]]' <<<"$listeners"; then
  echo "FAIL: 8099 or 8000 listens beyond 127.0.0.1" >&2
  status=1
fi

echo "== API readiness and Decider health"
if [[ ${CSO_PROFILE:-full} == replay ]]; then
  # The replay demo has no Decider: only the API's readiness counts.
  probe=$(
    cat <<'PY'
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/readyz", timeout=5) as response:
        print("readyz", response.status, response.read().decode()[:300])
        sys.exit(0 if response.status == 200 else 1)
except (urllib.error.URLError, OSError) as error:
    print("readyz failed:", error)
    sys.exit(1)
PY
  )
else
probe=$(
  cat <<'PY'
import sys
import urllib.error
import urllib.request


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


code, body = get("http://127.0.0.1:8000/readyz")
print("readyz", code, body[:300])
code_d, body_d = get("http://127.0.0.1:8099/health")
print("decider", code_d, body_d[:200])
sys.exit(0 if code == 200 and code_d == 200 else 1)
PY
)
fi
if ! $compose exec -T api python -c "$probe"; then
  status=1
fi

if [[ ${1:-} == --public ]]; then
  echo "== public edge"
  curl -fsS -o /dev/null -w 'https://%{url_effective} -> %{http_code}\n' \
    "https://${CSO_DOMAIN}/healthz" || status=1
fi

exit "$status"
