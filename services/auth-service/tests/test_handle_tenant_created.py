import uuid
from unittest.mock import MagicMock

from app.models import User, UserStatus
from app.schemas.onboarding import OnboardingRequest
from app.services.onboarding import handle_tenant_created, start_onboarding
from shared.events.envelope import EventEnvelope


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        phone="+14155550100",
        business_name="Acme Co",
        timezone="America/Mexico_City",
        legal_name="Acme Co LLC",
        support_inbox="support@acme.com",
    )
    base.update(over)
    return OnboardingRequest(**base)


def test_assigns_tenant_and_marks_active(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id=str(user.id),
        tenant_id="00000000-0000-0000-0000-000000000099",
        payload={"tenant_id": "00000000-0000-0000-0000-000000000099",
                 "business_name": "Acme Co",
                 "timezone": "America/Mexico_City",
                 "support_inbox": "support@acme.com"},
    )
    bus = MagicMock()
    result = handle_tenant_created(event, db=db_session, event_bus=bus)

    assert result is not None
    assert result.id == user.id
    db_session.refresh(user)
    assert user.tenant_id == uuid.UUID("00000000-0000-0000-0000-000000000099")
    assert user.status == UserStatus.ACTIVE.value
    bus.publish.assert_called_once()
    args = bus.publish.call_args
    assert args[0][0] == "onboarding"
    envelope: EventEnvelope = args[0][1]
    assert envelope.type == "onboarding.completed"
    assert envelope.aggregate_id == str(user.id)


def test_skips_unknown_user(db_session):
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id="00000000-0000-0000-0000-000000000777",
        payload={"tenant_id": "00000000-0000-0000-0000-000000000099"},
    )
    bus = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus)
    bus.publish.assert_not_called()
