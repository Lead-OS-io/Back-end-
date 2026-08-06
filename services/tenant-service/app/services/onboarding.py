import logging
import re
import uuid

from sqlmodel import Session

from app.models.entities import Tenant
from app.models.enums import TenantStatus
from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)

_slug_strip_re = re.compile(r"[^a-z0-9-]+")
_slug_dash_re = re.compile(r"-+")


def _slugify(business_name: str) -> str:
    base = business_name.lower().replace(" ", "-")
    base = _slug_strip_re.sub("", base)
    base = _slug_dash_re.sub("-", base).strip("-")
    return (base or "tenant")[:32]


def handle_onboarding_pending(event: EventEnvelope, *, db: Session) -> tuple[str, str]:
    payload = event.payload
    business = payload["business_name"]
    slug = f"{_slugify(business)}-{uuid.uuid4().hex[:6]}"

    tenant = Tenant(
        id=uuid.uuid4(),
        name=business,
        slug=slug,
        business_name=business,
        timezone=payload["timezone"],
        legal_name=payload["legal_name"],
        support_inbox=payload["support_inbox"],
        status=TenantStatus.TRIAL.value,  # str — model field is typed as str
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return str(tenant.id), slug
