import functools
import inspect
import json
import logging
import hashlib
import jwt
from typing import Optional, Callable
from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from app.config import settings
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _verified_tenant_id(request: Request) -> str:
    """Cache-key tenant must come from the signature-verified Bearer token,
    never from the client-supplied X-Tenant-Id header - trusting that header
    let any caller read another tenant's cached response for the same path."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        try:
            claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            return str(claims.get("tenant_id") or "global")
        except jwt.InvalidTokenError:
            pass
    return "global"

def get_cache_key(prefix: str, tenant_id: str, user_id: Optional[str] = None, url_path: str = "", query_params: str = "", body_hash: str = "") -> str:
    """
    Standardized cache key generation with user-prefixed segment.
    Format: ariadesk:shared:u:{user_id}:hash(...)
    This allows pattern-based invalidation (e.g. DELETE ariadesk:shared:u:{user_id}:*)
    """
    u_segment = str(user_id) if user_id else "global"
    # Normalize path: remove trailing slashes and ensure it starts with /
    normalized_path = "/" + url_path.strip("/") if url_path else ""
    body_suffix = f":{body_hash}" if body_hash else ""
    
    # Hash the details, but keep user_id visible for pattern matching
    details_raw = f"{prefix}:{tenant_id}:{normalized_path}:{query_params}{body_suffix}"
    details_hash = hashlib.md5(details_raw.encode()).hexdigest()
    
    return f"ariadesk:shared:u:{u_segment}:{details_hash}"

def cached(ttl: int = 1800, prefix: str = "cache"):
    """
    FastAPI Redis Caching Decorator.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            async def call_original():
                if inspect.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return await run_in_threadpool(lambda: func(*args, **kwargs))

            from app.redis_client import redis_client
            if not redis_client:
                return await call_original()

            request: Optional[Request] = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                return await call_original()
            
            # Use shared key format to align with other services
            tenant_id = _verified_tenant_id(request)
            url_path = request.url.path
            query_params = str(request.query_params)
            
            # Extract body_hash for POST/PUT/PATCH requests
            body_hash = ""
            if request.method in ["POST", "PUT", "PATCH"]:
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        body_hash = hashlib.md5(body_bytes).hexdigest()
                except Exception:
                    pass

            # News service typically serves same news to all users in a tenant, 
            # but we use 'global' user_id segment to stay consistent with the format.
            cache_key = get_cache_key(prefix, tenant_id, "global", url_path, query_params, body_hash)

            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    return json.loads(cached_data)
                
            except Exception as e:
                logger.debug(f"Redis cache operation failed: {e}")
            result = await call_original()
            
            # Save to cache if result is valid
            try:
                if result is not None:
                    await redis_client.set(
                        cache_key,
                        json.dumps(jsonable_encoder(result), default=str),
                        ex=ttl,
                    )
            except Exception as e:
                logger.debug(f"Redis cache operation failed: {e}")
            return result
        return wrapper
    return decorator
