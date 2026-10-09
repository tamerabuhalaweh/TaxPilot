"""Worker entrypoint: python -m worker.runner (from apps/api). Processes queued jobs in a loop.

Sprint 0 supports the `noop` and `echo` kinds only — enough to prove queue → process →
status visibility end to end. Reconciliation handlers arrive with approved contracts.
"""

import logging
import time

from app.config import get_settings
from app.logging_setup import setup_logging
from worker.jobs import MemoryBackend, RedisBackend, process_one

log = logging.getLogger("taxpilot.worker")


def make_backend():  # type: ignore[no-untyped-def]
    settings = get_settings()
    try:
        backend = RedisBackend(settings.redis_url)
        log.info("worker using redis backend")
        return backend, "up"
    except Exception as exc:
        log.warning("redis unavailable, memory-fallback active: %s", exc)
        return MemoryBackend(), "memory-fallback"


def handle(job):  # type: ignore[no-untyped-def]
    if job.kind in ("noop", "echo"):
        return
    raise ValueError(f"unsupported job kind: {job.kind}")


def main() -> None:
    setup_logging(get_settings().log_level)
    backend, _ = make_backend()
    log.info("worker started")
    while True:
        job = process_one(backend, handle)
        if job is None:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
