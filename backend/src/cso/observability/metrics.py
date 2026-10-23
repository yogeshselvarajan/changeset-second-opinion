"""In-process counters and histograms with a plain-text exposition.

A tiny thread-safe registry: enough for one API process plus its embedded worker. The text format
follows the Prometheus exposition convention, so a CloudWatch agent or a scraper can read it, but
nothing here depends on either. Counts are lost on restart, which is acceptable for operational
signals; anything that must survive a restart (the daily caps) is recomputed from the database.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

LATENCY_BUCKETS_MS: tuple[float, ...] = (50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000)

Labels = tuple[tuple[str, str], ...]


def _key(labels: Mapping[str, object]) -> Labels:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: Labels, extra: Iterable[tuple[str, str]] = ()) -> str:
    pairs = [*labels, *extra]
    if not pairs:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in pairs) + "}"


@dataclass
class _Histogram:
    buckets: tuple[float, ...]
    counts: list[int] = field(default_factory=list)
    total: float = 0.0
    n: int = 0

    def __post_init__(self) -> None:
        self.counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self.n += 1
        self.total += value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.counts[i] += 1


class Metrics:
    """Counters and histograms keyed by name and labels; safe to call from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, float]] = {}
        self._histograms: dict[str, dict[Labels, _Histogram]] = {}

    def inc(self, name: str, amount: float = 1.0, **labels: object) -> None:
        """Add to a counter."""
        with self._lock:
            series = self._counters.setdefault(name, {})
            key = _key(labels)
            series[key] = series.get(key, 0.0) + amount

    def observe(
        self,
        name: str,
        value: float,
        *,
        buckets: tuple[float, ...] = LATENCY_BUCKETS_MS,
        **labels: object,
    ) -> None:
        """Record a value in a histogram (milliseconds by default)."""
        with self._lock:
            series = self._histograms.setdefault(name, {})
            key = _key(labels)
            hist = series.get(key)
            if hist is None:
                hist = series[key] = _Histogram(buckets)
            hist.observe(value)

    def counter(self, name: str, **labels: object) -> float:
        """Current value of one counter series (0 when unseen)."""
        with self._lock:
            return self._counters.get(name, {}).get(_key(labels), 0.0)

    def total(self, name: str) -> float:
        """Sum of a counter over all label sets."""
        with self._lock:
            return sum(self._counters.get(name, {}).values())

    def histogram_count(self, name: str, **labels: object) -> int:
        """Number of observations in one histogram series."""
        with self._lock:
            hist = self._histograms.get(name, {}).get(_key(labels))
            return hist.n if hist else 0

    def snapshot(self) -> dict[str, object]:
        """A JSON-friendly copy of everything recorded."""
        with self._lock:
            return {
                "counters": {
                    name: {dict(k).__repr__(): v for k, v in series.items()}
                    for name, series in self._counters.items()
                },
                "histograms": {
                    name: {
                        dict(k).__repr__(): {"count": h.n, "sum": h.total}
                        for k, h in series.items()
                    }
                    for name, series in self._histograms.items()
                },
            }

    def render_text(self) -> str:
        """Plain-text exposition (counters, then histogram buckets, sums and counts)."""
        lines: list[str] = []
        with self._lock:
            for name in sorted(self._counters):
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(self._counters[name].items()):
                    lines.append(f"{name}{_fmt_labels(labels)} {value:g}")
            for name in sorted(self._histograms):
                lines.append(f"# TYPE {name} histogram")
                for labels, hist in sorted(self._histograms[name].items()):
                    for bound, count in zip(hist.buckets, hist.counts, strict=True):
                        lines.append(
                            f"{name}_bucket{_fmt_labels(labels, [('le', f'{bound:g}')])} {count}"
                        )
                    lines.append(f"{name}_bucket{_fmt_labels(labels, [('le', '+Inf')])} {hist.n}")
                    lines.append(f"{name}_sum{_fmt_labels(labels)} {hist.total:g}")
                    lines.append(f"{name}_count{_fmt_labels(labels)} {hist.n}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        """Forget everything (tests)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


METRICS = Metrics()

# Metric names, kept in one place so instrumentation and tests agree.
ANALYSES = "cso_analyses_total"  # labels: lane, status
DECIDER_CALLS = "cso_decider_calls_total"  # labels: outcome
DECIDER_LATENCY = "cso_decider_latency_ms"
DRAFT_REQUESTS = "cso_draft_requests_total"
BEDROCK_CALLS = "cso_bedrock_calls_total"  # labels: outcome
BEDROCK_TOKENS = "cso_bedrock_tokens_total"  # labels: direction
TEMPLATE_FALLBACKS = "cso_template_fallbacks_total"  # labels: reason
JOB_FAILURES = "cso_job_failures_total"  # labels: kind, code
HTTP_REQUESTS = "cso_http_requests_total"  # labels: method, route, status
HTTP_LATENCY = "cso_http_request_duration_ms"  # labels: route
BUDGET_REJECTIONS = "cso_budget_rejections_total"  # labels: cap
