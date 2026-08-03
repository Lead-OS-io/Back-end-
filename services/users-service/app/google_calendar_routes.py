"""
Google Calendar endpoints for users-service.

OAuth is owned by auth-service. This service fetches short-lived Google access tokens
from auth-service and uses them to call Google Calendar API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users/google", tags=["Google Calendar (users-service)"])

# Pooled client reused across requests instead of opening a new connection
# per call.
_http_client = httpx.Client(timeout=10.0)


def get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-Id")) -> UUID:
    try:
        return UUID(str(x_tenant_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-Id (must be UUID)")


def get_claims(authorization: str = Header(..., alias="Authorization")) -> Dict[str, Any]:
    """Verify the Bearer JWT's signature and return its claims. Was previously
    using get_unverified_claims, which accepted any forged, unsigned token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user_id(
    tenant_id: UUID = Depends(get_tenant_id),
    claims: dict = Depends(get_claims),
) -> UUID:
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing sub")
    try:
        user_id = UUID(str(sub))
    except Exception:
        raise HTTPException(status_code=400, detail="Token sub must be UUID")

    token_tenant = claims.get("tenant_id") or claims.get("tenant") or claims.get("tid")
    if token_tenant and str(token_tenant).strip() != str(tenant_id).strip():
        raise HTTPException(status_code=403, detail="X-Tenant-Id does not match token tenant_id")
    return user_id


def _fetch_google_access_token(*, authorization: str, tenant_id: UUID) -> dict:
    url = f"{settings.AUTH_SERVICE_URL.rstrip('/')}/api/auth/google/access-token"
    headers = {"Authorization": authorization, "X-Tenant-Id": str(tenant_id)}
    try:
        r = _http_client.get(url, headers=headers)
        if r.status_code == 400:
            raise HTTPException(status_code=401, detail="Google authentication required")
        r.raise_for_status()
        return r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Auth service unavailable: {e}")


def _calendar_service(access: dict):
    token = (access or {}).get("access_token")
    if not token:
        raise HTTPException(status_code=502, detail="Auth service did not return access_token")
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


@router.get("/debug-calendar-events")
def debug_calendar_events(
    tenant_id: UUID = Depends(get_tenant_id),
    authorization: str = Header(..., alias="Authorization"),
    user_id: UUID = Depends(get_user_id),
):
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)

    # List upcoming events from primary calendar (simple + fast)
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
        raise HTTPException(status_code=502, detail=f"Google Calendar error: {e}")

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
        out.append(
            {
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
            }
        )
    return {"events": out, "count": len(out)}


@router.patch("/event-add-meet/{google_event_id}")
def add_meet_to_event(
    google_event_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    authorization: str = Header(..., alias="Authorization"),
    user_id: UUID = Depends(get_user_id),
):
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
        raise HTTPException(status_code=502, detail=f"Failed to add Meet: {e}")

    meet_url = _extract_meet_url(updated) or updated.get("hangoutLink")
    if not meet_url:
        raise HTTPException(status_code=500, detail="Meet link not found in updated event")
    return {"meet_url": meet_url}


@router.get("/event-meet-link/{google_event_id}")
def get_event_meet_link(
    google_event_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    authorization: str = Header(..., alias="Authorization"),
    user_id: UUID = Depends(get_user_id),
):
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)
    try:
        ev = cal.events().get(
            calendarId="primary",
            eventId=google_event_id,
            conferenceDataVersion=1,
        ).execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch event: {e}")

    return {"meet_url": _extract_meet_url(ev)}


@router.delete("/calendar/{google_event_id}")
def delete_google_calendar_event(
    google_event_id: str,
    tenant_id: UUID = Depends(get_tenant_id),
    authorization: str = Header(..., alias="Authorization"),
    user_id: UUID = Depends(get_user_id),
):
    access = _fetch_google_access_token(authorization=authorization, tenant_id=tenant_id)
    cal = _calendar_service(access)
    try:
        cal.events().delete(calendarId="primary", eventId=google_event_id).execute()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete event: {e}")
    return {"success": True}


@router.post("/calendar/event")
async def create_google_calendar_event_stub():
    """
    Optional legacy endpoint.
    If needed, implement creation of Google Calendar events here.
    """
    raise HTTPException(status_code=410, detail="Not implemented: create events through /api/calendar (local) or extend users-service")

