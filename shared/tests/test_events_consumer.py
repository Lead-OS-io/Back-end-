import threading
import time

import fakeredis
import pytest

from shared.events import bus as bus_module
from shared.events import consumer as consumer_module
from shared.events.bus import EventBus
from shared.events.consumer import Consumer
from shared.events.envelope import EventEnvelope


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus_module.redis.Redis, "from_url", lambda *a, **k: client)
    monkeypatch.setattr(consumer_module.redis.Redis, "from_url", lambda *a, **k: client)
    return client


def _make_consumer(handlers, max_deliveries=3):
    return Consumer("redis://fake:6379/0", domain="auth", group="users-service",
                    consumer_name="users-1", handlers=handlers,
                    max_deliveries=max_deliveries, block_ms=50)


def _publish_one(fake_redis):
    bus = EventBus("redis://fake:6379/0")
    return bus.publish("auth", EventEnvelope(type="user.registered", aggregate_id="1"))


def test_handler_receives_event_and_acks(fake_redis):
    received = []
    consumer = _make_consumer({"user.registered": received.append})
    consumer._ensure_group()
    msg_id = _publish_one(fake_redis)
    _, fields = fake_redis.xrange("events:auth")[0]
    consumer._handle(msg_id, fields)
    assert len(received) == 1 and received[0].aggregate_id == "1"
    pending = fake_redis.xpending("events:auth", "users-service")
    assert pending["pending"] == 0


def test_unknown_event_type_is_acked_without_handler(fake_redis):
    consumer = _make_consumer({})
    consumer._ensure_group()
    bus = EventBus("redis://fake:6379/0")
    msg_id = bus.publish("auth", EventEnvelope(type="unknown.thing", aggregate_id="9"))
    _, fields = fake_redis.xrange("events:auth")[0]
    consumer._handle(msg_id, fields)
    assert fake_redis.xpending("events:auth", "users-service")["pending"] == 0


def test_failing_message_lands_in_dlq_after_max_deliveries(fake_redis):
    def boom(event):
        raise RuntimeError("handler exploded")

    consumer = _make_consumer({"user.registered": boom}, max_deliveries=3)
    consumer._ensure_group()
    msg_id = _publish_one(fake_redis)
    _, fields = fake_redis.xrange("events:auth")[0]
    for _ in range(3):
        consumer._handle(msg_id, fields)
    dlq = fake_redis.xrange("events:auth:dlq")
    assert len(dlq) == 1
    assert fake_redis.xpending("events:auth", "users-service")["pending"] == 0


def test_run_forever_processes_until_stopped(fake_redis):
    received = []
    consumer = _make_consumer({"user.registered": received.append})
    thread = threading.Thread(target=consumer.run_forever, daemon=True)
    thread.start()
    _publish_one(fake_redis)
    deadline = time.time() + 5
    while not received and time.time() < deadline:
        time.sleep(0.05)
    consumer.stop()
    thread.join(timeout=5)
    assert len(received) == 1
