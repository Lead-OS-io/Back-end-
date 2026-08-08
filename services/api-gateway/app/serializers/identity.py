IDENTITY_HEADERS = ("X-User-Id", "X-Tenant-Id", "X-Role-Id", "X-Is-Superuser", "X-Service-Token")


def identity_headers_from_claims(claims: dict) -> dict[str, str]:
    # El JWT de usuario de auth-service emite `sub` como user id y `tenant_id`.
    headers = {
        "X-User-Id": str(claims["sub"]),
        "X-Is-Superuser": "true" if claims.get("is_superuser") else "false",
    }
    tenant_id = claims.get("tenant_id")
    if tenant_id is not None:
        headers["X-Tenant-Id"] = str(tenant_id)
    if claims.get("role_id") is not None:
        headers["X-Role-Id"] = str(claims["role_id"])
    return headers
