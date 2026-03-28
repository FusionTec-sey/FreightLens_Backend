import os
from dotenv import load_dotenv

# Load from .env only if DATABASE_URL is not already set
if not os.getenv("DATABASE_URL"):
    load_dotenv()

class Settings:
    HOST_IP = os.getenv("HOST_IP", "0.0.0.0")
    HOST_PORT = int(os.getenv("HOST_PORT", 9000))
    
    CMA_CGM_API_KEY = os.getenv("CMA_CGM_API_KEY", "")
    CMA_CGM_CLIENT_ID = os.getenv("CMA_CGM_CLIENT_ID", "")
    CMA_CGM_SECRET = os.getenv("CMA_CGM_SECRET", "")
    CMA_CGM_TRACK_AND_TRACE_URL = os.getenv("CMA_CGM_TRACK_AND_TRACE_URL", "")
    CMA_CGM_SHIPEMENTS_URL = os.getenv("CMA_CGM_SHIPEMENTS_URL", "")
    
    MEARSK_CLIENT_ID = os.getenv("MEARSK_CLIENT_ID", "")
    MEARSK_SECRET = os.getenv("MEARSK_SECRET", "")
    MEARSK_TRACK_AND_TRACE_URL = os.getenv("MEARSK_TRACK_AND_TRACE_URL", "")
    MEARSK_SHIPMENTS_URL = os.getenv("MEARSK_SHIPMENTS_URL", "")
    
    MEARSK_TOKEN_URL = os.getenv("MEARSK_OAUTH", "")
    CMA_CGM_TOKEN_URL = os.getenv("CMA_CGM_OAUTH", "")

    # Make DATABASE_URL mandatory, raise error if not set
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")

settings = Settings()
print(settings.DATABASE_URL)  # For debugging; remove in production
print(f"Server will run on {settings.HOST_IP}:{settings.HOST_PORT}" )
print(f"CMA CGM API Key: {settings.CMA_CGM_API_KEY}")  # For debugging; remove in production
print(f"MEARSK Client ID: {settings.MEARSK_CLIENT_ID}")  # For debugging; remove in production
print(f"MEARSK Token URL: {settings.MEARSK_TOKEN_URL}")  # For debugging; remove in production
print(f"CMA CGM Token URL: {settings.CMA_CGM_TOKEN_URL}")   # For debugging; remove in production  
