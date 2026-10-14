"""EP-04C1 durable-jobs pure unit tests (no services required)."""

from app.jobs import (
    RetryableError,
    TerminalError,
    WakeupBus,
    fingerprint_payload,
    new_worker_id,
)


def test_fingerprint_deterministic_and_order_insensitive() -> None:
    assert fingerprint_payload({"b": 1, "a": [1, 2]}) == fingerprint_payload({"a": [1, 2], "b": 1})
    assert len(fingerprint_payload({})) == 64


def test_fingerprint_rejects_non_dict_oversize_and_unserializable() -> None:
    import pytest

    with pytest.raises(ValueError):
        fingerprint_payload(["not", "a", "dict"])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        fingerprint_payload({"huge": "x" * 70000})
    with pytest.raises(ValueError):
        fingerprint_payload({"bad": object()})


def test_worker_ids_unique() -> None:
    assert new_worker_id() != new_worker_id()


def test_handler_error_types_distinct() -> None:
    assert issubclass(RetryableError, Exception) and issubclass(TerminalError, Exception)
    assert not issubclass(RetryableError, TerminalError)


def test_wakeup_bus_without_redis_fails_soft() -> None:
    bus = WakeupBus(None)
    assert bus.notify("job-1") is False
    assert bus.wait(0.01) is None
