import os
import logging
from dotenv import load_dotenv

# Always load .env (without overriding existing container environment variables)
load_dotenv(override=False)

logger = logging.getLogger("auth.config")

DEPLOYED_ENVIRONMENTS = {"staging", "production"}


def read_boolean_setting(name: str, default: bool = False) -> bool:
    """Read a strict boolean environment setting."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def required_security_secrets(
    jwt_secret_key: str,
    media_signing_key: str,
    cma_cgm_webhook_enabled: bool,
    cma_cgm_webhook_secret: str,
) -> dict:
    """Return secrets required for the enabled production features."""
    secrets = {
        "JWT_SECRET_KEY": jwt_secret_key,
        "MEDIA_SIGNING_KEY": media_signing_key,
    }
    if cma_cgm_webhook_enabled:
        secrets["CMA_CGM_WEBHOOK_SECRET"] = cma_cgm_webhook_secret
    return secrets


def validate_security_settings(environment: str, secrets: dict) -> None:
    """Fail closed when a deployed environment is missing required secrets."""
    if environment.strip().lower() not in DEPLOYED_ENVIRONMENTS:
        return
    missing = sorted(name for name, value in secrets.items() if not value)
    if missing:
        raise ValueError(
            "Missing required security environment variables: " + ", ".join(missing)
        )

class Settings:
    HOST_IP = os.getenv("HOST_IP", "0.0.0.0")
    HOST_PORT = int(os.getenv("HOST_PORT", 9000))

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    MEDIA_SIGNING_KEY = os.getenv("MEDIA_SIGNING_KEY", "")

    # ── App Environment ────────────────────────────────────────────────────────
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

    # ── CORS Allowed Origins ───────────────────────────────────────────────────
    _raw_origins = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
    )
    ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _raw_origins.split(",") if o.strip()]

    # ── External Shipping APIs ────────────────────────────────────────────────
    CMA_CGM_API_KEY = os.getenv("CMA_CGM_API_KEY", "")
    CMA_CGM_CLIENT_ID = os.getenv("CMA_CGM_CLIENT_ID", "")
    CMA_CGM_SECRET = os.getenv("CMA_CGM_SECRET", "")
    CMA_CGM_TRACK_AND_TRACE_URL = os.getenv("CMA_CGM_TRACK_AND_TRACE_URL", "")
    CMA_CGM_SHIPEMENTS_URL = os.getenv("CMA_CGM_SHIPEMENTS_URL", "")
    CMA_CGM_TOKEN_URL = os.getenv("CMA_CGM_OAUTH", "")
    CMA_CGM_WEBHOOK_ENABLED = read_boolean_setting("CMA_CGM_WEBHOOK_ENABLED")
    CMA_CGM_WEBHOOK_SECRET = os.getenv("CMA_CGM_WEBHOOK_SECRET", "")

    MEARSK_CLIENT_ID = os.getenv("MEARSK_CLIENT_ID", "")
    MEARSK_SECRET = os.getenv("MEARSK_SECRET", "")
    MEARSK_TRACK_AND_TRACE_URL = os.getenv("MEARSK_TRACK_AND_TRACE_URL", "")
    MEARSK_SHIPMENTS_URL = os.getenv("MEARSK_SHIPMENTS_URL", "")
    MEARSK_TOKEN_URL = os.getenv("MEARSK_OAUTH", "")

    TRACKING_PROXY = os.getenv("TRACKING_PROXY", "")

    # ── Database ───────────────────────────────────────────────────────────────
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")

    # ── Security validation ───────────────────────────────────────────────────
    validate_security_settings(
        ENVIRONMENT,
        required_security_secrets(
            JWT_SECRET_KEY,
            MEDIA_SIGNING_KEY,
            CMA_CGM_WEBHOOK_ENABLED,
            CMA_CGM_WEBHOOK_SECRET,
        ),
    )
    if ENVIRONMENT.strip().lower() not in DEPLOYED_ENVIRONMENTS and not JWT_SECRET_KEY:
        logger.warning(
            "JWT_SECRET_KEY is not set; authentication tokens are unsafe outside local development"
        )

settings = Settings()
