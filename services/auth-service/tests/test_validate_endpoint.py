from shared.db.engine import get_db


def test_validate_without_bearer_returns_401(client):
    resp = client.get("/api/auth/validate")
    assert resp.status_code == 401


def test_validate_with_bearer_returns_200(client):
    from app.services.auth_tokens import mint_access_token
    from passlib.context import CryptContext
    from app.models.entities import User
    from app.models.enums import UserStatus
    import uuid as _uuid

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=_uuid.uuid4(), email="a@a.com",
        password_hash=pwd.hash("x"), status=UserStatus.ACTIVE.value,
    )
    db_session = client.app.dependency_overrides[get_db]()
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token, _ = mint_access_token(
        user_id=user.id, tenant_id=None, status="active",
        ttl_minutes=15, secret="test-secret-key-0123456789abcdef",
    )

    resp = client.get("/api/auth/validate", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
