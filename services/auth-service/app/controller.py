from sqlmodel import Session

from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from app.services.onboarding import publish_pending, start_onboarding
from shared.events.bus import EventBus


def onboarding(
    *, data: OnboardingRequest, db: Session, settings, event_bus: EventBus
) -> OnboardingAcceptedResponse:
    user = start_onboarding(db=db, data=data)
    publish_pending(event_bus=event_bus, user=user, data=data)
    return OnboardingAcceptedResponse(user_id=user.id, status=user.status)
