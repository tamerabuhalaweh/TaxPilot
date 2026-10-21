"""Sprint 1 unit tests: password/email helpers, config guards. No services needed."""

import pytest

from app.config import Settings
from app.security import hash_password, normalize_email, validate_password, verify_password


def test_password_roundtrip_and_wrong_rejected():
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("wrong password here!", stored) is False
    assert stored != "correct horse battery staple"


def test_password_policy():
    with pytest.raises(ValueError):
        validate_password("short")
    validate_password("long enough passphrase")
    with pytest.raises(ValueError):
        validate_password("x" * 129)


def test_email_normalization_and_rejection():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"
    with pytest.raises(ValueError):
        normalize_email("not-an-email")


def test_dev_token_exposure_forced_off_in_production():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@db:5432/t",
            redis_url="redis://localhost:6379/0",
            cors_allowed_origins=["https://app.example.com"],
            auth_expose_tokens=True,
        )


def test_public_registration_flag_parses():
    assert Settings().allow_public_registration is True
    assert Settings(allow_public_registration=False).allow_public_registration is False


def test_edge_secret_requires_enough_entropy():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(api_edge_secret="too-short")
    assert Settings(api_edge_secret="x" * 32).api_edge_secret == "x" * 32


def test_registration_guard_returns_403_without_opening_store(monkeypatch):
    from fastapi.testclient import TestClient

    from app.deps import settings_singleton
    from app.main import create_app

    monkeypatch.setattr(
        "app.routers.auth.settings_singleton",
        lambda: Settings(allow_public_registration=False),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "long enough passphrase", "firm_name": "Firm"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
    settings_singleton.cache_clear()
