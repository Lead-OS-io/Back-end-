from sqlmodel import Session

from app.services.onboarding import handle_tenant_created
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope


def build_handlers(session_factory, event_bus: EventBus) -> dict[str, EventHandler]:
    def _handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            handle_tenant_created(event, db=session, event_bus=event_bus)
        finally:
            session.close()

    return {"tenant.created": _handler}
