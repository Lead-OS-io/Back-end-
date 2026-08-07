def test_refresh_rotates_and_returns_new_tokens(client, db_session):
    from app.services.login import authenticate_and_open_session
    from app.config import Settings
    from passlib.context import CryptContext
    from app.models.entities import User
    from app.models.enums import UserStatus
    import uuid as _uuid

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=_uuid.uuid4(), email="a@a.com",
        password_hash=pwd.hash("verysecurepw"), status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    settings = Settings(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="test-inter-service-secret",
        SECRET_KEY="test-secret-key-0123456789abcdef",
        REDIS_URL="redis://x",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_MINUTES=60,
    )
    outcome = authenticate_and_open_session(
        db=db_session, settings=settings,
        email="a@a.com", password="verysecurepw",
    )

    resp = client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": outcome.refresh_token},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie


def test_refresh_without_cookie_is_401(client):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
