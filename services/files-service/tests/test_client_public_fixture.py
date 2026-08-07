"""Smoke test for the client_public fixture."""


def test_client_public_exposes_health(client_public):
    resp = client_public.get("/health")
    assert resp.status_code == 200
