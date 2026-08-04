import time

import redis.asyncio as aioredis


async def is_rate_limited(redis: aioredis.Redis, key: str, limit: int) -> bool:
    window = int(time.time() // 60)
    redis_key = f"ratelimit:{key}:{window}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, 70)
    return count > limit
