import logging
import uuid
from typing import Optional

from passlib.context import CryptContext
from sqlmodel import Session, select

from app.models.entities import User
from app.models.enums import UserStatus
from app.schemas.onboarding import OnboardingRequest
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope
from shared.utils.exceptions import ConflictError

logger = logging.getLogger(__name__)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def start_onboarding(*, db: Session, data: OnboardingRequest) -> User:
    existing = db.exec(select(User).where(User.email == data.email)).first()
    if existing:
        raise ConflictError("email already registered")

    user = User(
        id=uuid.uuid4(),
        tenant_id=None,
        email=data.email,
        password_hash=_pwd.hash(data.password),
        full_name=data.name,
        phone=data.phone,
        status=UserStatus.PENDING_TENANT.value,  # str — model field is typed as str
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def publish_pending(*, event_bus: EventBus, user: User, data: OnboardingRequest) -> str:
    return event_bus.publish(
        "onboarding",
        EventEnvelope(
            type="onboarding.pending",
            aggregate_id=str(user.id),
            tenant_id=None,
            payload={
                "user_id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "phone": user.phone,
                "business_name": data.business_name,
                "legal_name": data.legal_name,
                "support_inbox": data.support_inbox,
                "timezone": data.timezone,
            },
        ),
    )


def handle_tenant_created(
    event: EventEnvelope, *, db: Session, event_bus: EventBus
) -> Optional[User]:
    """Assign tenant to user and publish onboarding.completed.

    Returns the updated user when the assignment happened, or None when the
    user was unknown or already active.
    """
    user_id = uuid.UUID(event.aggregate_id)
    user = db.get(User, user_id)
    if not user:
        logger.warning("tenant.created for unknown user %s; skipping", user_id)
        return None

    if user.status == UserStatus.ACTIVE:
        logger.info("user %s already active; skipping idempotently", user_id)
        return None

    user.tenant_id = uuid.UUID(event.payload["tenant_id"])
    user.status = UserStatus.ACTIVE.value  # str
    db.commit()
    db.refresh(user)

    event_bus.publish(
        "onboarding",
        EventEnvelope(
            type="onboarding.completed",
            aggregate_id=str(user.id),
            tenant_id=str(user.tenant_id),
            payload={
                "user_id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "email": user.email,
                "full_name": user.full_name,
                "phone": user.phone,
                "business_name": event.payload.get("business_name", ""),
                "timezone": event.payload.get("timezone", ""),
                "support_inbox": event.payload.get("support_inbox", ""),
            },
        ),
    )
    return user


def wait_for_onboarding_completion(
    *,
    registry,
    user_id: uuid.UUID,
    timeout: float,
) -> Optional[uuid.UUID]:
    """Wait for the consumer to mark onboarding completed for `user_id`.

    Returns the tenant_id if completed within `timeout`, otherwise None.
    """
    completion = registry.wait_for(user_id, timeout=timeout)
    return completion.tenant_id if completion else None
