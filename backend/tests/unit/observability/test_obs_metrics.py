"""Counters, histograms, the text exposition, request counting and the loopback-only endpoint."""

from __future__ import annotations

import threading

import httpx

from cso.observability.metrics import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    METRICS,
    Metrics,
)


def test_counters_accumulate_per_label_set() -> None:
    m = Metrics()
    m.inc("things_total", lane="a")
    m.inc("things_total", lane="a")
    m.inc("things_total", 3, lane="b")
    assert m.counter("things_total", lane="a") == 2 and m.counter("things_total", lane="b") == 3
    assert m.counter("things_total", lane="zzz") == 0 and m.total("things_total") == 5


def test_label_order_does_not_matter() -> None:
    m = Metrics()
    m.inc("x", a="1", b="2")
    m.inc("x", b="2", a="1")
    assert m.counter("x", a="1", b="2") == 2


def test_histograms_count_and_sum_and_fill_cumulative_buckets() -> None:
    m = Metrics()
    for value in (40, 90, 600, 90000):
        m.observe("lat_ms", value, route="/r")
    assert m.histogram_count("lat_ms", route="/r") == 4
    text = m.render_text()
    assert 'lat_ms_bucket{route="/r",le="50"} 1' in text
    assert 'lat_ms_bucket{route="/r",le="100"} 2' in text
    assert 'lat_ms_bucket{route="/r",le="1000"} 3' in text
    assert 'lat_ms_bucket{route="/r",le="+Inf"} 4' in text
    assert 'lat_ms_count{route="/r"} 4' in text and 'lat_ms_sum{route="/r"} 90730' in text


def test_text_format_has_type_lines_and_escapes_label_values() -> None:
    m = Metrics()
    m.inc("c_total", code='he said "no"\nthen left\\')
    text = m.render_text()
    assert "# TYPE c_total counter" in text
    assert r'code="he said \"no\"\nthen left\\"' in text
    assert Metrics().render_text() == ""


def test_snapshot_is_json_friendly() -> None:
    import json

    m = Metrics()
    m.inc("a_total", k="v")
    m.observe("b_ms", 5, k="v")
    assert json.loads(json.dumps(m.snapshot()))["counters"]["a_total"]


def test_updates_from_many_threads_are_not_lost() -> None:
    m = Metrics()

    def work() -> None:
        for _ in range(2000):
            m.inc("hits_total", worker="w")
            m.observe("lat_ms", 1.0, worker="w")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.counter("hits_total", worker="w") == 16000
    assert m.histogram_count("lat_ms", worker="w") == 16000


def test_reset_forgets_everything() -> None:
    m = Metrics()
    m.inc("a")
    m.reset()
    assert m.total("a") == 0 and m.render_text() == ""


async def test_requests_are_counted_by_route_template_and_status(client) -> None:
    await client.get("/healthz")
    await client.get("/healthz")
    await client.get("/readyz")
    assert METRICS.counter(HTTP_REQUESTS, method="GET", route="/healthz", status=200) == 2
    assert METRICS.histogram_count(HTTP_LATENCY, route="/healthz") == 2
    assert METRICS.total(HTTP_REQUESTS) == 3


async def test_metrics_endpoint_serves_plain_text_to_the_host_itself(client) -> None:
    await client.get("/healthz")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "cso_http_requests_total" in response.text


async def test_metrics_endpoint_refuses_a_remote_peer(app, make_client) -> None:
    async with make_client(app, client=("203.0.113.9", 4000)) as remote:
        response = await remote.get("/metrics")
    assert response.status_code == 403
    assert "cso_http" not in response.text
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_metrics_endpoint_refuses_anything_that_came_through_a_proxy(client) -> None:
    for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "X-Forwarded-Host"):
        response = await client.get("/metrics", headers={header: "198.51.100.7"})
        assert response.status_code == 403, header


async def test_metrics_endpoint_is_not_part_of_the_public_contract(client) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert "/metrics" not in spec["paths"]


def test_metrics_helper_is_importable_from_the_package() -> None:
    assert isinstance(METRICS, Metrics) and isinstance(httpx.__version__, str)
