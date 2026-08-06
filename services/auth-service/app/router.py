from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from shared.db.engine import get_db
from shared.events.bus import EventBus

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


@router.post(
    "/onboarding",
    response_model=OnboardingAcceptedResponse,
    status_code=202,
)
def onboarding(
    data: OnboardingRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    event_bus: EventBus = Depends(get_event_bus),
) -> OnboardingAcceptedResponse:
    return controller.onboarding(data=data, db=db, settings=settings, event_bus=event_bus)
