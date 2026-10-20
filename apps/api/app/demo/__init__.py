"""REC-UI-01 restricted synthetic-demo reconciliation support.

Wholly invented, versioned, static fixtures plus dependency-free report
renderers for the accountant-facing walkthrough. Nothing here reads a
database, quarantine, or uploaded file, and nothing is persisted: the
restricted demo boundary rebuilds the scenario in memory and runs the
existing pure REC-005 engine over it.
"""

from app.demo.fixtures import (
    FIXTURES,
    SYNTHETIC_LABEL,
    SYNTHETIC_LABEL_ASCII,
    DemoFixture,
    get_fixture,
)

__all__ = [
    "FIXTURES",
    "SYNTHETIC_LABEL",
    "SYNTHETIC_LABEL_ASCII",
    "DemoFixture",
    "get_fixture",
]
