def _login_payload(**over):
    base = dict(email="alice@acme.com", password="correctpw-12345")
    base.update(over)
    return base


def _register_test_user(db_session):
    from passlib.context import CryptContext
    from app.models.entities import User
    from app.models.enums import UserStatus
    import uuid as _uuid

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=_uuid.uuid4(),
        email="alice@acme.com",
        password_hash=pwd.hash("correctpw-12345"),
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_login_returns_access_token_and_sets_cookie(client, db_session):
    _register_test_user(db_session)
    resp = client.post("/api/auth/login", json=_login_payload())
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie


def test_login_invalid_credentials_401(client):
    resp = client.post("/api/auth/login", json=_login_payload(password="wrongpassword"))
    assert resp.status_code == 401


def test_login_unknown_email_401(client):
    resp = client.post("/api/auth/login", json=_login_payload(email="nobody@x.com"))
    assert resp.status_code == 401


def test_login_short_password_422(client):
    resp = client.post("/api/auth/login", json=_login_payload(password="short"))
    assert resp.status_code == 422
