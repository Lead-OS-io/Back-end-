import functools
import json

import redis


def _build_key(prefix: str, key_parts: tuple[str, ...], kwargs: dict) -> str:
    if key_parts:
        parts = [str(kwargs[p]) for p in key_parts]
    else:
        parts = [f"{k}={v}" for k, v in sorted(kwargs.items()) if k != "redis_client"]
    suffix = ":".join(parts)
    return f"ariadesk:shared:{prefix}:{suffix}" if suffix else f"ariadesk:shared:{prefix}"


def cached(*, prefix: str, ttl: int = 300, key_parts: tuple[str, ...] = ()):
    """Cachea el retorno (JSON-serializable) en redis. La función decorada debe
    aceptar kwarg `redis_client` y los kwargs nombrados en key_parts."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            redis_client = kwargs.get("redis_client")
            if redis_client is None:
                return func(*args, **kwargs)
            key = _build_key(prefix, key_parts, kwargs)
            hit = redis_client.get(key)
            if hit is not None:
                return json.loads(hit)
            result = func(*args, **kwargs)
            redis_client.setex(key, ttl, json.dumps(result, default=str))
            return result

        return wrapper

    return decorator


def invalidate_pattern(redis_client: redis.Redis, pattern: str) -> int:
    deleted = 0
    for key in redis_client.scan_iter(match=pattern, count=500):
        redis_client.delete(key)
        deleted += 1
    return deleted
