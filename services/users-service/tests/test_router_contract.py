"""Contrato del router de users-service (Task 26)."""
import uuid
from datetime import datetime

from tests import TENANT_ID, USER_ID


class _StubUser:
    def __init__(self, **kw):
        self.id = USER_ID
        self.tenant_id = TENANT_ID
        self.email = "u@x.com"
        self.first_name = "U"
        self.last_name = None
        self.middle_name = None
        self.country_code = None
        self.mobile = None
        self.npn = None
        self.anpn = None
        self.compensation = None
        self.job_title = None
        self.role_id = 2
        self.is_individual = None
        self.business_name = None
        self.tax_number = None
        self.fein = None
        self.residential_address = None
        self.mailing_address = None
        self.business_address = None
        self.permissions = None
        self.is_active = True
        self.is_staff = False
        self.is_superuser = False
        self.date_joined = datetime.utcnow()
        self.last_login = None
        self.upline_id = None
        self.invited_by_id = None
        self.production_upline_id = None
        self.accepted_campaign_terms_at = None
        self.accepted_underwriter_terms_at = None
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        for k, v in kw.items():
            setattr(self, k, v)


class _StubAgentSetting:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.user_id = USER_ID
        self.tenant_id = TENANT_ID
        self.settings = {}
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        for k, v in kw.items():
            setattr(self, k, v)


class _StubUserRequest:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.user_id = USER_ID
        self.tenant_id = TENANT_ID
        self.request_type = "other_request"
        self.data = {}
        self.status = "pending"
        self.created_by_id = USER_ID
        self.reviewed_by_id = None
        self.reviewed_at = None
        self.notes = None
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        for k, v in kw.items():
            setattr(self, k, v)


class _StubCalendarEvent:
    def __init__(self, **kw):
        self.id = 1
        self.title = "Event"
        self.description = None
        self.event_type = "call"
        self.start_date = datetime.utcnow()
        self.end_date = datetime.utcnow()
        self.all_day = False
        self.timezone = "America/New_York"
        self.location = None
        self.color = "#465fff"
        self.priority = "medium"
        self.status = "scheduled"
        self.assigned_to_id = None
        self.case_data_id = None
        self.policy_id = None
        self.agency_id = None
        self.reminder_before_minutes = 15
        self.visibility = "private"
        self.shared_with = []
        self.tenant_id = TENANT_ID
        self.owner_id = USER_ID
        self.created_by_id = USER_ID
        self.is_active = True
        self.reminder_sent = False
        self.reminder_sent_at = None
        self.google_calendar_id = None
        self.google_calendar_synced = False
        self.google_calendar_synced_at = None
        self.meet_url = None
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        for k, v in kw.items():
            setattr(self, k, v)


def _create_payload() -> dict:
    return {
        "email": "u@x.com", "password": "Pw123456", "tenant_id": str(TENANT_ID),
        "first_name": "U",
    }


# ---- Health ----
def test_health_ok(client):
    assert client.get("/health").status_code == 200


# ---- CRUD users ----
def test_create_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user_by_email", lambda **kwargs: None)
    monkeypatch.setattr("app.services.users.create_user", lambda **kwargs: _StubUser())
    resp = client.post("/api/users", json=_create_payload(), headers=svc_headers)
    assert resp.status_code == 201
    assert resp.json()["email"] == "u@x.com"


def test_get_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    resp = client.get(f"/api/users/{USER_ID}", headers=svc_headers)
    assert resp.status_code == 200


def test_get_user_missing_is_404(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: None)
    resp = client.get(f"/api/users/{USER_ID}", headers=svc_headers)
    assert resp.status_code == 404


def test_list_users(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.list_users",
                        lambda **kwargs: ([_StubUser()], 1))
    resp = client.get("/api/users", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_update_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.update_user", lambda **kwargs: _StubUser(first_name="U2"))
    resp = client.put(f"/api/users/{USER_ID}", json={"first_name": "U2"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "U2"


def test_delete_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.delete_user", lambda **kwargs: None)
    resp = client.delete(f"/api/users/{USER_ID}", headers=svc_headers)
    assert resp.status_code == 204


def test_user_stats(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user_stats",
                        lambda **kwargs: {"total_users": 3, "active_users": 2,
                                          "agents": 1, "opt_in_records": 0})
    resp = client.get("/api/users/stats", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["total_users"] == 3


def test_me(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_current_user", lambda **kwargs: _StubUser())
    resp = client.get("/api/users/me", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(USER_ID)


# ---- Agent settings ----
def test_get_agent_settings(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.get_or_create_agent_settings",
                        lambda **kwargs: _StubAgentSetting())
    resp = client.get(f"/api/users/{USER_ID}/agent-settings", headers=svc_headers)
    assert resp.status_code == 200


def test_update_agent_settings(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.get_or_create_agent_settings",
                        lambda **kwargs: _StubAgentSetting())
    monkeypatch.setattr("app.services.users.update_agent_settings",
                        lambda **kwargs: _StubAgentSetting(settings={"a": 1}))
    resp = client.put(f"/api/users/{USER_ID}/agent-settings",
                      json={"settings": {"a": 1}}, headers=svc_headers)
    assert resp.status_code == 200


# ---- User requests ----
def test_create_user_request(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.create_user_request",
                        lambda **kwargs: _StubUserRequest())
    resp = client.post(f"/api/users/{USER_ID}/requests",
                       json={"request_type": "other_request", "data": {}},
                       headers=svc_headers)
    assert resp.status_code == 201


def test_list_user_requests(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.list_user_requests",
                        lambda **kwargs: ([_StubUserRequest()], 1))
    resp = client.get(f"/api/users/{USER_ID}/requests", headers=svc_headers)
    assert resp.status_code == 200


def test_update_user_request(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.users.get_user", lambda **kwargs: _StubUser())
    monkeypatch.setattr("app.services.users.get_user_request",
                        lambda **kwargs: _StubUserRequest())
    monkeypatch.setattr("app.services.users.update_user_request",
                        lambda **kwargs: _StubUserRequest(status="approved"))
    resp = client.put(f"/api/users/{USER_ID}/requests/{uuid.uuid4()}",
                      json={"status": "approved"}, headers=svc_headers)
    assert resp.status_code == 200


# ---- Webhook Aria (ruta pública: service-token via gateway + X-API-Key) ----
def test_webhook_aria_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.webhooks.handle_aria_webhook",
                        lambda **kwargs: {"status": "processed"})
    payload = {
        "event_type": "ACCESS_GRANTED",
        "timestamp": datetime.utcnow().isoformat(),
        "user": {"email": "u@x.com", "first_name": "U", "last_name": None},
    }
    resp = client.post("/api/saas/webhooks/aria", json=payload,
                       headers={**svc_headers, "X-API-Key": "test-webhook-key"})
    assert resp.status_code == 200


def test_webhook_aria_bad_key_is_401(client, svc_headers):
    payload = {"event_type": "ACCESS_GRANTED", "timestamp": datetime.utcnow().isoformat(),
               "user": {"email": "u@x.com"}}
    resp = client.post("/api/saas/webhooks/aria", json=payload,
                       headers={**svc_headers, "X-API-Key": "wrong-key"})
    assert resp.status_code == 401


# ---- Calendar ----
def test_create_calendar_event(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.create_event",
                        lambda **kwargs: _StubCalendarEvent())
    resp = client.post("/api/calendar",
                       json={"title": "Event", "event_type": "call",
                             "start_date": "2026-08-10T10:00:00",
                             "end_date": "2026-08-10T11:00:00"},
                       headers=svc_headers)
    assert resp.status_code == 201


def test_list_calendar_events(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.list_events",
                        lambda **kwargs: [_StubCalendarEvent()])
    resp = client.get("/api/calendar", headers=svc_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_update_calendar_event(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.get_event", lambda **kwargs: _StubCalendarEvent())
    monkeypatch.setattr("app.services.calendar.update_event",
                        lambda **kwargs: _StubCalendarEvent(title="Updated"))
    resp = client.put("/api/calendar/1", json={"title": "Updated"}, headers=svc_headers)
    assert resp.status_code == 200


def test_delete_calendar_event(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.get_event", lambda **kwargs: _StubCalendarEvent())
    monkeypatch.setattr("app.services.calendar.delete_event",
                        lambda **kwargs: {"message": "Calendar event deleted successfully"})
    resp = client.delete("/api/calendar/1", headers=svc_headers)
    assert resp.status_code == 200


def test_upcoming_reminders(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.upcoming_reminders",
                        lambda **kwargs: [{
                            "id": 1, "type": "reminder", "title": "R", "time": "10:00",
                            "status": "upcoming", "event_type": "call",
                            "start_date": "2026-08-10T10:00:00",
                            "end_date": "2026-08-10T11:00:00",
                        }])
    resp = client.get("/api/calendar/reminders/upcoming", headers=svc_headers)
    assert resp.status_code == 200


def test_policy_warnings_sync(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.sync_policy_warnings",
                        lambda **kwargs: {"created": 2})
    resp = client.post("/api/calendar/policy-warnings/sync", json={"alerts": []},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["created"] == 2


# ---- Google calendar ----
def test_google_calendar_debug(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.debug_calendar_events",
                        lambda **kwargs: {"events": []})
    resp = client.get("/api/users/google/debug-calendar-events", headers=svc_headers)
    assert resp.status_code == 200


def test_google_event_add_meet(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.add_meet_link",
                        lambda **kwargs: {"meet_url": "https://meet.google.com/x"})
    resp = client.patch("/api/users/google/event-add-meet/evt1", headers=svc_headers)
    assert resp.status_code == 200


def test_google_event_meet_link(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.get_meet_link",
                        lambda **kwargs: {"meet_url": "https://meet.google.com/x"})
    resp = client.get("/api/users/google/event-meet-link/evt1", headers=svc_headers)
    assert resp.status_code == 200


def test_google_calendar_delete(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.calendar.delete_google_event",
                        lambda **kwargs: {"deleted": True})
    resp = client.delete("/api/users/google/calendar/evt1", headers=svc_headers)
    assert resp.status_code == 200


def test_google_calendar_create_event(client, svc_headers):
    # Stub heredado: crear eventos Google se hace via /api/calendar (local).
    resp = client.post("/api/users/google/calendar/event", json={"title": "E"},
                       headers=svc_headers)
    assert resp.status_code == 410


# ---- Enforcement ----
def test_missing_service_token_is_401(client):
    assert client.get("/api/users").status_code == 401
