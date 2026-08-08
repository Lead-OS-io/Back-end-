from app.serializers.identity import IDENTITY_HEADERS, identity_headers_from_claims


def test_identity_headers_from_full_claims():
    # El JWT real emite `sub` (user id) y `tenant_id` como claims.
    headers = identity_headers_from_claims(
        {"sub": "7", "tenant_id": "42", "role_id": 1, "is_superuser": True}
    )
    assert headers == {
        "X-User-Id": "7",
        "X-Tenant-Id": "42",
        "X-Is-Superuser": "true",
        "X-Role-Id": "1",
    }


def test_identity_headers_minimal_claims():
    headers = identity_headers_from_claims({"sub": "3", "tenant_id": "5"})
    assert headers["X-Is-Superuser"] == "false"
    assert "X-Role-Id" not in headers


def test_identity_headers_omits_tenant_when_null():
    headers = identity_headers_from_claims({"sub": "3", "tenant_id": None})
    assert headers == {"X-User-Id": "3", "X-Is-Superuser": "false"}
    assert "X-Tenant-Id" not in headers


def test_identity_headers_tuple_covers_service_token():
    assert "X-Service-Token" in IDENTITY_HEADERS
