import fakeredis.aioredis
import pytest

from app.services.ratelimit import is_rate_limited


@pytest.mark.asyncio
async def test_allows_up_to_limit_then_blocks():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for _ in range(3):
        assert await is_rate_limited(redis, "1.2.3.4", limit=3) is False
    assert await is_rate_limited(redis, "1.2.3.4", limit=3) is True


@pytest.mark.asyncio
async def test_different_keys_are_independent():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await is_rate_limited(redis, "1.1.1.1", limit=1)
    assert await is_rate_limited(redis, "2.2.2.2", limit=1) is False
