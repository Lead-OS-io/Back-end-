import redis

from shared.events.envelope import EventEnvelope


class EventBus:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def stream_name(domain: str) -> str:
        return f"events:{domain}"

    def publish(self, domain: str, event: EventEnvelope) -> str:
        return self._redis.xadd(
            self.stream_name(domain), {"data": event.model_dump_json()}
        )
