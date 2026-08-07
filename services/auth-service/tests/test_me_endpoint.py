def _seed_user(db_session):
    from passlib.context import CryptContext
    from app.models.entities import User
    from app.models.enums import UserStatus
    import uuid as _uuid

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=_uuid.uuid4(), email="u@u.com",
        password_hash=pwd.hash("x"),
        full_name="Original", phone="+14155550100",
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _bearer(client, user_id):
    from app.services.auth_tokens import mint_access_token

    token, _ = mint_access_token(
        user_id=user_id, tenant_id=None, status="active",
        ttl_minutes=15, secret="test-secret-key-0123456789abcdef",
    )
    return {"Authorization": f"Bearer {token}"}


def test_me_returns_profile(client, db_session):
    user = _seed_user(db_session)
    resp = client.get("/api/auth/me", headers=_bearer(client, user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "u@u.com"
    assert body["has_avatar"] is False


def test_patch_me_updates_full_name_and_phone(client, db_session):
    user = _seed_user(db_session)
    resp = client.patch(
        "/api/auth/me",
        headers=_bearer(client, user.id),
        json={"full_name": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New Name"


def test_patch_me_rejects_email_field(client, db_session):
    user = _seed_user(db_session)
    resp = client.patch(
        "/api/auth/me",
        headers=_bearer(client, user.id),
        json={"email": "evil@x.com"},
    )
    assert resp.status_code == 422


def test_me_returns_avatar_summary_when_remote_has_avatar(
    client, db_session, fake_files_read_client
):
    from app.services.avatars_read import _set_files_read_client_for_tests

    user = _seed_user(db_session)
    fake_files_read_client.set_has_avatar(True, url="https://example/x.png?sig=1")
    _set_files_read_client_for_tests(fake_files_read_client)
    try:
        resp = client.get("/api/auth/me", headers=_bearer(client, user.id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_avatar"] is True
        assert body["avatar_url"] == "https://example/x.png?sig=1"
    finally:
        from app.services.avatars_read import _reset_files_read_client_for_tests
        _reset_files_read_client_for_tests()


def test_me_returns_no_avatar_when_remote_404(
    client, db_session, fake_files_read_client
):
    from app.services.avatars_read import _set_files_read_client_for_tests

    user = _seed_user(db_session)
    fake_files_read_client.set_has_avatar(False)
    _set_files_read_client_for_tests(fake_files_read_client)
    try:
        resp = client.get("/api/auth/me", headers=_bearer(client, user.id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_avatar"] is False
        assert body["avatar_url"] is None
    finally:
        from app.services.avatars_read import _reset_files_read_client_for_tests
        _reset_files_read_client_for_tests()
