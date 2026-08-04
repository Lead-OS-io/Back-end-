"""
Calendar service (Desk) + Google Calendar integration (users-service).
Los endpoints que sincronizan con Google reciben el Authorization header del
cliente para obtener un access token corto via auth-service.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlmodel import Session, select, and_

from app.config import settings
from app.models import CalendarEvent
from app.schemas.calendar import (
    CalendarCreate, CalendarReminderItem, CalendarUpdate, PolicyWarningSyncRequest,
    PolicyWarningSyncResponse,
)
from shared.utils.exceptions import AppError

_http_client = httpx.Client(timeout=10.0)


def _fetch_google_access_token(*, authorization: str, tenant_id) -> dict:
    url = f"{settings.AUTH_SERVICE_URL.rstrip('/')}/api/auth/google/access-token"
    headers = {"Authorization": authorization, "X-Tenant-Id": str(tenant_id)}
    try:
        r = _http_client.get(url, headers=headers)
        if r.status_code == 400:
            raise AppError(401, "Google authentication required")
        r.raise_for_status()
        return r.json()
    except AppError:
        raise
    except Exception as e:
        raise AppError(502, f"Auth service unavailable: {e}")


def _calendar_service(access: dict):
    token = (access or {}).get("access_token")
    if not token:
        raise AppError(502, "Auth service did not return access_token")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(token=token)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _extract_meet_url(event_dict: dict) -> Optional[str]:
    try:
        hangout = event_dict.get("hangoutLink")
        if isinstance(hangout, str) and "meet.google.com" in hangout:
            return hangout
        conf = event_dict.get("conferenceData") or {}
        for ep in (conf.get("entryPoints") or []):
            if isinstance(ep, dict) and ep.get("entryPointType") == "video":
                uri = ep.get("uri")
                if isinstance(uri, str) and "meet.google.com" in uri:
                    return uri
        loc = event_dict.get("location")
        if isinstance(loc, str) and "meet.google.com" in loc:
            return loc
        desc = event_dict.get("description")
        if isinstance(desc, str) and "meet.google.com" in desc:
            import re
            m = re.search(r"https?://meet\.google\.com/[\w-]+", desc)
            if m:
                return m.group(0)
    except Exception:
        return None
    return None


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
        raise AppError(400, "start_date and end_date are required")

    if end_date <= start_date:
        raise AppError(400, "End date must be after start date")

    return {
        "summary": title,
        "location": location,
        "description": description,
        "start": {"dateTime": start_date.isoformat(), "timeZone": tz},
        "end": {"dateTime": end_date.isoformat(), "timeZone": tz},
    }


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


# ---- CRUD ----
def create_event(*, db: Session, payload: CalendarCreate, tenant_id, user_id,
                 authorization: Optional[str] = None) -> CalendarEvent:
    """Crea el evento en Google primero (si hay token) y luego en local."""
    google_event_id = None
    meet_url = None
    if authorization:
        access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
        cal = _calendar_service(access)
        try:
            created = cal.events().insert(calendarId="primary", body=_google_event_body(payload)).execute()
        except AppError:
            raise
        except Exception as e:
            raise AppError(502, f"Google Calendar error: {e}")
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
        google_calendar_synced=bool(google_event_id),
        google_calendar_synced_at=datetime.utcnow() if google_event_id else None,
        meet_url=meet_url,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def list_events(*, db: Session, tenant_id, user_id,
                start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[CalendarEvent]:
    q = select(CalendarEvent).where(
        CalendarEvent.tenant_id == tenant_id,
        CalendarEvent.owner_id == user_id,
        CalendarEvent.is_active == True,
    )

    if start:
        q = q.where(CalendarEvent.start_date >= start)
    if end:
        q = q.where(CalendarEvent.end_date <= end)

    q = q.order_by(CalendarEvent.start_date.asc())

    return db.exec(q).all()


def get_event(*, db: Session, tenant_id, event_id: int) -> Optional[CalendarEvent]:
    ev = db.get(CalendarEvent, int(event_id))
    if not ev or not ev.is_active or str(ev.tenant_id) != str(tenant_id):
        return None
    return ev


def update_event(*, db: Session, payload: CalendarUpdate, tenant_id, user_id, event_id: int,
                 authorization: Optional[str] = None) -> CalendarEvent:
    ev = get_event(db=db, tenant_id=tenant_id, event_id=event_id)
    if not ev:
        raise AppError(404, "Calendar event not found")
    if str(ev.owner_id) != str(user_id) and str(ev.created_by_id) != str(user_id):
        raise AppError(403, "Cannot modify this calendar event")

    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(ev, k, v)
    ev.modified_at = datetime.utcnow()

    if ev.google_calendar_id and authorization:
        access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
        cal = _calendar_service(access)
        try:
            body = _google_event_body({
                "title": ev.title,
                "description": ev.description,
                "location": ev.location,
                "start_date": ev.start_date,
                "end_date": ev.end_date,
                "timezone": ev.timezone,
            })
            updated = cal.events().update(calendarId="primary", eventId=ev.google_calendar_id,
                                          body=body).execute()
            ev.google_calendar_synced = True
            ev.google_calendar_synced_at = datetime.utcnow()
            ev.meet_url = _extract_meet_url(updated) or ev.meet_url
        except AppError:
            raise
        except Exception as e:
            raise AppError(502, f"Google Calendar error: {e}")

    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def delete_event(*, db: Session, tenant_id, user_id, event_id: int,
                 authorization: Optional[str] = None) -> dict:
    ev = get_event(db=db, tenant_id=tenant_id, event_id=event_id)
    if not ev:
        raise AppError(404, "Calendar event not found")
    if str(ev.owner_id) != str(user_id) and str(ev.created_by_id) != str(user_id):
        raise AppError(403, "Cannot delete this calendar event")

    if ev.google_calendar_id and authorization:
        access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
        cal = _calendar_service(access)
        try:
            cal.events().delete(calendarId="primary", eventId=ev.google_calendar_id).execute()
        except Exception as e:
            raise AppError(502, f"Failed to delete Google event: {e}")

    db.delete(ev)
    db.commit()
    return {"message": "Calendar event deleted successfully"}


def upcoming_reminders(*, db: Session, tenant_id, user_id, hours_ahead: int = 24) -> List[CalendarReminderItem]:
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
        out.append(CalendarReminderItem(
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
        ))
    return out


def sync_policy_warnings(*, db: Session, tenant_id, user_id,
                         payload: PolicyWarningSyncRequest) -> PolicyWarningSyncResponse:
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


# ---- Google Calendar endpoints ----
def debug_calendar_events(*, authorization: str, tenant_id) -> dict:
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=30)).isoformat()
    time_max = (now + timedelta(days=90)).isoformat()
    try:
        resp = cal.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        ).execute()
    except Exception as e:
        raise AppError(502, f"Google Calendar error: {e}")

    items = resp.get("items", []) or []
    out = []
    for ev in items:
        if ev.get("status") == "cancelled":
            continue
        start_obj = ev.get("start", {}) or {}
        end_obj = ev.get("end", {}) or {}
        start_str = start_obj.get("dateTime", start_obj.get("date"))
        end_str = end_obj.get("dateTime", end_obj.get("date"))
        if not start_str or not end_str:
            continue
        out.append({
            "id": ev.get("id"),
            "title": ev.get("summary", "No Title"),
            "description": ev.get("description"),
            "start_date": start_str,
            "end_date": end_str,
            "all_day": "date" in start_obj,
            "location": ev.get("location"),
            "meet_url": _extract_meet_url(ev),
            "status": "scheduled",
            "is_active": True,
            "google_calendar_id": ev.get("id"),
            "google_calendar_synced": True,
        })
    return {"events": out, "count": len(out)}


def add_meet_link(*, authorization: str, tenant_id, google_event_id: str) -> dict:
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)

    request_id = f"meet-{google_event_id}-{int(datetime.utcnow().timestamp())}"
    body = {
        "conferenceData": {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    }
    try:
        updated = cal.events().patch(
            calendarId="primary",
            eventId=google_event_id,
            conferenceDataVersion=1,
            body=body,
        ).execute()
    except Exception as e:
        raise AppError(502, f"Failed to add Meet: {e}")

    meet_url = _extract_meet_url(updated) or updated.get("hangoutLink")
    if not meet_url:
        raise AppError(500, "Meet link not found in updated event")
    return {"meet_url": meet_url}


def get_meet_link(*, authorization: str, tenant_id, google_event_id: str) -> dict:
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)
    try:
        ev = cal.events().get(
            calendarId="primary",
            eventId=google_event_id,
            conferenceDataVersion=1,
        ).execute()
    except Exception as e:
        raise AppError(502, f"Failed to fetch event: {e}")

    return {"meet_url": _extract_meet_url(ev)}


def delete_google_event(*, authorization: str, tenant_id, google_event_id: str) -> dict:
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)
    try:
        cal.events().delete(calendarId="primary", eventId=google_event_id).execute()
    except Exception as e:
        raise AppError(502, f"Failed to delete event: {e}")
    return {"success": True}
