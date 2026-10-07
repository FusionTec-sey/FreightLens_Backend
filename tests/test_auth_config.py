import os

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test"
)

from auth.config import (
    read_boolean_setting,
    required_security_secrets,
    validate_security_settings,
)


def test_development_allows_missing_secrets():
    validate_security_settings(
        "development",
        {
            "JWT_SECRET_KEY": "",
            "MEDIA_SIGNING_KEY": "",
            "CMA_CGM_WEBHOOK_SECRET": "",
        },
    )


@pytest.mark.parametrize("environment", ["staging", "production", "PRODUCTION"])
def test_deployed_environment_requires_core_security_secrets(environment):
    with pytest.raises(ValueError) as exc_info:
        validate_security_settings(
            environment,
            {
                "JWT_SECRET_KEY": "set",
                "MEDIA_SIGNING_KEY": "",
            },
        )

    message = str(exc_info.value)
    assert "MEDIA_SIGNING_KEY" in message


def test_disabled_webhook_does_not_require_secret_in_production():
    secrets = required_security_secrets("jwt", "media", False, "")

    validate_security_settings("production", secrets)

    assert "CMA_CGM_WEBHOOK_SECRET" not in secrets


def test_enabled_webhook_requires_secret_in_production():
    secrets = required_security_secrets("jwt", "media", True, "")

    with pytest.raises(ValueError) as exc_info:
        validate_security_settings("production", secrets)

    assert "CMA_CGM_WEBHOOK_SECRET" in str(exc_info.value)


def test_production_accepts_complete_security_configuration():
    secrets = required_security_secrets(
        "jwt",
        "media",
        True,
        "webhook",
    )

    validate_security_settings("production", secrets)


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_boolean_setting_accepts_true_values(monkeypatch, value):
    monkeypatch.setenv("TEST_FEATURE_ENABLED", value)
    assert read_boolean_setting("TEST_FEATURE_ENABLED") is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off", ""])
def test_boolean_setting_accepts_false_values(monkeypatch, value):
    monkeypatch.setenv("TEST_FEATURE_ENABLED", value)
    assert read_boolean_setting("TEST_FEATURE_ENABLED", default=True) is False


def test_boolean_setting_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("TEST_FEATURE_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="TEST_FEATURE_ENABLED must be a boolean value"):
        read_boolean_setting("TEST_FEATURE_ENABLED")
