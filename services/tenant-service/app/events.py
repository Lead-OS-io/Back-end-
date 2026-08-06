import logging

from sqlmodel import Session
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

from app.services.onboarding import handle_onboarding_pending

logger = logging.getLogger(__name__)


def build_handlers(session_factory, event_bus: EventBus) -> dict[str, EventHandler]:
    def _handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            tenant_id, slug = handle_onboarding_pending(event, db=session)
            event_bus.publish(
                "onboarding",
                EventEnvelope(
                    type="tenant.created",
                    aggregate_id=event.payload["user_id"],
                    tenant_id=tenant_id,
                    payload={
                        "user_id": event.payload["user_id"],
                        "tenant_id": tenant_id,
                        "tenant_slug": slug,
                        "business_name": event.payload.get("business_name", ""),
                        "timezone": event.payload.get("timezone", ""),
                        "support_inbox": event.payload.get("support_inbox", ""),
                    },
                ),
            )
        finally:
            session.close()

    return {"onboarding.pending": _handler}
