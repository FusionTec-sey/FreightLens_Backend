import os

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test"
)

from auth.config import validate_security_settings


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
def test_deployed_environment_requires_every_security_secret(environment):
    with pytest.raises(ValueError) as exc_info:
        validate_security_settings(
            environment,
            {
                "JWT_SECRET_KEY": "set",
                "MEDIA_SIGNING_KEY": "",
                "CMA_CGM_WEBHOOK_SECRET": "",
            },
        )

    message = str(exc_info.value)
    assert "MEDIA_SIGNING_KEY" in message
    assert "CMA_CGM_WEBHOOK_SECRET" in message


def test_production_accepts_complete_security_configuration():
    validate_security_settings(
        "production",
        {
            "JWT_SECRET_KEY": "jwt",
            "MEDIA_SIGNING_KEY": "media",
            "CMA_CGM_WEBHOOK_SECRET": "webhook",
        },
    )
