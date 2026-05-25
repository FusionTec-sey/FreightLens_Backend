import logging

logger = logging.getLogger("limiter")

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address)
    RATE_LIMIT_AVAILABLE = True
except ImportError:
    logger.warning(
        "slowapi not installed — rate limiting is disabled. "
        "Run: pip install slowapi"
    )
    # Dummy limiter for environments without slowapi to prevent crashes
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    limiter = DummyLimiter()
    RATE_LIMIT_AVAILABLE = False
