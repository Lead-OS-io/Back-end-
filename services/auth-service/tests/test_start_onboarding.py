import uuid

import pytest

from app.models import User, UserStatus
from app.schemas.onboarding import OnboardingRequest
from app.services.onboarding import start_onboarding
from shared.utils.exceptions import ConflictError


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


def test_creates_user_pending_tenant(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    assert user.id is not None
    assert isinstance(user.id, uuid.UUID)
    assert user.tenant_id is None
    assert user.email == "founder@acme.com"
    assert user.full_name == "Ana Founder"
    assert user.phone == "+14155550100"
    assert user.status == UserStatus.PENDING_TENANT


def test_password_is_hashed_not_plain(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    assert user.password_hash is not None
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$2")


def test_duplicate_email_raises_conflict(db_session):
    start_onboarding(db=db_session, data=_payload())
    with pytest.raises(ConflictError):
        start_onboarding(db=db_session, data=_payload())
