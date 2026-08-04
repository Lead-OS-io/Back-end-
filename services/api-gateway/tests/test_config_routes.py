from app.config import Settings


def test_service_routes_cover_all_public_prefixes():
    s = Settings(SERVICE_NAME="api-gateway", INTER_SERVICE_SECRET="x", SECRET_KEY="y")
    routes = s.service_routes
    assert routes["/api/auth"] == s.AUTH_SERVICE_URL
    assert routes["/api/tenants"] == s.TENANT_SERVICE_URL
    assert routes["/api/users"] == s.USERS_SERVICE_URL
    assert routes["/api/files"] == s.FILES_SERVICE_URL
    assert routes["/api/resolve"] == s.TENANT_SERVICE_URL
    assert "/api/internal" not in routes
    assert "/api/saas/webhooks" not in routes
