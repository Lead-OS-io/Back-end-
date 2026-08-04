from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from shared.events.envelope import EventEnvelope


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, domain, event):
        self.published.append((domain, event))
        return "1-0"


def test_register_publishes_user_registered(svc_headers, monkeypatch):
    import uuid
    from datetime import datetime

    class U:
        id = uuid.uuid4()
        email = "n@x.com"
        full_name = "N"
        first_name = "N"
        last_name = None
        tenant_id = uuid.uuid4()
        is_active = True
        is_staff = False
        is_superuser = False
        role_id = None
        date_joined = datetime.utcnow()
        last_login = None
        first_login = False

    monkeypatch.setattr("app.controller.auth_service.register_user",
                        lambda **kwargs: U())

    bus = _FakeBus()
    from app.main import create_app
    from app.router import get_event_bus
    from shared.db.engine import get_db

    app = create_app()
    app.dependency_overrides[get_event_bus] = lambda: bus
    app.dependency_overrides[get_db] = lambda: MagicMock()
    with TestClient(app) as c:
        resp = c.post("/api/auth/register",
                      json={"email": "n@x.com", "password": "Pw123456", "full_name": "N"},
                      headers=svc_headers)
    assert resp.status_code == 201
    assert len(bus.published) == 1
    domain, event = bus.published[0]
    assert domain == "auth"
    assert isinstance(event, EventEnvelope)
    assert event.type == "user.registered" and event.aggregate_id == str(U.id)
    assert event.payload["email"] == "n@x.com"
