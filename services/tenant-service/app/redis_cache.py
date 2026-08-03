import functools
import json
import logging
import hashlib
import asyncio
from typing import Optional, Callable, Any
from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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

def cached(ttl: int = 3600, prefix: str = "cache"):
    """
    FastAPI Redis Caching Decorator for Tenant Service.
    Standard TTL is 1 hour as tenant data changes very infrequently.
    Supports both sync and async functions."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            is_async = asyncio.iscoroutinefunction(func)
            
            async def get_original_result():
                if is_async:
                    return await func(*args, **kwargs)
                return await run_in_threadpool(func, *args, **kwargs)

            from app.redis_client import redis_client
            if not redis_client:
                return await get_original_result()
            
            request: Optional[Request] = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if not request:
                return await get_original_result()
            
            # Tenant service is usually global (no X-Tenant-Id header required for key isolation)
            # but we use it if present.
            tenant_id = request.headers.get("X-Tenant-Id", "system")
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

            cache_key = get_cache_key(prefix, tenant_id, None, url_path, query_params, body_hash)
            

            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    return json.loads(cached_data)
            except Exception as e:
                pass
            
            result = await get_original_result()
            
            try:
                if result is not None:
                    from fastapi.encoders import jsonable_encoder
                    await redis_client.set(
                        cache_key, 
                        json.dumps(jsonable_encoder(result), default=str), 
                        ex=ttl
                    )
            except Exception as e:
                pass
            
            return result
        return wrapper
    return decorator
