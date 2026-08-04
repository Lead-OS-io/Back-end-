import fakeredis
import pytest

from shared.events import bus as bus_module
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus_module.redis.Redis, "from_url", lambda *a, **k: client)
    return client


def test_envelope_defaults():
    e = EventEnvelope(type="user.registered", aggregate_id="123")
    assert e.version == 1
    assert e.tenant_id is None
    assert e.payload == {}
    assert e.id is not None and e.occurred_at is not None


def test_envelope_requires_type_and_aggregate_id():
    with pytest.raises(Exception):
        EventEnvelope()


def test_publish_xadds_envelope_to_domain_stream(fake_redis):
    bus = EventBus("redis://fake:6379/0")
    event = EventEnvelope(type="user.registered", aggregate_id="123",
                          tenant_id=42, payload={"email": "a@b.c"})
    stream_id = bus.publish("auth", event)
    entries = fake_redis.xrange("events:auth")
    assert len(entries) == 1
    assert entries[0][0] == stream_id
    stored = EventEnvelope.model_validate_json(entries[0][1]["data"])
    assert stored == event


def test_stream_name():
    assert EventBus.stream_name("users") == "events:users"
