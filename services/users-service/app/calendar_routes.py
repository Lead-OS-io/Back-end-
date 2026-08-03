"""
Local calendar (DB) endpoints for users-service.

This is the ONLY place that should read/write the `public.calendar` table.
Desk (desk_app) should call these endpoints instead of touching the DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session, select, and_
from sqlalchemy import text

from app.database import engine
from app.models import CalendarEvent
from app.schemas import (
    CalendarCreate,
    CalendarUpdate,
    CalendarResponse,
    CalendarReminderItem,
    PolicyWarningSyncRequest,
    PolicyWarningSyncResponse,
)

# Reuse auth + Google Calendar helpers from users-service Google routes.
from app.google_calendar_routes import get_tenant_id, get_user_id, _fetch_google_access_token, _calendar_service, _extract_meet_url


router = APIRouter(prefix="/api/calendar", tags=["Calendar (users-service)"])


def get_db(tenant_id=Depends(get_tenant_id)) -> Generator[Session, None, None]:
    """Tenant-scoped session: sets the app.tenant_id GUC read by the
    tenant_isolation policy on public.calendar (see the migration that
    restored the tenant_id column on this table)."""
    with Session(engine) as session:
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


def _format_time_until(start_date: datetime) -> str:
    now = datetime.utcnow()
    diff = start_date - now
    if diff.total_seconds() < 0:
        return "Past event"
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    if days > 0:
        return f"in {days} day{'s' if days != 1 else ''}"
    if hours > 0:
        return f"in {hours} hour{'s' if hours != 1 else ''}"
    if minutes > 0:
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    return "Now"


def _google_event_body(payload: CalendarCreate | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(payload, dict):
        title = payload.get("title") or "Event"
        description = payload.get("description") or ""
        location = payload.get("location") or ""
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        tz = payload.get("timezone") or "UTC"
    else:
        title = payload.title
        description = payload.description or ""
        location = payload.location or ""
        start_date = payload.start_date
        end_date = payload.end_date
        tz = payload.timezone or "UTC"

    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")

    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")

    # Google expects RFC3339; datetime.isoformat() works.
    return {
        "summary": title,
        "location": location,
        "description": description,
        "start": {"dateTime": start_date.isoformat(), "timeZone": tz},
        "end": {"dateTime": end_date.isoformat(), "timeZone": tz},
    }


@router.post("", response_model=CalendarResponse)
def create_calendar_event(
    payload: CalendarCreate,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    authorization: str = Header(..., alias="Authorization"),
    db: Session = Depends(get_db),
):
    # Create in Google first (source of truth for Google events)
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)
    try:
        created = cal.events().insert(calendarId="primary", body=_google_event_body(payload)).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google Calendar error: {e}")

    google_event_id = created.get("id")
    meet_url = _extract_meet_url(created)

    ev = CalendarEvent(
        tenant_id=tenant_id,
        title=payload.title,
        description=payload.description,
        event_type=payload.event_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        all_day=payload.all_day,
        timezone=payload.timezone,
        location=payload.location,
        color=payload.color,
        priority=payload.priority,
        status=payload.status,
        is_active=True,
        owner_id=user_id,
        created_by_id=user_id,
        assigned_to_id=payload.assigned_to_id,
        case_data_id=payload.case_data_id,
        policy_id=payload.policy_id,
        agency_id=payload.agency_id,
        reminder_before_minutes=payload.reminder_before_minutes,
        reminder_sent=False,
        reminder_sent_at=None,
        visibility=payload.visibility,
        shared_with=payload.shared_with or [],
        google_calendar_id=google_event_id,
        google_calendar_synced=True,
        google_calendar_synced_at=datetime.utcnow(),
        meet_url=meet_url,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev



@router.get("", response_model=List[CalendarResponse])
def list_calendar_events(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    db: Session = Depends(get_db),
):
    q = select(CalendarEvent).where(
        CalendarEvent.tenant_id == tenant_id,
        CalendarEvent.owner_id == user_id,
        CalendarEvent.is_active == True,
    )
    
    if start:
        q = q.where(CalendarEvent.start_date >= start)
    if end:
        q = q.where(CalendarEvent.end_date <= end)
        
    # Sort by start date
    q = q.order_by(CalendarEvent.start_date.asc())
    
    return db.exec(q).all()


@router.put("/{event_id}", response_model=CalendarResponse)
def update_calendar_event(
    event_id: int,
    payload: CalendarUpdate,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    authorization: str = Header(..., alias="Authorization"),
    db: Session = Depends(get_db),
):
    ev = db.get(CalendarEvent, int(event_id))
    if not ev or not ev.is_active or str(ev.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if str(ev.owner_id) != str(user_id) and str(ev.created_by_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Cannot modify this calendar event")

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(ev, k, v)
    ev.modified_at = datetime.utcnow()

    # Sync to Google if we have a Google event ID
    if ev.google_calendar_id:
        access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
        cal = _calendar_service(access)
        try:
            body = _google_event_body(
                {
                    "title": ev.title,
                    "description": ev.description,
                    "location": ev.location,
                    "start_date": ev.start_date,
                    "end_date": ev.end_date,
                    "timezone": ev.timezone,
                }
            )
            updated = cal.events().update(calendarId="primary", eventId=ev.google_calendar_id, body=body).execute()
            ev.google_calendar_synced = True
            ev.google_calendar_synced_at = datetime.utcnow()
            ev.meet_url = _extract_meet_url(updated) or ev.meet_url
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Google Calendar error: {e}")

    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@router.delete("/{event_id}")
def delete_calendar_event(
    event_id: int,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    authorization: str = Header(..., alias="Authorization"),
    db: Session = Depends(get_db),
):
    ev = db.get(CalendarEvent, int(event_id))
    if not ev or str(ev.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Calendar event not found")
    if str(ev.owner_id) != str(user_id) and str(ev.created_by_id) != str(user_id):
        raise HTTPException(status_code=403, detail="Cannot delete this calendar event")

    if ev.google_calendar_id:
        access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
        cal = _calendar_service(access)
        try:
            cal.events().delete(calendarId="primary", eventId=ev.google_calendar_id).execute()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to delete Google event: {e}")

    db.delete(ev)
    db.commit()
    return {"message": "Calendar event deleted successfully"}


@router.get("/reminders/upcoming", response_model=List[CalendarReminderItem])
def upcoming_reminders(
    hours_ahead: int = 24,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    future = now + timedelta(hours=int(hours_ahead or 24))
    q = (
        select(CalendarEvent)
        .where(
            and_(
                CalendarEvent.tenant_id == tenant_id,
                CalendarEvent.is_active == True,
                CalendarEvent.owner_id == user_id,
                CalendarEvent.status.in_(["scheduled", "in_progress"]),
                CalendarEvent.start_date > now,
                CalendarEvent.start_date <= future,
            )
        )
        .order_by(CalendarEvent.start_date.asc())
    )
    rows = db.exec(q).all() or []
    out: List[CalendarReminderItem] = []
    for ev in rows:
        out.append(
            CalendarReminderItem(
                id=int(ev.id),
                title=f"{(ev.event_type or '').title()}: {ev.title}",
                description=ev.description or f"{(ev.event_type or '').title()} scheduled",
                time=_format_time_until(ev.start_date),
                status=(ev.event_type or "").title(),
                event_type=ev.event_type,
                start_date=ev.start_date,
                end_date=ev.end_date,
                location=ev.location,
                case_data_id=ev.case_data_id,
                policy_id=ev.policy_id,
            )
        )
    return out


@router.post("/policy-warnings/sync", response_model=PolicyWarningSyncResponse)
def sync_policy_warning_events(
    payload: PolicyWarningSyncRequest,
    tenant_id=Depends(get_tenant_id),
    user_id=Depends(get_user_id),
    db: Session = Depends(get_db),
):
    created = 0
    for alert in (payload.alerts or []):
        try:
            pid = int(alert.id)
        except Exception:
            continue

        exists = db.exec(
            select(CalendarEvent.id).where(
                and_(
                    CalendarEvent.tenant_id == tenant_id,
                    CalendarEvent.owner_id == user_id,
                    CalendarEvent.policy_id == pid,
                    CalendarEvent.event_type == "policy_warning",
                    CalendarEvent.is_active == True,
                )
            )
        ).first()
        if exists:
            continue

        start_dt = None
        try:
            if alert.date:
                start_dt = datetime.strptime(str(alert.date), "%m-%d-%Y")
        except Exception:
            start_dt = None
        if not start_dt:
            continue

        title = f"Policy Warning: {(alert.policy_number or '').strip()} requires attention".strip()
        desc = f"Policy for {(alert.name or '').strip()} requires attention.".strip()

        ev = CalendarEvent(
            tenant_id=tenant_id,
            title=title or "Policy Warning",
            description=desc or None,
            event_type="policy_warning",
            start_date=start_dt,
            end_date=start_dt + timedelta(hours=1),
            all_day=False,
            timezone="UTC",
            location=None,
            color="#465fff",
            priority="high",
            status="scheduled",
            is_active=True,
            owner_id=user_id,
            created_by_id=user_id,
            assigned_to_id=None,
            case_data_id=None,
            policy_id=pid,
            agency_id=None,
            reminder_before_minutes=1440,
            reminder_sent=False,
            reminder_sent_at=None,
            visibility="private",
            shared_with=[],
            google_calendar_id=None,
            google_calendar_synced=False,
            google_calendar_synced_at=None,
            meet_url=None,
        )
        db.add(ev)
        created += 1

    if created:
        db.commit()
    return PolicyWarningSyncResponse(created=created)

