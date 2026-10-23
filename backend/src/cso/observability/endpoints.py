"""`GET /metrics`: plain-text counters for the host's own agent, loopback only.

Not part of the public contract (`include_in_schema=False`) and not proxied by Caddy, which only
forwards `/api` and `/healthz`. A request is served only when its socket peer is a loopback address
and it carries no forwarding header; anything else gets a 403 problem, so the counters are never
visible to the internet even if a proxy rule changes.
"""

from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from cso.api.problems import ForbiddenError
from cso.observability.metrics import METRICS

router = APIRouter()
_FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip")


def is_loopback_request(request: Request) -> bool:
    """True for a direct connection from this host (no proxy hop)."""
    if any(h in request.headers for h in _FORWARD_HEADERS):
        return False
    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    """The registry in Prometheus text format; 403 unless the caller is on this host."""
    if not is_loopback_request(request):
        raise ForbiddenError("Metrics are only available from the host itself.")
    return PlainTextResponse(METRICS.render_text(), media_type="text/plain; version=0.0.4")
