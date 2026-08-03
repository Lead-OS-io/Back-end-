import functools
import json
import logging
import hashlib
import asyncio
import jwt
from typing import Optional, Callable, Any
from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool
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

def cached(ttl: int = 300, prefix: str = "cache"):
    """
    FastAPI Redis Caching Decorator for Files Service.
    Commonly used for attachment lists which don't change very often.
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
            
            tenant_id = _verified_tenant_id(request)
            url_path = request.url.path
            query_params = str(request.query_params)
            
            key_raw = f"{prefix}:{tenant_id}:{url_path}:{query_params}"
            cache_key = f"ariadesk:files:{hashlib.md5(key_raw.encode()).hexdigest()}"
            

            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    return json.loads(cached_data)
            except Exception as e:
                logger.debug(f"Redis cache operation failed: {e}")
            
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
                logger.debug(f"Redis cache operation failed: {e}")
            
            return result
        return wrapper
    return decorator
