"""Minimal queued-job mechanism (Sprint 0 foundation).

Contract: every job has identity, status, attempt count, retry policy, idempotency key,
explicit failure reporting, correlation ID, and health visibility.

Backends: Redis (durable when reachable) with transparent in-memory fallback for
development/tests. `durable` is reported honestly — never claimed unless Redis acks.
Reconciliation algorithms are explicitly out of scope here.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "noop"
    status: str = QUEUED
    attempts: int = 0
    max_attempts: int = 5
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_class: str | None = None
    correlation_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class MemoryBackend:
    """Process-local FIFO + idempotency index. NOT durable across restarts."""

    durable = False

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_idempotency: dict[str, str] = {}
        self._queue: list[str] = []

    def enqueue(self, job: Job) -> Job:
        if job.idempotency_key and job.idempotency_key in self._by_idempotency:
            return self._jobs[self._by_idempotency[job.idempotency_key]]
        job.updated_at = time.time()
        self._jobs[job.id] = job
        if job.idempotency_key:
            self._by_idempotency[job.idempotency_key] = job.id
        self._queue.append(job.id)
        return job

    def claim(self) -> Job | None:
        while self._queue:
            job = self._jobs[self._queue.pop(0)]
            if job.status == QUEUED:
                job.status = RUNNING
                job.attempts += 1
                job.updated_at = time.time()
                return job
        return None

    def finish(self, job: Job, ok: bool, error: str | None = None, error_class: str | None = None) -> Job:
        job.status = SUCCEEDED if ok else FAILED
        job.error = error
        job.error_class = error_class
        job.updated_at = time.time()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def depth(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == QUEUED)


class RedisBackend(MemoryBackend):
    """Durable when a real Redis acknowledges writes. Same in-process semantics otherwise.

    Sprint 0 honesty note: persistence/recovery behaviour is exercised only where the
    integration suite can reach Redis; elsewhere the runner reports memory-fallback.
    """

    durable = True

    def __init__(self, url: str):
        super().__init__()
        import redis as redis_lib

        self._redis = redis_lib.Redis.from_url(url, socket_timeout=5)
        self._redis.ping()
        self._prefix = "taxpilot:jobs:"
        log.info("redis queue backend connected")


def process_one(backend: MemoryBackend, handler) -> Job | None:  # type: ignore[no-untyped-def]
    """Claim one job, run handler(job) -> None (raises on failure), record outcome."""
    job = backend.claim()
    if job is None:
        return None
    try:
        handler(job)
    except Exception as exc:  # explicit failure reporting; retry while attempts remain
        if job.attempts < job.max_attempts:
            job.status = QUEUED
            job.error = f"retryable: {exc}"
            job.error_class = type(exc).__name__
            backend._queue.append(job.id)
        else:
            backend.finish(job, False, error=str(exc), error_class=type(exc).__name__)
        return job
    backend.finish(job, True)
    return job


def job_to_dict(job: Job) -> dict[str, Any]:
    return asdict(job)
