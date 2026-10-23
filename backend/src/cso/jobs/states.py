"""Job state machine and the timing constants of the worker."""

from __future__ import annotations

from cso.domain.enums import JobKind, JobStatus

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.QUEUED, JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

POLL_INTERVAL_S = 1.0
REAPER_INTERVAL_S = 60.0
LEASE_SECONDS = 300
DEFAULT_CONCURRENCY = 2  # fetch stages overlap; Decider calls are still one at a time

# Backoff before attempt 2, 3 and so on after a transient failure, in seconds.
RETRY_BACKOFF_S: tuple[float, ...] = (5.0, 20.0, 60.0)
JITTER = 0.2  # +/- 20 %

# Outer bound for one attempt; inner timeouts (OSM 8 s call / 20 s stage, Decider 45 s / 90 s) are
# shorter. Both are well under the lease, so a running job never needs a background heartbeat.
HARD_CAP_S: dict[JobKind, float] = {JobKind.ANALYZE: 120.0, JobKind.DRAFT: 60.0}

STEP_FETCH = "fetch_evidence"
STEP_SNAPSHOT = "snapshot"
STEP_DECIDE = "decide"
STEP_PERSIST = "persist"
STEP_DRAFT = "draft"
ANALYZE_STEPS = (STEP_FETCH, STEP_SNAPSHOT, STEP_DECIDE, STEP_PERSIST)


def is_terminal(status: JobStatus) -> bool:
    """True for succeeded, failed and cancelled."""
    return not TRANSITIONS[status]


def can_transition(current: JobStatus, new: JobStatus) -> bool:
    """Whether the state machine allows `current -> new`."""
    return new in TRANSITIONS[current]


def assert_transition(current: JobStatus, new: JobStatus) -> None:
    """Raise ValueError for a transition the state machine does not allow."""
    if not can_transition(current, new):
        raise ValueError(f"job cannot move from {current.value} to {new.value}")


def backoff_seconds(attempt: int, rand: float) -> float:
    """Delay before the next attempt after `attempt` failed ones; `rand` in [0, 1) sets jitter."""
    base = RETRY_BACKOFF_S[min(max(attempt, 1), len(RETRY_BACKOFF_S)) - 1]
    return base * (1.0 + JITTER * (2.0 * rand - 1.0))
