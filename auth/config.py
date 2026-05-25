import os
import logging
from dotenv import load_dotenv

# Load from .env only if DATABASE_URL is not already set
if not os.getenv("DATABASE_URL"):
    load_dotenv()

logger = logging.getLogger("auth.config")

class Settings:
    HOST_IP = os.getenv("HOST_IP", "0.0.0.0")
    HOST_PORT = int(os.getenv("HOST_PORT", 9000))

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

    # ── App Environment ────────────────────────────────────────────────────────
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

    # ── CORS Allowed Origins ───────────────────────────────────────────────────
    ALLOWED_ORIGINS = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")

    # ── External Shipping APIs ────────────────────────────────────────────────
    CMA_CGM_API_KEY = os.getenv("CMA_CGM_API_KEY", "")
    CMA_CGM_CLIENT_ID = os.getenv("CMA_CGM_CLIENT_ID", "")
    CMA_CGM_SECRET = os.getenv("CMA_CGM_SECRET", "")
    CMA_CGM_TRACK_AND_TRACE_URL = os.getenv("CMA_CGM_TRACK_AND_TRACE_URL", "")
    CMA_CGM_SHIPEMENTS_URL = os.getenv("CMA_CGM_SHIPEMENTS_URL", "")
    CMA_CGM_TOKEN_URL = os.getenv("CMA_CGM_OAUTH", "")

    MEARSK_CLIENT_ID = os.getenv("MEARSK_CLIENT_ID", "")
    MEARSK_SECRET = os.getenv("MEARSK_SECRET", "")
    MEARSK_TRACK_AND_TRACE_URL = os.getenv("MEARSK_TRACK_AND_TRACE_URL", "")
    MEARSK_SHIPMENTS_URL = os.getenv("MEARSK_SHIPMENTS_URL", "")
    MEARSK_TOKEN_URL = os.getenv("MEARSK_OAUTH", "")

    # ── Database ───────────────────────────────────────────────────────────────
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")

    # ── Validation Warnings ───────────────────────────────────────────────────
    if not JWT_SECRET_KEY:
        logger.warning(
            "JWT_SECRET_KEY is not set in .env — using an empty string is insecure!"
        )

settings = Settings()
