"""Fail-closed guard for destructive database integration tests (TEST-SAFETY-01).

Destructive operations — DROP SCHEMA/TABLE ... CASCADE, ALTER/DROP of shared
constraints, DELETEs against the migration ledger — must only ever execute
against a dedicated disposable test database, never staging, production, or a
shared development database.

A destructive test MUST resolve its target via :func:`destructive_url` and pass
it through :func:`require_destructive_db` before touching the database. The
guard raises :class:`ValueError` unless ALL of the following hold:

1. Explicit opt-in: ``TAXPILOT_ALLOW_DESTRUCTIVE_TESTS=1`` is set. The default
   (unset/any other value) refuses, so a developer who never opted in can
   never destroy anything.
2. Designated database name: the connected database name ends with ``_test``
   and is not a system database. Production databases are never named
   ``*_test``; anything else is refused.
3. Non-remote host: the host is loopback or a well-known CI service name
   (``localhost``, ``127.0.0.1``, ``::1``, ``postgres``, ``db``) unless the
   separate ``TAXPILOT_ALLOW_REMOTE_DESTRUCTIVE=1`` override is set. This makes
   pointing the suite at a cloud staging host a deliberate two-switch action.

Deliberately NOT covered here: the session ``conftest`` baseline ``migrate()``
and the application startup path. Those are idempotent, checksum-gated,
ledger-gated forward migrations — the system's own purpose — not test
destruction, and they run against ``DATABASE_URL`` as designed.

CI wires ``TAXPILOT_DESTRUCTIVE_DATABASE_URL`` to a freshly created
``taxpilot_test`` database inside the disposable postgres service container
(see ``.github/workflows/ci.yml``); locally, create an equivalent scratch
database (``CREATE DATABASE taxpayer_test``) and export the same variables.
"""

import os
from urllib.parse import urlparse

OPT_IN_VAR = "TAXPILOT_ALLOW_DESTRUCTIVE_TESTS"
URL_VAR = "TAXPILOT_DESTRUCTIVE_DATABASE_URL"
REMOTE_OVERRIDE_VAR = "TAXPILOT_ALLOW_REMOTE_DESTRUCTIVE"
DESIGNATED_SUFFIX = "_test"
SYSTEM_DATABASES = frozenset({"postgres", "template0", "template1"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "db"})


def _to_libpq(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url


def destructive_url() -> str:
    """Return the dedicated disposable-database URL, or skip/fail when unset.

    Unset locally means "destructive tests do not run here" (skip, consistent
    with the suite's documented optional local mode); unset with
    ``REQUIRE_SERVICES=1`` (CI) is a hard failure so the safety wiring can
    never silently go missing.
    """
    url = os.environ.get(URL_VAR, "")
    if not url:
        import pytest

        message = (
            f"{URL_VAR} is not set: destructive integration tests refuse to "
            "run without a dedicated disposable test database"
        )
        if os.environ.get("REQUIRE_SERVICES") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return url


def require_destructive_db(url: str) -> str:
    """Fail closed unless ``url`` is an explicitly opted-in designated test DB.

    Returns the verified database name. Raises :class:`ValueError` listing
    every unmet condition — callers must treat this as a hard stop, never a
    fallback to another database.
    """
    problems: list[str] = []
    if os.environ.get(OPT_IN_VAR) != "1":
        problems.append(f"{OPT_IN_VAR}=1 opt-in is absent")
    try:
        parts = urlparse(_to_libpq(url))
        dbname = (parts.path or "").lstrip("/").split("?")[0]
        host = (parts.hostname or "").lower()
    except Exception:
        dbname, host = "", ""
    if (
        not dbname
        or not dbname.endswith(DESIGNATED_SUFFIX)
        or dbname in SYSTEM_DATABASES
    ):
        problems.append(
            f"database {dbname!r} is not a designated test database "
            f"(name must end with {DESIGNATED_SUFFIX!r})"
        )
    if host not in LOCAL_HOSTS and os.environ.get(REMOTE_OVERRIDE_VAR) != "1":
        problems.append(
            f"host {host!r} is not a local/CI database host "
            f"(set {REMOTE_OVERRIDE_VAR}=1 to override deliberately)"
        )
    if problems:
        raise ValueError(
            "refusing destructive database operation: " + "; ".join(problems)
        )
    return dbname
