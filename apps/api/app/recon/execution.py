"""Reconciliation-run identity contracts (REC-SLICE-03).

Pure typed models connecting the deterministic engine (``reconcile`` /
``project``) to execution bookkeeping. A run is identified by its full input
scope: tenant, engagement, operation, caller idempotency key, and the exact
input versions + configuration. The same identity replays stably; the same
key with different inputs conflicts instead of merging; any version change
produces a new identity. No database, HTTP, or job-queue writes here — the
API layer owns persistence, and durable-job enqueue stays unwired until claim
supports operation scoping (documented blocker, fencing untouched).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from app.recon.findings import PROJECTION_VERSION

OPERATION = "rec.reconcile.v1"
DEFAULT_RULES_VERSION = "1"  # mirrors ReconcileRequest.tolerance-version default


@dataclass(frozen=True)
class RunDescriptor:
    """Canonical, hashable description of one requested reconciliation run."""

    tenant_id: str
    client_id: str
    engagement_id: str
    operation: str
    idempotency_key: str
    sales_dataset_version_id: str
    jofo_dataset_version_id: str
    rules_version: str
    projection_version: str
    period_start: date | None
    period_end: date | None
    jurisdiction_code: str | None


def _canonical(descriptor: RunDescriptor) -> str:
    payload = {
        "tenant": descriptor.tenant_id,
        "client": descriptor.client_id,
        "engagement": descriptor.engagement_id,
        "operation": descriptor.operation,
        "key": descriptor.idempotency_key,
        "sales_version": descriptor.sales_dataset_version_id,
        "jofo_version": descriptor.jofo_dataset_version_id,
        "rules": descriptor.rules_version,
        "projection": descriptor.projection_version,
        "period": [
            descriptor.period_start.isoformat() if descriptor.period_start else None,
            descriptor.period_end.isoformat() if descriptor.period_end else None,
        ],
        "jurisdiction": descriptor.jurisdiction_code,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_hash(descriptor: RunDescriptor) -> str:
    """Stable identity of the full input scope (hex sha256)."""
    if not isinstance(descriptor, RunDescriptor):
        raise TypeError(f"descriptor must be RunDescriptor, got {type(descriptor).__name__}")
    return hashlib.sha256(_canonical(descriptor).encode("utf-8")).hexdigest()


def source_set_fingerprint(
    sales_dataset_version_id: str,
    jofo_dataset_version_id: str,
    rules_version: str = DEFAULT_RULES_VERSION,
    projection_version: str = PROJECTION_VERSION,
) -> str:
    """Stable identity of the versioned input set alone (key-independent).

    Two runs over the same approved versions share this fingerprint even under
    different idempotency keys; any version change produces a new one.
    """
    for label, value in (
        ("sales_dataset_version_id", sales_dataset_version_id),
        ("jofo_dataset_version_id", jofo_dataset_version_id),
        ("rules_version", rules_version),
        ("projection_version", projection_version),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-blank string")
    canonical = json.dumps(
        {
            "sales_version": sales_dataset_version_id,
            "jofo_version": jofo_dataset_version_id,
            "rules": rules_version,
            "projection": projection_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
