"""Session baseline: repair schema debris before any integration test runs.

Developers routinely interrupt runs mid-migration; without this, the first test
to touch the ledger inherits whatever state was left behind. This fixture runs
migrate() once per session (idempotent), so every module starts from a fully
migrated schema. Gating mirrors the modules: hard failure under
REQUIRE_SERVICES=1, documented skip otherwise.
"""

import os

import pytest

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"


@pytest.fixture(scope="session", autouse=True)
def _baseline_schema():  # type: ignore[no-untyped-def]
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        if REQUIRE_SERVICES:
            pytest.fail("DATABASE_URL is required when REQUIRE_SERVICES=1")
        pytest.skip("DATABASE_URL not set (documented optional local mode)")
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        from db.migrate import migrate

        migrate(url)
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"baseline migrate failed with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(
            f"baseline migrate unreachable (documented optional local mode): {exc}"
        )
    yield
