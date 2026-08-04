import redis


def create_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)
