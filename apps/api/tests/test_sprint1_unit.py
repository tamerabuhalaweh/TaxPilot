"""Sprint 1 unit tests: password/email helpers, config guards. No services needed."""

import secrets

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


STRONG_EDGE_SECRET = secrets.token_urlsafe(48)


def hosted_demo_settings(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "environment": "staging",
        "demo_recon_enabled": True,
        "allow_public_registration": False,
        "api_edge_secret": STRONG_EDGE_SECRET,
    }
    values.update(overrides)
    return Settings(**values)


def test_edge_secret_shape_outside_hosted_demo():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(api_edge_secret="too-short")
    settings = Settings(api_edge_secret="x" * 32)
    assert settings.api_edge_secret_value == "x" * 32


def test_staging_demo_accepts_only_fail_closed_configuration():
    settings = hosted_demo_settings()
    assert settings.demo_recon_enabled is True
    assert settings.allow_public_registration is False
    assert settings.auth_expose_tokens is False
    assert settings.api_edge_secret_value == STRONG_EDGE_SECRET
    assert settings.cookie_secure is True


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"allow_public_registration": True}, "ALLOW_PUBLIC_REGISTRATION"),
        ({"api_edge_secret": None}, "API_EDGE_SECRET is required"),
        ({"api_edge_secret": "a" * 64}, "too repetitive"),
        ({"api_edge_secret": "short"}, "64-128 URL-safe"),
        ({"auth_expose_tokens": True}, "AUTH_EXPOSE_TOKENS"),
    ],
)
def test_staging_demo_rejects_unsafe_configuration(overrides, match):  # type: ignore[no-untyped-def]
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=match):
        hosted_demo_settings(**overrides)


def test_staging_demo_guard_is_narrow_to_enabled_demo():
    settings = Settings(
        environment="staging",
        demo_recon_enabled=False,
        allow_public_registration=True,
    )
    assert settings.allow_public_registration is True
    assert settings.api_edge_secret_value is None


def test_local_demo_defaults_remain_permissive():
    for environment in ("development", "test"):
        settings = Settings(environment=environment, demo_recon_enabled=True)  # type: ignore[arg-type]
        assert settings.allow_public_registration is True
        assert settings.api_edge_secret_value is None


def test_production_forces_demo_off_without_hosted_defaults():
    settings = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:p@db:5432/t",
        redis_url="redis://redis:6379/0",
        cors_allowed_origins=["https://app.example.com"],
        demo_recon_enabled=True,
        allow_public_registration=True,
    )
    assert settings.demo_recon_enabled is False


def test_edge_secret_is_masked_in_repr_and_errors():
    from pydantic import ValidationError

    settings = hosted_demo_settings()
    assert STRONG_EDGE_SECRET not in repr(settings)
    assert STRONG_EDGE_SECRET not in str(settings)

    weak = "B" * 64
    with pytest.raises(ValidationError) as exc:
        hosted_demo_settings(api_edge_secret=weak)
    assert weak not in str(exc.value)


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


def test_staging_demo_app_wires_the_fail_closed_gate(monkeypatch):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.deps import settings_singleton
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("TAXPILOT_DEMO_RECON_ENABLED", "1")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "false")
    monkeypatch.setenv("API_EDGE_SECRET", STRONG_EDGE_SECRET)
    monkeypatch.delenv("AUTH_EXPOSE_TOKENS", raising=False)
    settings_singleton.cache_clear()
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/openapi.json").status_code == 403
        assert client.get("/openapi.json", headers={"X-TaxPilot-Edge": STRONG_EDGE_SECRET}).status_code == 200
    finally:
        settings_singleton.cache_clear()


def test_staging_demo_app_refuses_missing_edge_secret(monkeypatch):  # type: ignore[no-untyped-def]
    from pydantic import ValidationError

    from app.deps import settings_singleton
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("TAXPILOT_DEMO_RECON_ENABLED", "1")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "false")
    monkeypatch.delenv("API_EDGE_SECRET", raising=False)
    monkeypatch.delenv("AUTH_EXPOSE_TOKENS", raising=False)
    settings_singleton.cache_clear()
    try:
        with pytest.raises(ValidationError, match="API_EDGE_SECRET is required"):
            create_app()
    finally:
        settings_singleton.cache_clear()
