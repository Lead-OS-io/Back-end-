import logging
import threading
from typing import Callable

import redis

from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventEnvelope], None]


class Consumer:
    def __init__(self, redis_url: str, *, domain: str, group: str, consumer_name: str,
                 handlers: dict[str, EventHandler], max_deliveries: int = 5,
                 block_ms: int = 5000):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.stream = EventBus.stream_name(domain)
        self.dlq_stream = f"{self.stream}:dlq"
        self.deliveries_key = f"{self.stream}:deliveries"
        self.group = group
        self.consumer_name = consumer_name
        self.handlers = handlers
        self.max_deliveries = max_deliveries
        self.block_ms = block_ms
        self._stop_event = threading.Event()

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_forever(self) -> None:
        self._ensure_group()
        start_id = "0"
        while not self._stop_event.is_set():
            entries = self._redis.xreadgroup(
                self.group, self.consumer_name,
                {self.stream: start_id}, count=10, block=self.block_ms if start_id == ">" else None,
            )
            messages = (entries or [("", [])])[0][1]
            if not messages:
                start_id = ">"
                continue
            for msg_id, fields in messages:
                self._handle(msg_id, fields)

    def stop(self) -> None:
        self._stop_event.set()

    def _handle(self, msg_id: str, fields: dict) -> None:
        try:
            event = EventEnvelope.model_validate_json(fields["data"])
            handler = self.handlers.get(event.type)
            if handler is None:
                logger.info("no handler for %s, acking", event.type)
                self._redis.xack(self.stream, self.group, msg_id)
                return
            handler(event)
            self._redis.xack(self.stream, self.group, msg_id)
            self._redis.hdel(self.deliveries_key, msg_id)
        except Exception:
            logger.exception("error handling message %s", msg_id)
            deliveries = self._redis.hincrby(self.deliveries_key, msg_id, 1)
            if deliveries >= self.max_deliveries:
                logger.error("message %s to DLQ after %s deliveries", msg_id, deliveries)
                self._redis.xadd(self.dlq_stream, fields)
                self._redis.xack(self.stream, self.group, msg_id)
                self._redis.hdel(self.deliveries_key, msg_id)
