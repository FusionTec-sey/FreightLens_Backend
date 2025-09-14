
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # DROPBOX_API: str = os.getenv("DROPBOX_API", "")
    HOST_IP = os.getenv("HOST_IP", "0.0.0.0")
    HOST_PORT = int(os.getenv("HOST_PORT", 8000))
    
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
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

settings = Settings()

