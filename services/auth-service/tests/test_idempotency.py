from unittest.mock import MagicMock

from app.schemas.onboarding import OnboardingRequest
from app.services.onboarding import handle_tenant_created, start_onboarding
from shared.events.envelope import EventEnvelope


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        business_name="Acme Co",
        timezone="UTC",
        legal_name="Acme",
        support_inbox="s@acme.com",
    )
    base.update(over)
    return OnboardingRequest(**base)


def test_second_tenant_created_does_not_republish(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    tenant_id = "00000000-0000-0000-0000-000000000099"
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id=str(user.id),
        payload={"tenant_id": tenant_id, "business_name": "Acme"},
    )
    bus1 = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus1)
    assert bus1.publish.call_count == 1

    bus2 = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus2)
    assert bus2.publish.call_count == 0
