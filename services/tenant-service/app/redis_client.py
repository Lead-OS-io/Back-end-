import redis.asyncio as redis
from app.config import settings
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


def _safe_redis_target(url: str) -> str:
    """host:port only for logs - the URL carries the password as userinfo."""
    try:
        u = urlparse(url)
        return f"{u.scheme}://{u.hostname}:{u.port or ''}"
    except Exception:
        return "<redis>"

# Global Redis client instance
redis_client: redis.Redis = None

def init_redis():
    """
    Initialize Redis client.
    """
    global redis_client
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Connecting to Redis at: {_safe_redis_target(settings.REDIS_URL)}")
    try:
        kwargs = {
            "encoding": "utf-8",
            "decode_responses": True,
            "socket_timeout": 5.0,
            "socket_connect_timeout": 5.0,
            "retry_on_timeout": True,
            "max_connections": 10,
            "health_check_interval": 30,
            "socket_keepalive": True
        }
        if settings.REDIS_URL and settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = "required"
            
        redis_client = redis.from_url(settings.REDIS_URL, **kwargs)
        logger.info("Redis client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis client: {e}")
        redis_client = None

async def close_redis():
    """
    Close Redis client.
    """
    global redis_client
    if redis_client:
        await redis_client.aclose()
        logger.info("Redis client closed for tenant-service")
