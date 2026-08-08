import uuid
from typing import Optional

from sqlmodel import Session

from app.services.onboarding import handle_tenant_created
from app.services.onboarding_completion import (
    OnboardingCompletion,
    OnboardingCompletionRegistry,
)
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope


def build_handlers(
    session_factory,
    event_bus: EventBus,
    completion_registry: Optional[OnboardingCompletionRegistry] = None,
) -> dict[str, EventHandler]:
    def _handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            user = handle_tenant_created(event, db=session, event_bus=event_bus)
            if completion_registry is not None and user is not None and user.tenant_id is not None:
                completion_registry.complete(
                    OnboardingCompletion(
                        user_id=user.id,
                        tenant_id=user.tenant_id,
                    )
                )
        finally:
            session.close()

    return {"tenant.created": _handler}
