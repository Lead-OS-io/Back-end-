import uuid


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        phone="+14155550100",
        business_name="Acme Co",
        timezone="America/Mexico_City",
        legal_name="Acme Co LLC",
        support_inbox="support@acme.com",
    )
    base.update(over)
    return base


def test_returns_202_with_pending_status(client):
    # Reduce long-poll timeout so the test does not wait the default 10s.
    client.app.state.settings.ONBOARDING_LONG_POLL_SECONDS = 1
    resp = client.post("/api/auth/onboarding", json=_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert "user_id" in body
    assert body["status"] == "pending_tenant"


def test_onboarding_completes_and_returns_200(client):
    from app.services.onboarding_completion import OnboardingCompletion, OnboardingCompletionRegistry

    class AutoCompleteRegistry(OnboardingCompletionRegistry):
        def register(self, user_id):
            event = super().register(user_id)
            self.complete(
                OnboardingCompletion(
                    user_id=user_id,
                    tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
                )
            )
            return event

    settings = client.app.state.settings
    settings.ONBOARDING_LONG_POLL_SECONDS = 5
    client.app.state.completion_registry = AutoCompleteRegistry()

    resp = client.post("/api/auth/onboarding", json=_payload(email="complete@acme.com"))
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["status"] == "active"
    assert body["user"]["tenant_id"] == "00000000-0000-0000-0000-000000000099"
    assert "refresh_token" in resp.cookies


def test_duplicate_email_returns_409(client):
    client.app.state.settings.ONBOARDING_LONG_POLL_SECONDS = 1
    client.post("/api/auth/onboarding", json=_payload())
    resp = client.post("/api/auth/onboarding", json=_payload())
    assert resp.status_code == 409


def test_short_password_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(password="short"))
    assert resp.status_code == 422


def test_missing_business_name_returns_422(client):
    payload = _payload()
    payload.pop("business_name")
    resp = client.post("/api/auth/onboarding", json=payload)
    assert resp.status_code == 422


def test_invalid_email_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(email="not-an-email"))
    assert resp.status_code == 422


def test_phone_optional_returns_202(client):
    client.app.state.settings.ONBOARDING_LONG_POLL_SECONDS = 1
    payload = _payload()
    payload.pop("phone")
    resp = client.post("/api/auth/onboarding", json=payload)
    assert resp.status_code == 202


def test_invalid_phone_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(phone="not-a-phone"))
    assert resp.status_code == 422


def test_too_short_phone_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(phone="+1"))
    assert resp.status_code == 422


def test_invalid_timezone_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(timezone="Mars/Olympus"))
    assert resp.status_code == 422


def test_invalid_support_inbox_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(support_inbox="not-an-email"))
    assert resp.status_code == 422
