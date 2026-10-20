"""REC-UI-01 synthetic demo fixtures + engine run (pure, no DB).

Pins the deterministic scenario contract the demo boundary and the web journey
depend on: JOD reconciles to a 100.000 difference with a linked credit note and
reversal, and USD is inconclusive because of a duplicate. Every row carries
evidence provenance, and payloads are always labelled synthetic.
"""

from app.config import Settings
from app.demo.fixtures import (
    FIXTURES,
    SYNTHETIC_LABEL,
    get_fixture,
)
from app.demo.service import run_fixture, to_response

FIXTURE_ID = "synthetic-sales-gl-v1"


def test_registry_exposes_the_scenarios() -> None:
    assert list(FIXTURES) == [FIXTURE_ID, "synthetic-sales-gl-v2"]
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    assert fixture.policy.currency_scope == ("JOD", "USD")
    assert get_fixture("does-not-exist") is None


def test_second_fixture_is_a_distinct_calculation() -> None:
    fixture = get_fixture("synthetic-sales-gl-v2")
    assert fixture is not None
    report, findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    difference = next(o for o in report.outcomes if o.kind == "DIFFERENCE")
    assert str(difference.delta) == "50.000"
    assert difference.currency == "JOD"
    assert report.counts == {"DIFFERENCE": 1}
    assert findings.summary["total"] == 1


def test_run_produces_the_expected_outcomes() -> None:
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    report, findings = run_fixture(fixture, tenant_id="tenant-a", client_id="client-a")
    assert report.blocked is False
    assert report.counts == {
        "REVERSAL_NOTED": 1,
        "CREDIT_NOTE_LINKED": 1,
        "DUPLICATE_SALES": 1,
        "DIFFERENCE": 1,
        "INCONCLUSIVE_COVERAGE": 1,
    }
    difference = next(o for o in report.outcomes if o.kind == "DIFFERENCE")
    assert str(difference.sales_total) == "3500.000"
    assert str(difference.gl_total) == "3400.000"
    assert str(difference.delta) == "100.000"
    assert difference.currency == "JOD"
    assert report.inconclusive is True
    assert report.inconclusive_reasons == ("COVERAGE_DUPLICATE",)
    assert findings.summary["review_required"] == 3
    assert findings.summary["informational"] == 2


def test_run_is_deterministic_and_tenant_independent() -> None:
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    first, first_findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    second, second_findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    assert first.fingerprint == second.fingerprint
    assert first_findings.fingerprint == second_findings.fingerprint


def test_every_finding_row_has_traceable_evidence() -> None:
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    _, findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    for item in findings.findings:
        assert item.evidence, f"finding {item.finding_id} has no evidence"
        for ref in item.evidence:
            assert ref.dataset_id.strip()
            assert ref.source.strip()
            assert ref.row_number > 0
            assert ref.role in ("sales", "gl")


def test_payload_is_always_labelled_synthetic() -> None:
    fixture = get_fixture(FIXTURE_ID)
    assert fixture is not None
    report, findings = run_fixture(fixture, tenant_id="t1", client_id="c1")
    response = to_response(fixture, report, findings)
    assert response.synthetic is True
    assert response.label == SYNTHETIC_LABEL
    assert "SYNTHETIC DEMO DATA" in response.label
    assert response.findings
    evidence_roles = {ref.role for item in response.findings for ref in item.evidence}
    assert evidence_roles == {"sales", "gl"}
    assert response.conclusion.status == "REVIEW_REQUIRED"
    assert response.conclusion.coverage.complete is False
    assert response.conclusion.coverage.currencies == ["USD"]
    assert response.conclusion.coverage.reasons == ["COVERAGE_DUPLICATE"]
    assert [(item.currency, item.outcome) for item in response.conclusion.currency_results] == [
        ("JOD", "DIFFERENCE"),
        ("USD", "INCONCLUSIVE_COVERAGE"),
    ]
    assert all(item.guidance for item in response.findings)


def test_demo_flag_is_off_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TAXPILOT_DEMO_RECON_ENABLED", raising=False)
    monkeypatch.delenv("DEMO_RECON_ENABLED", raising=False)
    assert Settings(environment="test").demo_recon_enabled is False


def test_production_forces_demo_off_even_when_enabled() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:p@db:5432/t",
        redis_url="redis://redis:6379/0",
        cors_allowed_origins=["https://app.example.com"],
        auth_expose_tokens=False,
        demo_recon_enabled=True,
    )
    assert settings.demo_recon_enabled is False
