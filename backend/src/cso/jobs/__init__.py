"""Durable background jobs: queue, worker, reaper and the analysis pipeline."""

from cso.jobs.deps import (
    DeciderNotConfigured,
    Deps,
    LiveOsmProvider,
    OsmSourceProvider,
    PanelDecider,
    ReplayOsmProvider,
    UnavailableDecider,
    build_deps,
    default_fixtures_dir,
)
from cso.jobs.enqueue import EnqueueResult, enqueue_analysis, enqueue_changeset, enqueue_draft
from cso.jobs.errors import (
    JobCancelled,
    JobError,
    LeaseLost,
    PermanentJobError,
    TransientJobError,
    classify,
)
from cso.jobs.handlers import Handler, HandlerRegistry, JobContext, default_registry
from cso.jobs.reaper import reap_once, reaper_loop
from cso.jobs.runtime import EmbeddedWorker, run_worker_cli
from cso.jobs.states import (
    ANALYZE_STEPS,
    HARD_CAP_S,
    RETRY_BACKOFF_S,
    backoff_seconds,
    can_transition,
    is_terminal,
)
from cso.jobs.worker import JobOutcome, Worker

__all__ = [
    "ANALYZE_STEPS",
    "HARD_CAP_S",
    "RETRY_BACKOFF_S",
    "DeciderNotConfigured",
    "Deps",
    "EmbeddedWorker",
    "EnqueueResult",
    "Handler",
    "HandlerRegistry",
    "JobCancelled",
    "JobContext",
    "JobError",
    "JobOutcome",
    "LeaseLost",
    "LiveOsmProvider",
    "OsmSourceProvider",
    "PanelDecider",
    "PermanentJobError",
    "ReplayOsmProvider",
    "TransientJobError",
    "UnavailableDecider",
    "Worker",
    "backoff_seconds",
    "build_deps",
    "can_transition",
    "classify",
    "default_fixtures_dir",
    "default_registry",
    "enqueue_analysis",
    "enqueue_changeset",
    "enqueue_draft",
    "is_terminal",
    "reap_once",
    "reaper_loop",
    "run_worker_cli",
]
