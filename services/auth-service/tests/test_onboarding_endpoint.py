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
    resp = client.post("/api/auth/onboarding", json=_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert "user_id" in body
    assert body["status"] == "pending_tenant"


def test_duplicate_email_returns_409(client):
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
