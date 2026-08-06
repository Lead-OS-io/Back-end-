import re

from app.models import Tenant, TenantStatus
from app.services.onboarding import handle_onboarding_pending
from shared.events.envelope import EventEnvelope


def _event(**over):
    base = dict(
        type="onboarding.pending",
        aggregate_id="00000000-0000-0000-0000-000000000001",
        payload={
            "user_id": "00000000-0000-0000-0000-000000000001",
            "email": "founder@acme.com",
            "full_name": "Ana Founder",
            "phone": "+14155550100",
            "business_name": "Acme Co",
            "legal_name": "Acme Co LLC",
            "support_inbox": "support@acme.com",
            "timezone": "America/Mexico_City",
        },
    )
    base["payload"].update(over)
    return EventEnvelope(**base)


def test_creates_tenant_in_trial(db_session):
    tenant_id, slug = handle_onboarding_pending(_event(), db=db_session)
    assert tenant_id

    from sqlmodel import select
    t = db_session.exec(select(Tenant)).first()
    assert t is not None
    assert t.id is not None
    assert t.name == "Acme Co"
    assert t.business_name == "Acme Co"
    assert t.legal_name == "Acme Co LLC"
    assert t.support_inbox == "support@acme.com"
    assert t.timezone == "America/Mexico_City"
    assert t.status == TenantStatus.TRIAL.value
    assert t.is_active is True
    assert t.slug == slug


def test_slug_is_derived_and_unique(db_session):
    _, slug1 = handle_onboarding_pending(_event(), db=db_session)
    _, slug2 = handle_onboarding_pending(_event(), db=db_session)
    assert slug1 != slug2
    assert re.match(r"^[a-z0-9-]+-[a-f0-9]{6}$", slug1)


def test_handles_special_chars_in_business_name(db_session):
    _, slug = handle_onboarding_pending(_event(business_name="Café & Co!"), db=db_session)
    assert slug.startswith("caf-co-")
