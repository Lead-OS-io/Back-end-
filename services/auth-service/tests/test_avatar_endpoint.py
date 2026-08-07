import io
from passlib.context import CryptContext
import uuid as _uuid

from app.models.entities import User
from app.models.enums import UserStatus
from app.services.auth_tokens import mint_access_token


_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _png():
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


def _seeded_user_and_token(db_session):
    user = User(
        id=_uuid.uuid4(),
        email=f"avatar-{_uuid.uuid4()}@x.com",
        password_hash=_PWD.hash("x"),
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token, _ = mint_access_token(
        user_id=user.id, tenant_id=None, status="active",
        ttl_minutes=15, secret="test-secret-key-0123456789abcdef",
    )
    return user, {"Authorization": f"Bearer {token}"}


def test_post_avatar_returns_200(client, db_session):
    _, headers = _seeded_user_and_token(db_session)
    files = {"file": ("a.png", io.BytesIO(_png()), "image/png")}
    resp = client.post("/api/auth/me/avatar", files=files, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"].startswith("https://test/")


def test_post_avatar_rejects_too_big(client, db_session, settings):
    _, headers = _seeded_user_and_token(db_session)
    big = b"x" * (settings.AVATAR_MAX_BYTES + 1)
    files = {"file": ("a.png", io.BytesIO(big), "image/png")}
    resp = client.post("/api/auth/me/avatar", files=files, headers=headers)
    assert resp.status_code == 413


def test_post_avatar_rejects_bad_mime(client, db_session):
    _, headers = _seeded_user_and_token(db_session)
    files = {"file": ("a.gif", io.BytesIO(_png()), "image/gif")}
    resp = client.post("/api/auth/me/avatar", files=files, headers=headers)
    assert resp.status_code == 415


def test_get_avatar_returns_302(client, db_session):
    _, headers = _seeded_user_and_token(db_session)
    files = {"file": ("a.png", io.BytesIO(_png()), "image/png")}
    client.post("/api/auth/me/avatar", files=files, headers=headers)
    resp = client.get("/api/auth/me/avatar", headers=headers, follow_redirects=False)
    assert resp.status_code == 302
    assert "https://test/" in resp.headers["location"]


def test_get_avatar_returns_404_when_no_avatar(client, db_session):
    _, headers = _seeded_user_and_token(db_session)
    resp = client.get("/api/auth/me/avatar", headers=headers)
    assert resp.status_code == 404


def test_delete_avatar_returns_204(client, db_session):
    _, headers = _seeded_user_and_token(db_session)
    files = {"file": ("a.png", io.BytesIO(_png()), "image/png")}
    client.post("/api/auth/me/avatar", files=files, headers=headers)
    resp = client.delete("/api/auth/me/avatar", headers=headers)
    assert resp.status_code == 204
