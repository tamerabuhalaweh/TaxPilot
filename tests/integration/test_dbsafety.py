"""Negative tests for the destructive-database guard (TEST-SAFETY-01).

Pure unit tests: no database required, so they run everywhere including plain
CI. They prove the guard refuses every unsafe combination and accepts only
the fully opted-in designated disposable target.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety
from dbsafety import require_destructive_db

GOOD = "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot_test"


def _opt_in(monkeypatch, value="1"):  # type: ignore[no-untyped-def]
    monkeypatch.setenv(dbsafety.OPT_IN_VAR, value)
    monkeypatch.delenv(dbsafety.REMOTE_OVERRIDE_VAR, raising=False)


def test_accepts_designated_disposable_target(monkeypatch):  # type: ignore[no-untyped-def]
    _opt_in(monkeypatch)
    assert require_destructive_db(GOOD) == "taxpilot_test"
    # CI service hostname is an accepted local/CI host.
    assert (
        require_destructive_db(
            "postgresql+psycopg://taxpilot:taxpilot@postgres:5432/taxpilot_test"
        )
        == "taxpilot_test"
    )


def test_refuses_without_opt_in(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.delenv(dbsafety.OPT_IN_VAR, raising=False)
    with pytest.raises(ValueError, match="opt-in is absent"):
        require_destructive_db(GOOD)


def test_refuses_production_like_name_even_with_opt_in(monkeypatch):  # type: ignore[no-untyped-def]
    _opt_in(monkeypatch)
    for url in (
        "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot",
        "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/postgres",
        "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/",
    ):
        with pytest.raises(ValueError, match="not a designated test database"):
            require_destructive_db(url)


def test_refuses_remote_host_without_override(monkeypatch):  # type: ignore[no-untyped-def]
    _opt_in(monkeypatch)
    with pytest.raises(ValueError, match="not a local/CI database host"):
        require_destructive_db(
            "postgresql+psycopg://taxpilot:taxpilot@staging.internal:5432/taxpilot_test"
        )
    # Deliberate two-switch override restores access (auditable, explicit).
    monkeypatch.setenv(dbsafety.REMOTE_OVERRIDE_VAR, "1")
    assert (
        require_destructive_db(
            "postgresql+psycopg://taxpilot:taxpilot@staging.internal:5432/taxpilot_test"
        )
        == "taxpilot_test"
    )


def test_destructive_url_missing_fails_closed_under_require_services(monkeypatch):  # type: ignore[no-untyped-def]
    # pytest.fail raises Failed (a BaseException, not an Exception), so assert
    # refusal explicitly instead of via pytest.raises(Exception, ...).
    monkeypatch.delenv(dbsafety.URL_VAR, raising=False)
    monkeypatch.setenv("REQUIRE_SERVICES", "1")
    try:
        dbsafety.destructive_url()
    except BaseException as exc:
        assert "refuse to run without a dedicated" in str(exc)
    else:
        raise AssertionError("destructive_url() did not refuse a missing URL")
