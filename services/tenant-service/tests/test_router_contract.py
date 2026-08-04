"""Contrato del router de tenant-service (Task 22)."""
import uuid
from datetime import datetime

from shared.utils.exceptions import AppError

TENANT_ID = str(uuid.uuid4())


class _StubTenant:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.name = "Acme"
        self.slug = "acme"
        self.custom_domain = None
        self.domain_status = "pending"
        self.status = "active"
        self.is_active = True
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        self.owner_email = "owner@x.com"
        self.billing_email = None
        self.settings = {}
        self.branding = {}
        self.limits = {}
        self.features = {}
        self.trial_ends_at = None
        for k, v in kw.items():
            setattr(self, k, v)


class _StubDomain:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.domain = "app.acme.airedesk.com"
        self.domain_type = "subdomain"
        self.status = "pending"
        self.ssl_status = "pending"
        self.created_at = datetime.utcnow()
        self.tenant_id = TENANT_ID
        for k, v in kw.items():
            setattr(self, k, v)


def _mocked_tenant(**kw):
    t = _StubTenant(**kw)
    return {"tenant": t, "id": str(t.id)}


# ---- Health ----
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "tenant-service"


# ---- Resolve (público) ----
def test_resolve_by_host(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.resolve_tenant",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.get("/api/resolve", params={"host": "acme.airedesk.com"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["slug"] == "acme"


def test_resolve_by_email(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.resolve_tenant_by_email",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.get("/api/resolve/email", params={"email": "u@x.com"}, headers=svc_headers)
    assert resp.status_code == 200


def test_resolve_by_slug(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.resolve_tenant_by_slug",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.get("/api/resolve/acme", headers=svc_headers)
    assert resp.status_code == 200


def test_resolve_missing_is_404(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.resolve_tenant_by_slug",
                        lambda **kwargs: None)
    resp = client.get("/api/resolve/nope", headers=svc_headers)
    assert resp.status_code == 404


# ---- CRUD tenants ----
def test_create_tenant_admin(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.create_tenant",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.post("/api/tenants",
                       json={"name": "Acme", "slug": "acme", "owner_email": "owner@x.com"},
                       headers=svc_headers)
    assert resp.status_code == 201
    assert resp.json()["slug"] == "acme"


def test_create_tenant_forbidden_for_regular_user(client, svc_headers, monkeypatch):
    from shared.auth.dependencies import Identity, get_current_identity

    client.app.dependency_overrides[get_current_identity] = (
        lambda: Identity(user_id=2, tenant_id=1, role_id=2, is_superuser=False))
    resp = client.post("/api/tenants",
                       json={"name": "Acme", "slug": "acme2", "owner_email": "owner@x.com"},
                       headers=svc_headers)
    assert resp.status_code == 403


def test_list_tenants(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.list_tenants",
                        lambda **kwargs: ([_mocked_tenant()["tenant"]], 1))
    resp = client.get("/api/tenants", headers=svc_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_tenant(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.get_tenant",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.get(f"/api/tenants/{TENANT_ID}", headers=svc_headers)
    assert resp.status_code == 200


def test_get_tenant_missing_is_404(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.get_tenant", lambda **kwargs: None)
    resp = client.get(f"/api/tenants/{TENANT_ID}", headers=svc_headers)
    assert resp.status_code == 404


def test_update_tenant_admin(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.update_tenant",
                        lambda **kwargs: _mocked_tenant()["tenant"])
    resp = client.put(f"/api/tenants/{TENANT_ID}", json={"name": "Acme2"},
                      headers=svc_headers)
    assert resp.status_code == 200


# ---- Domains ----
def test_create_subdomain(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.cloudflare.create_subdomain",
                        lambda **kwargs: _StubDomain())
    resp = client.post(f"/api/tenants/{TENANT_ID}/domains/subdomain",
                       json={"subdomain": "app2"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["domain_type"] == "subdomain"


def test_create_custom_domain(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.cloudflare.create_custom_domain",
                        lambda **kwargs: _StubDomain(domain="custom.io"))
    monkeypatch.setattr("app.services.cloudflare.get_verification_instructions",
                        lambda **kwargs: {
                            "domain": "custom.io", "status": "pending",
                            "verification_type": "cname",
                            "verification_record": {"name": "_custom.io", "value": "target"},
                            "instructions": "Add CNAME",
                        })
    monkeypatch.setattr("app.services.tenants.get_tenant",
                        lambda **kwargs: _mocked_tenant(features={"custom_domain": True})["tenant"])
    resp = client.post(f"/api/tenants/{TENANT_ID}/domains/custom",
                       json={"domain": "custom.io"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["verification_type"] == "cname"


def test_list_domains(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.list_domains",
                        lambda **kwargs: [_StubDomain()])
    resp = client.get(f"/api/tenants/{TENANT_ID}/domains", headers=svc_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_domain(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.get_domain",
                        lambda **kwargs: _StubDomain())
    resp = client.get(f"/api/tenants/{TENANT_ID}/domains/{uuid.uuid4()}", headers=svc_headers)
    assert resp.status_code == 200


def test_delete_domain_admin(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.delete_domain",
                        lambda **kwargs: None)
    resp = client.delete(f"/api/tenants/{TENANT_ID}/domains/{uuid.uuid4()}", headers=svc_headers)
    assert resp.status_code == 200


# ---- Internals (solo red interna, service token) ----
def test_active_ids_internal(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.list_active_tenant_ids",
                        lambda **kwargs: [TENANT_ID])
    resp = client.get("/api/internal/tenants/active-ids", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json() == [TENANT_ID]


def test_db_credentials_internal(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.tenants.get_tenant_db_credentials",
                        lambda **kwargs: {"db_host": "postgres", "db_port": 5432,
                                          "db_name": "tenant_db", "db_user": "lead_os",
                                          "db_password": "x", "db_sslmode": "require"})
    resp = client.get(f"/api/internal/tenants/{TENANT_ID}/db-credentials", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["db_name"] == "tenant_db"


# ---- Enforcement ----
def test_missing_service_token_is_401(client):
    assert client.get("/api/tenants").status_code == 401


def test_admin_requires_admin_identity(client, svc_headers, monkeypatch):
    from shared.auth.dependencies import Identity, get_current_identity

    client.app.dependency_overrides[get_current_identity] = (
        lambda: Identity(user_id=3, tenant_id=1, role_id=5, is_superuser=False))
    resp = client.post("/api/tenants",
                       json={"name": "X", "slug": "x1", "owner_email": "o@x.com"},
                       headers=svc_headers)
    assert resp.status_code == 403
