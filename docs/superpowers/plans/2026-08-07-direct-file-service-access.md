# Direct File-Service Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the frontend talk to `files-service` directly through `api-gateway` for avatar lifecycle (upload, get, delete, presign), so `auth-service` stops owning avatar endpoints and the column `users.avatar_media_id` disappears from its DB.

**Architecture:** Two routers in the same FastAPI app inside `files-service`. The existing `/internal/files/*` router (protected by `X-Service-Token`) is reduced to the two read endpoints that `auth-service` still needs to enrich `/me`. A new `/public/files/*` router is mounted, protected by a `PublicAuthMiddleware` that validates the `X-User-Id` header (injected by the gateway from the user's JWT) and enforces `user_id` ownership. `auth-service` deletes `FilesClient`, the avatar service module, the three `/me/avatar*` endpoints, and the `avatar_media_id` column, keeping only a thin read helper to fill `has_avatar`/`avatar_url` in `UserResponse`.

**Tech Stack:** Python 3.12, FastAPI 0.104.1, SQLModel 0.0.14, Pydantic v2, pytest 7.4.3, httpx 0.27.0, fakeredis 2.20.0, uv. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-direct-file-service-access-design.md` (commit `5e71cbb`).

## Global Constraints

These apply to every task. Copied verbatim from the spec:

- Frontend MUST go through `api-gateway` (`/api/files/...`); never reach `files-service` directly.
- The new public endpoints MUST validate `X-User-Id` is a UUID and enforce `user_id == X-User-Id` on every resource access. No admin override in this spec (deferred to a future plan).
- File validation lives in `files-service`: `AVATAR_MAX_BYTES = 5 * 1024 * 1024`, `AVATAR_ALLOWED_MIMETYPES = ("image/jpeg", "image/png", "image/webp")`, file must be non-empty. Source of truth: `services/files-service/.env` and `services/files-service/app/config.py`.
- Upload is upsert: a new upload deletes the previous avatar (object + DB row) before writing the new one. Matches today's behavior.
- GET returns 302 to a presigned URL with TTL = `settings.PRESIGN_TTL_SECONDS` (default 300s).
- `user.avatar.changed` / `user.avatar.removed` events are published by `files-service` (not `auth-service`) on domain `"onboarding"`, with the same envelope shape `auth-service` already uses.
- `auth-service` keeps `FilesClient`-style HTTP calls to `files-service` only for the read path used by `_build_user_response`. No upload/delete calls in `auth-service` after this plan.
- `auth-service` `/auth/me`, `/auth/login`, `/auth/refresh`, `/auth/me PATCH` continue to return `has_avatar`/`avatar_url` in `UserResponse`. If `files-service` 404s or 5xxs, `has_avatar=false`, `avatar_url=null`, no side effect on `auth_db`.
- `users.avatar_media_id` column is dropped via Alembic migration `0003_drop_avatar_media_id`.
- Tests use in-memory sqlite + `fakeredis` + `FakeStorage`. No Docker, no real Postgres/Redis/MinIO.
- Run unit tests with: `cd shared && uv run pytest -q` and `cd services/<svc> && uv run pytest -q`.

## File Structure

Created or modified by this plan. Each file has one clear responsibility.

**Shared (one file modified):**
- `shared/src/shared/auth/middleware.py` — extend `ServiceTokenMiddleware` to support `exempt_prefixes` alongside exact-path exempt list.
- `shared/tests/test_auth_middleware.py` — add tests for prefix-exempt behavior.

**files-service (created or modified):**
- `services/files-service/app/auth.py` (new) — `PublicAuthMiddleware`, `get_current_identity` FastAPI dependency, local `Identity` dataclass (UUID-based).
- `services/files-service/app/public_router.py` (new) — 4 endpoints: `POST/GET/DELETE /users/me/avatar` and `GET /media/{media_id}/presign`. Validates uploads, publishes events.
- `services/files-service/app/internal_router.py` (modified) — remove `POST /users/{user_id}/avatar` and `DELETE /users/{user_id}/avatar` handlers.
- `services/files-service/app/main.py` (modified) — mount `public_router`, register `PublicAuthMiddleware`, expand `ServiceTokenMiddleware` exempt list to skip `/public/*`.
- `services/files-service/tests/conftest.py` (modified) — add `client_public` fixture (no `X-Service-Token`, with `X-User-Id`).
- `services/files-service/tests/test_auth.py` (new) — tests for `PublicAuthMiddleware` and `get_current_identity`.
- `services/files-service/tests/test_public_router.py` (new) — endpoint tests.
- `services/files-service/tests/test_internal_router_avatar.py` (modified) — drop the two tests for POST/DELETE internal endpoints.
- `services/files-service/README.md` (modified) — document the dual-router layout.

**auth-service (created or modified):**
- `services/auth-service/app/services/avatars_read.py` (new) — `AvatarSummary`, `FilesReadClient` Protocol, `get_avatar_summary`, test seam.
- `services/auth-service/app/services/avatars.py` (deleted).
- `services/auth-service/app/services/files_client.py` (deleted).
- `services/auth-service/app/schemas/avatar.py` (deleted).
- `services/auth-service/app/controller.py` (modified) — remove `get_my_avatar_response`, `post_my_avatar`, `delete_my_avatar`; update `_build_user_response` to use `get_avatar_summary`.
- `services/auth-service/app/router.py` (modified) — remove `GET/POST/DELETE /me/avatar` routes.
- `services/auth-service/app/services/__init__.py` (modified) — drop `FilesClient`, `MediaRef`, `delete_avatar_for_user`, `get_avatar_for_user`, `upload_avatar_for_user` re-exports.
- `services/auth-service/app/models/entities.py` (modified) — remove `User.avatar_media_id`.
- `services/auth-service/app/config.py` (modified) — remove `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS`, and the `_split_avatar_mimetypes` validator.
- `services/auth-service/migrations/versions/0003_drop_avatar_media_id.py` (new) — Alembic migration.
- `services/auth-service/tests/conftest.py` (modified) — drop `FakeFilesClient`/`fake_files_client`/`_FILES_CLIENT_OVERRIDE`; drop `AVATAR_*`/`PRESIGN_*` from `settings` fixture; add `fake_files_read_client` and patch `_FILES_READ_CLIENT_OVERRIDE`.
- `services/auth-service/tests/test_files_client.py` (deleted).
- `services/auth-service/tests/test_avatar_endpoint.py` (deleted).
- `services/auth-service/tests/test_avatars_service.py` (deleted).
- `services/auth-service/tests/test_avatars_read.py` (new) — tests for the new read helper.
- `services/auth-service/tests/test_refresh_token_model.py` (modified) — drop `test_user_has_avatar_media_id_column`.
- `scripts/smoke-files-avatar.sh` (new) — replace `scripts/smoke-auth-avatar.sh`.

**Out of scope (do NOT modify):**
- `services/api-gateway/**` — config already routes `/api/files` to `files-service` and injects `X-User-Id` for non-public paths. No code changes needed.
- `services/files-service/app/storage/**` — `MediaManager` is the shared helper both routers use; no behavior change.
- `services/files-service/app/schemas/internal.py` — `MediaRef` and `PresignResponse` are reused as-is for both routers.

---

## Phase A — Shared middleware supports prefix-exempt

### Task A1: Extend `ServiceTokenMiddleware` with `exempt_prefixes`

**Files:**
- Modify: `shared/src/shared/auth/middleware.py:1-31`
- Test: `shared/tests/test_auth_middleware.py`

**Interfaces:**
- Consumes: (none — pure refactor of existing code)
- Produces: `ServiceTokenMiddleware.__init__(self, app, *, secret, exempt_paths=EXEMPT_PATHS, exempt_prefixes=frozenset())` — same behavior as today when `exempt_prefixes` is empty; when set, any path starting with a prefix in the set is also exempt from token validation.

**Why:** Today the middleware does `scope["path"] in self.exempt_paths` (exact match). The new public router mounts at `/public/files/...` — there are many paths, not one exact path. Rather than enumerate them, we add prefix-exempt support. Backwards compatible.

- [ ] **Step 1: Write the failing test**

Append to `shared/tests/test_auth_middleware.py` (the file already imports `FastAPI`, `TestClient`, `ServiceTokenMiddleware` at lines 1-6):

```python
def test_prefix_exempt_path_is_allowed_without_token():
    app = FastAPI()
    app.add_middleware(
        ServiceTokenMiddleware,
        secret=SECRET,
        exempt_prefixes=frozenset({"/public"}),
    )

    @app.get("/public/health")
    def health():
        return {"ok": True}

    assert TestClient(app).get("/public/health").status_code == 200


def test_non_matching_prefix_still_requires_token():
    app = FastAPI()
    app.add_middleware(
        ServiceTokenMiddleware,
        secret=SECRET,
        exempt_prefixes=frozenset({"/public"}),
    )

    @app.get("/internal/ping")
    def ping():
        return {"ok": True}

    assert TestClient(app).get("/internal/ping").status_code == 401


def test_exact_match_still_works_alongside_prefix():
    app = FastAPI()
    app.add_middleware(
        ServiceTokenMiddleware,
        secret=SECRET,
        exempt_paths=frozenset({"/health"}),
        exempt_prefixes=frozenset({"/public"}),
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/public/anything")
    def anything():
        return {"ok": True}

    @app.get("/secure")
    def secure():
        return {"ok": True}

    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/public/anything").status_code == 200
    assert c.get("/secure").status_code == 401
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd shared && uv run pytest tests/test_auth_middleware.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'exempt_prefixes'` (the middleware signature does not accept it yet).

- [ ] **Step 3: Modify `shared/src/shared/auth/middleware.py`**

Replace the whole file contents with:

```python
import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from shared.auth.service_token import decode_service_token

EXEMPT_PATHS = frozenset({"/health"})


class ServiceTokenMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        secret: str,
        exempt_paths: frozenset[str] = EXEMPT_PATHS,
        exempt_prefixes: frozenset[str] = frozenset(),
    ):
        self.app = app
        self.secret = secret
        self.exempt_paths = exempt_paths
        self.exempt_prefixes = exempt_prefixes

    def _is_exempt(self, path: str) -> bool:
        if path in self.exempt_paths:
            return True
        return any(path.startswith(prefix) for prefix in self.exempt_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._is_exempt(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        token = headers.get(b"x-service-token", b"").decode()
        try:
            decode_service_token(token, secret=self.secret)
        except jwt.InvalidTokenError:
            response = JSONResponse({"detail": "invalid service token"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
```

- [ ] **Step 4: Re-run the new tests to verify they pass**

Run: `cd shared && uv run pytest tests/test_auth_middleware.py -v`
Expected: PASS (the 3 new tests plus the 5 existing tests).

- [ ] **Step 5: Run the full shared test suite**

Run: `cd shared && uv run pytest -q`
Expected: PASS (no regression in other shared tests that use `ServiceTokenMiddleware`).

- [ ] **Step 6: Commit**

```bash
git add shared/src/shared/auth/middleware.py shared/tests/test_auth_middleware.py
git commit -m "feat(shared): ServiceTokenMiddleware supports exempt_prefixes"
```

---

## Phase B — files-service: new public router with identity middleware

### Task B1: Create `app/auth.py` with `PublicAuthMiddleware` and identity dependency

**Files:**
- Create: `services/files-service/app/auth.py`
- Create: `services/files-service/tests/test_auth.py`

**Interfaces:**
- Consumes: (none)
- Produces:
  - `class Identity` — frozen dataclass with fields `user_id: uuid.UUID`, `tenant_id: uuid.UUID | None`, `is_superuser: bool`.
  - `class PublicAuthMiddleware(BaseHTTPMiddleware)` — reads `X-User-Id` and `X-Tenant-Id` from request headers when path starts with `/public`; rejects with 401 if missing or not UUID; populates `request.state.identity`. No-op for non-`/public` paths.
  - `def get_current_identity(request: Request) -> Identity` — FastAPI dependency that returns `request.state.identity`. Raises `AppError(401)` if missing.

**Note on `Identity`:** the existing `shared.auth.dependencies.Identity` uses `int | str` for `user_id`/`tenant_id` and `int | None` for `role_id`, and `get_current_identity` there tries `int(value)` first. In this repo every `user_id` is a UUID, so we define a local, UUID-typed `Identity`. We do NOT modify `shared.auth.dependencies` (other services rely on it).

- [ ] **Step 1: Write the failing tests**

Create `services/files-service/tests/test_auth.py`:

```python
"""PublicAuthMiddleware decodes X-User-Id and rejects malformed values."""
import uuid

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import Identity, PublicAuthMiddleware, get_current_identity


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(PublicAuthMiddleware)

    @app.get("/public/ping")
    def ping(identity: Identity = Depends(get_current_identity)):
        return {
            "user_id": str(identity.user_id),
            "tenant_id": str(identity.tenant_id) if identity.tenant_id else None,
            "is_superuser": identity.is_superuser,
        }

    @app.get("/internal/ping")
    def internal_ping():
        return {"ok": True}

    return app


def test_public_path_without_user_id_is_401():
    resp = TestClient(_make_app()).get("/public/ping")
    assert resp.status_code == 401


def test_public_path_with_invalid_uuid_is_401():
    resp = TestClient(_make_app()).get("/public/ping", headers={"X-User-Id": "not-a-uuid"})
    assert resp.status_code == 401


def test_public_path_with_valid_user_id_returns_identity():
    uid = str(uuid.uuid4())
    resp = TestClient(_make_app()).get(
        "/public/ping",
        headers={"X-User-Id": uid, "X-Tenant-Id": uid, "X-Is-Superuser": "false"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == uid
    assert body["tenant_id"] == uid
    assert body["is_superuser"] is False


def test_non_public_path_is_unaffected():
    resp = TestClient(_make_app()).get("/internal/ping")
    assert resp.status_code == 200


def test_is_superuser_true_parses_correctly():
    uid = str(uuid.uuid4())
    resp = TestClient(_make_app()).get(
        "/public/ping",
        headers={"X-User-Id": uid, "X-Is-Superuser": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_superuser"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/files-service && uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'` (file does not exist yet).

- [ ] **Step 3: Create `services/files-service/app/auth.py`**

```python
"""PublicAuthMiddleware: validates X-User-Id on /public/* paths.

Used by the public router in files-service. The api-gateway decodes the user
JWT and injects X-User-Id, X-Tenant-Id, X-Is-Superuser headers before
forwarding. This middleware enforces that those headers exist and are well
formed on any /public/* request, and exposes the resulting Identity via a
FastAPI dependency.

Not used by /internal/* routes (those are protected by ServiceTokenMiddleware
at the app level).
"""
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from shared.utils.exceptions import AppError


PUBLIC_PATH_PREFIX = "/public"


@dataclass(frozen=True)
class Identity:
    user_id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    is_superuser: bool


def _parse_uuid(raw: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise AppError(401, f"invalid {field}")


class PublicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(PUBLIC_PATH_PREFIX):
            return await call_next(request)

        user_id_raw = request.headers.get("X-User-Id")
        if not user_id_raw:
            return JSONResponse({"detail": "missing X-User-Id"}, status_code=401)
        user_id = _parse_uuid(user_id_raw, "X-User-Id")

        tenant_id_raw = request.headers.get("X-Tenant-Id")
        tenant_id = _parse_uuid(tenant_id_raw, "X-Tenant-Id") if tenant_id_raw else None

        is_superuser = request.headers.get("X-Is-Superuser", "").lower() == "true"

        request.state.identity = Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            is_superuser=is_superuser,
        )
        return await call_next(request)


def get_current_identity(request: Request) -> Identity:
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise AppError(401, "identity not resolved")
    return identity


__all__ = ["Identity", "PublicAuthMiddleware", "get_current_identity"]
```

- [ ] **Step 4: Re-run tests to verify they pass**

Run: `cd services/files-service && uv run pytest tests/test_auth.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add services/files-service/app/auth.py services/files-service/tests/test_auth.py
git commit -m "feat(files): PublicAuthMiddleware + Identity for /public/* routes"
```

---

### Task B2: Add `client_public` fixture to `services/files-service/tests/conftest.py`

**Files:**
- Modify: `services/files-service/tests/conftest.py:1-70`

**Interfaces:**
- Consumes: existing `FakeStorage`, `app.main.create_app`, `app.internal_router.get_storage`.
- Produces: new fixture `client_public` that builds an app with the public router mounted, monkey-patches `app.main.get_storage` to `FakeStorage`, sets `app.state.session_factory` and `app.state.settings`, and yields a `TestClient` whose default `X-User-Id` header is a fresh UUID (overridable per-test via `client_public.headers["X-User-Id"] = ...`).

**Why:** The existing `client` fixture (lines 64-70) calls `create_app()` which only mounts the internal router. We need a fixture for the public router. Both fixtures will coexist for a few tasks.

**Important caveat:** the `client` fixture in `tests/conftest.py:64-70` is used by `test_internal_router_avatar.py`, `test_smoke.py`, and `test_bucket_init.py`. We must NOT remove it; we add a new `client_public` fixture in the same file.

- [ ] **Step 1: Write a smoke test for `client_public`**

Append to `services/files-service/tests/conftest.py` is not the right place for a test. Instead, create `services/files-service/tests/test_public_router.py` as an empty file that we will fill in Task B3. For now, write ONE failing test that only depends on `client_public`:

Create `services/files-service/tests/test_client_public_fixture.py`:

```python
"""Smoke test for the client_public fixture."""


def test_client_public_exposes_health(client_public):
    resp = client_public.get("/health")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/files-service && uv run pytest tests/test_client_public_fixture.py -v`
Expected: FAIL with `fixture 'client_public' not found`.

- [ ] **Step 3: Add the fixture to `services/files-service/tests/conftest.py`**

Append to `services/files-service/tests/conftest.py` (after the existing `client` fixture, before any other code):

```python
@pytest.fixture
def client_public(monkeypatch) -> Iterator[TestClient]:
    """TestClient for the public router (no X-Service-Token, X-User-Id injected).

    Mirrors the structure of `client` in this file: monkey-patches
    `app.main.get_storage` to return a `FakeStorage`, sets up an in-memory
    sqlite engine via SQLModel.metadata.create_all, and yields a TestClient
    whose default headers include `X-User-Id` set to a fresh UUID.
    """
    import uuid as _uuid

    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.main import create_app

    fake = FakeStorage()
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()
    uid = str(_uuid.uuid4())
    with TestClient(app, headers={"X-User-Id": uid}) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake
        app.state.settings = type(
            "S",
            (),
            {
                "INTER_SERVICE_SECRET": "test-inter-service-secret",
                "PRESIGN_TTL_SECONDS": 300,
                "AVATAR_MAX_BYTES": 5 * 1024 * 1024,
                "AVATAR_ALLOWED_MIMETYPES": ("image/jpeg", "image/png", "image/webp"),
            },
        )()
        yield c
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd services/files-service && uv run pytest tests/test_client_public_fixture.py -v`
Expected: PASS.

**Note:** This task does NOT yet mount the public router in `app/main.py`. The fixture calls `create_app()` which still only mounts the internal router. The test only checks `/health` (an exempt path), so it passes without the public router being mounted. The next task adds the public router and real public tests.

- [ ] **Step 5: Commit**

```bash
git add services/files-service/tests/conftest.py services/files-service/tests/test_client_public_fixture.py
git commit -m "test(files): client_public fixture for public router tests"
```

---

### Task B3: Implement `app/public_router.py` and mount it in `app/main.py`

**Files:**
- Create: `services/files-service/app/public_router.py`
- Modify: `services/files-service/app/main.py:1-44`
- Create: `services/files-service/tests/test_public_router.py`
- Delete: `services/files-service/tests/test_client_public_fixture.py` (replaced by `test_public_router.py`)

**Interfaces:**
- Consumes: `app.auth.Identity`, `app.auth.get_current_identity`, `app.storage.manager.MediaManager`, `app.models.entities.MediaResources`, `app.models.enums.MediaPurpose`, `app.schemas.internal.MediaRef`, `app.schemas.internal.PresignResponse`.
- Produces:
  - `router: APIRouter` mounted at `/public/files` with 4 endpoints:
    - `POST /users/me/avatar` → `upload_my_avatar(...)` returns `MediaRef` (201)
    - `GET /users/me/avatar` → `get_my_avatar(...)` returns 302 redirect to presigned URL
    - `DELETE /users/me/avatar` → `delete_my_avatar(...)` returns 204
    - `GET /media/{media_id}/presign` → `presign_media(...)` returns 302 (with ownership check) or `PresignResponse` JSON (see implementation detail below)
  - Events: publishes `user.avatar.changed` on successful upload, `user.avatar.removed` on successful delete. Domain is `"onboarding"`.

**Design decision on presign return shape:** the internal router returns `PresignResponse(url=...)` JSON (lines 107-126 of `app/internal_router.py`). The public router's `/users/me/avatar` GET returns 302 with `Location` header (matches spec §3.6). The public router's `/media/{media_id}/presign` endpoint must enforce ownership (`row.user_id == X-User-Id`), and to keep behavior consistent with the spec which calls for 302 redirects for downloads, we return **302 with Location header** (not JSON). This deviates from the internal router's JSON response — but the public endpoint is consumed by browsers/CLIs that follow redirects naturally, while the internal one is consumed by `auth-service`'s code that wants the URL string. Both endpoints are valid; the difference is the consumer.

- [ ] **Step 1: Write the failing tests**

Create `services/files-service/tests/test_public_router.py`:

```python
"""Public router: avatar upload/get/delete + presign with ownership."""
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.main import create_app
from app.storage import get_storage
from tests.conftest import FakeStorage


SVC_SECRET = "test-inter-service-secret"


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


@pytest.fixture
def public_client(monkeypatch) -> TestClient:
    fake = FakeStorage()
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()
    uid = str(uuid.uuid4())
    with TestClient(app, headers={"X-User-Id": uid}) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake
        app.state.settings = type(
            "S",
            (),
            {
                "INTER_SERVICE_SECRET": SVC_SECRET,
                "PRESIGN_TTL_SECONDS": 300,
                "AVATAR_MAX_BYTES": 5 * 1024 * 1024,
                "AVATAR_ALLOWED_MIMETYPES": ("image/jpeg", "image/png", "image/webp"),
            },
        )()
        yield c


def test_upload_returns_201_and_creates_row(public_client):
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["bucket"] == "avatars"
    assert body["size_bytes"] > 0
    assert body["mimetype"] == "image/png"
    assert body["purpose"] == "profile_photo"


def test_upload_replaces_existing(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    first = public_client.post("/public/files/users/me/avatar", files=files).json()
    files2 = {"file": ("b.png", io.BytesIO(_png_bytes()), "image/png")}
    second = public_client.post("/public/files/users/me/avatar", files=files2).json()
    assert first["media_id"] != second["media_id"]
    listing = public_client.get("/public/files/users/me/avatar")
    assert listing.status_code == 302
    assert first["media_id"] not in listing.headers["location"]


def test_upload_rejects_oversize(public_client):
    big = b"x" * (5 * 1024 * 1024 + 1)
    files = {"file": ("a.png", io.BytesIO(big), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 413


def test_upload_rejects_bad_mime(public_client):
    files = {"file": ("a.gif", io.BytesIO(_png_bytes()), "image/gif")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 400


def test_upload_rejects_empty(public_client):
    files = {"file": ("a.png", io.BytesIO(b""), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 400


def test_upload_without_identity_is_401():
    from fastapi.testclient import TestClient as _TC

    from app.main import create_app

    app = create_app()
    with _TC(app) as c:
        files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
        resp = c.post("/public/files/users/me/avatar", files=files)
        assert resp.status_code == 401


def test_get_avatar_returns_302_with_presigned_url(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    public_client.post("/public/files/users/me/avatar", files=files)
    resp = public_client.get("/public/files/users/me/avatar")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://test/")
    assert "?exp=300" in resp.headers["location"]


def test_get_avatar_returns_404_when_missing(public_client):
    resp = public_client.get("/public/files/users/me/avatar")
    assert resp.status_code == 404


def test_delete_avatar_returns_204(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    public_client.post("/public/files/users/me/avatar", files=files)
    resp = public_client.delete("/public/files/users/me/avatar")
    assert resp.status_code == 204
    assert public_client.get("/public/files/users/me/avatar").status_code == 404


def test_delete_avatar_returns_404_when_missing(public_client):
    resp = public_client.delete("/public/files/users/me/avatar")
    assert resp.status_code == 404


def test_presign_endpoint_enforces_ownership(public_client):
    """User A uploads; user B cannot presign A's media."""
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    up = public_client.post("/public/files/users/me/avatar", files=files)
    media_id = up.json()["media_id"]

    # Switch to user B
    other = str(uuid.uuid4())
    public_client.headers["X-User-Id"] = other
    resp = public_client.get(f"/public/files/media/{media_id}/presign")
    assert resp.status_code == 403


def test_presign_endpoint_happy_path(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    up = public_client.post("/public/files/users/me/avatar", files=files)
    media_id = up.json()["media_id"]
    resp = public_client.get(
        f"/public/files/media/{media_id}/presign",
        params={"ttl": 60},
    )
    assert resp.status_code == 302
    assert "?exp=60" in resp.headers["location"]


def test_presign_endpoint_404_for_unknown_media(public_client):
    resp = public_client.get(f"/public/files/media/{uuid.uuid4()}/presign")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd services/files-service && uv run pytest tests/test_public_router.py -v`
Expected: FAIL — most tests will return 404 (public router not mounted yet), some will get 401 or hang on import.

- [ ] **Step 3: Create `services/files-service/app/public_router.py`**

```python
"""Public router for files-service.

Mounted at /public/files/*. Protected by PublicAuthMiddleware (validates
X-User-Id). The api-gateway decodes the user JWT and forwards with
X-User-Id / X-Tenant-Id / X-Is-Superuser headers; we resolve `me` from
X-User-Id server-side and enforce ownership.

Endpoints:
- POST   /users/me/avatar          upload (replace), 201 + MediaRef
- GET    /users/me/avatar          302 -> presigned URL
- DELETE /users/me/avatar          204
- GET    /media/{media_id}/presign 302 -> presigned URL (ownership enforced)
"""
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.auth import Identity, get_current_identity
from app.config import Settings
from app.models.entities import MediaResources
from app.schemas.internal import MediaRef
from app.storage import get_storage
from app.storage.manager import MediaManager
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope


_log = logging.getLogger(__name__)

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session(request: Request) -> Session:
    return request.app.state.session_factory()


def _manager(request: Request, settings: Settings = Depends(_settings)) -> MediaManager:
    return MediaManager(db=_session(request), backend=get_storage(settings))


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _publish_event(envelope: EventEnvelope) -> None:
    """Publish an event, swallowing infrastructure errors per spec §7.4."""
    try:
        EventBus(_redis_url()).publish("onboarding", envelope)
    except Exception:  # pragma: no cover — defensive
        _log.warning("failed to publish event %s", envelope.type, exc_info=True)


def _validate_upload(*, content: bytes, content_type: str, settings: Settings) -> None:
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > settings.AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds maximum {settings.AVATAR_MAX_BYTES} bytes",
        )
    if content_type not in settings.AVATAR_ALLOWED_MIMETYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported content type; allowed: {list(settings.AVATAR_ALLOWED_MIMETYPES)}",
        )


def _to_media_ref(media: MediaResources) -> MediaRef:
    return MediaRef(
        media_id=media.id,
        bucket=media.bucket,
        key=media.path,
        size_bytes=media.size_bytes,
        mimetype=media.mimetype,
        purpose=media.purpose,
    )


@router.post(
    "/users/me/avatar",
    response_model=MediaRef,
    status_code=201,
)
def upload_my_avatar(
    file: UploadFile = File(...),
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
    settings: Settings = Depends(_settings),
):
    content = file.file.read()
    content_type = file.content_type or "application/octet-stream"
    _validate_upload(content=content, content_type=content_type, settings=settings)
    media = manager.upload_avatar(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        content=content,
        filename=file.filename or "avatar.bin",
        content_type=content_type,
        size_bytes=len(content),
    )
    _publish_event(
        EventEnvelope(
            type="user.avatar.changed",
            aggregate_id=str(identity.user_id),
            tenant_id=str(identity.tenant_id) if identity.tenant_id else None,
            payload={
                "user_id": str(identity.user_id),
                "media_id": str(media.id),
                "mimetype": media.mimetype,
                "size_bytes": media.size_bytes,
            },
        )
    )
    return _to_media_ref(media)


@router.get("/users/me/avatar")
def get_my_avatar(
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
    settings: Settings = Depends(_settings),
):
    media = manager.get_avatar(user_id=identity.user_id)
    if media is None:
        raise HTTPException(status_code=404, detail="no avatar")
    url = manager.presigned_url_for(media=media, ttl_seconds=settings.PRESIGN_TTL_SECONDS)
    return RedirectResponse(url=url, status_code=302)


@router.delete("/users/me/avatar", status_code=204)
def delete_my_avatar(
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
):
    if not manager.delete_avatar(user_id=identity.user_id):
        raise HTTPException(status_code=404, detail="no avatar")
    _publish_event(
        EventEnvelope(
            type="user.avatar.removed",
            aggregate_id=str(identity.user_id),
            tenant_id=str(identity.tenant_id) if identity.tenant_id else None,
            payload={"user_id": str(identity.user_id)},
        )
    )
    return None


@router.get("/media/{media_id}/presign")
def presign_media_public(
    media_id: uuid.UUID,
    ttl: int = 300,
    identity: Identity = Depends(get_current_identity),
    session: Session = Depends(_session),
    settings: Settings = Depends(_settings),
    manager: MediaManager = Depends(_manager),
):
    media: Optional[MediaResources] = session.get(MediaResources, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="media not found")
    if media.user_id != identity.user_id:
        raise HTTPException(status_code=403, detail="not the owner")
    effective_ttl = max(1, min(ttl, settings.PRESIGN_TTL_SECONDS))
    url = manager.presigned_url_for(media=media, ttl_seconds=effective_ttl)
    return RedirectResponse(url=url, status_code=302)


__all__ = ["router"]
```

- [ ] **Step 4: Mount the public router in `services/files-service/app/main.py`**

Replace `services/files-service/app/main.py` contents with:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth import PublicAuthMiddleware
from app.config import Settings
from app.internal_router import router as internal_router
from app.public_router import router as public_router
from app.storage import get_storage
from shared.auth.middleware import ServiceTokenMiddleware
from shared.db.engine import create_service_engine, get_session_factory
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        storage = get_storage(settings)
        for bucket, is_public in settings.INIT_BUCKETS:
            storage.ensure_bucket(bucket=bucket)
            storage.set_bucket_public(bucket=bucket, public=is_public)
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        app.state.session_factory = get_session_factory(engine)
        app.state.storage = storage
        app.state.settings = settings
        yield
        engine.dispose()

    app = FastAPI(title="files-service", lifespan=lifespan)
    register_exception_handlers(app)
    # Middleware order matters: ServiceTokenMiddleware is added LAST so it
    # runs FIRST on incoming requests (Starlette applies middleware in
    # reverse-add order). It exempts /health and /public/* paths.
    app.add_middleware(PublicAuthMiddleware)
    app.add_middleware(
        ServiceTokenMiddleware,
        secret=settings.INTER_SERVICE_SECRET,
        exempt_prefixes=frozenset({"/public"}),
    )
    app.include_router(internal_router, prefix="/internal/files")
    app.include_router(public_router, prefix="/public/files")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
```

> **Middleware ordering note:** Starlette runs middleware in **reverse** order of `add_middleware` (last added = outermost). We want `ServiceTokenMiddleware` to check first (skip `/public/*`) and then `PublicAuthMiddleware` to validate `X-User-Id` only on `/public/*` paths. Therefore we add `PublicAuthMiddleware` first (innermost) and `ServiceTokenMiddleware` last (outermost).

- [ ] **Step 5: Re-run public router tests to verify they pass**

Run: `cd services/files-service && uv run pytest tests/test_public_router.py -v`
Expected: PASS (13 tests).

- [ ] **Step 6: Run the full files-service test suite**

Run: `cd services/files-service && uv run pytest -q`
Expected: PASS (existing tests for `MediaManager`, internal router, smoke, storage, bucket init, auth middleware, public auth, public router — all green).

- [ ] **Step 7: Delete the temporary fixture smoke test**

```bash
rm services/files-service/tests/test_client_public_fixture.py
```

- [ ] **Step 8: Commit**

```bash
git add services/files-service/app/public_router.py \
        services/files-service/app/main.py \
        services/files-service/tests/test_public_router.py
git commit -m "feat(files): public router for avatar lifecycle with ownership checks"
```

---

## Phase C — files-service: reduce internal router

### Task C1: Remove `POST` and `DELETE` avatar endpoints from internal router

**Files:**
- Modify: `services/files-service/app/internal_router.py:1-126`
- Modify: `services/files-service/tests/test_internal_router_avatar.py:1-124`

**Interfaces:**
- Consumes: (unchanged internal router handlers for `GET /users/{user_id}/avatar` and `GET /media/{media_id}/presign`).
- Produces: same router but with two handlers removed (`upload_avatar`, `delete_avatar`). The remaining handlers still authenticate via `X-Service-Token`.

**Why:** After this plan, no service talks to files-service via the internal `POST/DELETE /users/{user_id}/avatar` endpoints. The frontend talks to the public router; `auth-service` only needs the read endpoints to enrich `/me`.

- [ ] **Step 1: Remove tests for the deleted endpoints**

In `services/files-service/tests/test_internal_router_avatar.py`, delete these two tests entirely:
- `test_upload_avatar_returns_201_and_creates_row` (lines 57-69)
- `test_delete_avatar_returns_204` (lines 93-103)

- [ ] **Step 2: Run the test file to verify it still passes (minus the removed tests)**

Run: `cd services/files-service && uv run pytest tests/test_internal_router_avatar.py -v`
Expected: PASS (3 remaining tests: `test_get_avatar_returns_404_when_missing`, `test_get_avatar_returns_metadata`, `test_presign_endpoint_returns_url`, `test_presign_returns_404_for_unknown_media`).

- [ ] **Step 3: Remove the two handlers from `app/internal_router.py`**

In `services/files-service/app/internal_router.py`, delete:
- The `upload_avatar` handler (lines 44-73), including its `@router.post(...)` decorator.
- The `delete_avatar` handler (lines 97-104), including its `@router.delete(...)` decorator.

The remaining imports (`File`, `UploadFile`) are now unused; remove them from the `from fastapi import (...)` block at lines 10-17. Keep `MediaRef`, `PresignResponse`, `MediaResources`, `get_storage`, `MediaManager` — still in use.

- [ ] **Step 4: Run the full files-service test suite**

Run: `cd services/files-service && uv run pytest -q`
Expected: PASS (all green; no regression).

- [ ] **Step 5: Commit**

```bash
git add services/files-service/app/internal_router.py services/files-service/tests/test_internal_router_avatar.py
git commit -m "refactor(files): drop internal POST/DELETE avatar handlers"
```

---

## Phase D — auth-service: introduce the read helper that backs `/me`

### Task D1: Create `app/services/avatars_read.py` with `AvatarSummary` and `get_avatar_summary`

**Files:**
- Create: `services/auth-service/app/services/avatars_read.py`
- Create: `services/auth-service/tests/test_avatars_read.py`

**Interfaces:**
- Consumes: existing `shared.auth.client.ServiceHttpClient`.
- Produces:
  - `@dataclass(frozen=True) class AvatarSummary` with fields `has_avatar: bool`, `avatar_url: Optional[str]`.
  - `class FilesReadClient(ServiceHttpClient)` with two methods:
    - `get_avatar(*, user_id: uuid.UUID) -> MediaRef` — raises `NotFoundError` on 404.
    - `presign(*, media_id: uuid.UUID, ttl_seconds: int) -> str` — raises `NotFoundError` on 404.
  - `_FILES_READ_CLIENT_OVERRIDE: Optional[FilesReadClient]` — module global test seam.
  - `_set_files_read_client_for_tests(client: Optional[FilesReadClient]) -> None` and `_reset_files_read_client_for_tests() -> None` — test seam mutators.
  - `def get_avatar_summary(*, settings: Settings, user_id: uuid.UUID, files_client: Optional[FilesReadClient] = None) -> AvatarSummary` — calls `files_client.get_avatar` and `files_client.presign`. If `get_avatar` raises `NotFoundError` OR any exception (5xx, timeout), returns `AvatarSummary(has_avatar=False, avatar_url=None)`. **No side effects on the user record** (the FK is gone; nothing to clear).

- [ ] **Step 1: Write the failing tests**

Create `services/auth-service/tests/test_avatars_read.py`:

```python
"""Tests for the read-only avatars helper used by /me."""
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest

from app.config import Settings
from app.services.avatars_read import (
    AvatarSummary,
    FilesReadClient,
    _reset_files_read_client_for_tests,
    _set_files_read_client_for_tests,
    get_avatar_summary,
)
from shared.utils.exceptions import NotFoundError


def _settings(**over) -> Settings:
    base = dict(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 32,
        REDIS_URL="redis://x",
        FILES_SERVICE_URL="http://files:8004",
        PRESIGN_TTL_SECONDS=300,
    )
    base.update(over)
    return Settings(**base)


def _files_client(handler) -> FilesReadClient:
    return FilesReadClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )


def test_get_avatar_summary_returns_url_when_remote_has_avatar():
    user_id = uuid.uuid4()
    media_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/presign" in request.url.path:
            return httpx.Response(200, json={"url": "https://example/avatar?sig=1"})
        return httpx.Response(200, json={
            "media_id": str(media_id),
            "bucket": "avatars", "key": f"users/{user_id}/x.png",
            "size_bytes": 100, "mimetype": "image/png", "purpose": "profile_photo",
        })

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is True
    assert summary.avatar_url == "https://example/avatar?sig=1"


def test_get_avatar_summary_returns_false_on_404():
    user_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is False
    assert summary.avatar_url is None


def test_get_avatar_summary_returns_false_on_5xx_graceful():
    user_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is False
    assert summary.avatar_url is None


def test_get_avatar_summary_uses_test_override_seam():
    user_id = uuid.uuid4()
    media_id = uuid.uuid4()

    class FakeReadClient:
        def get_avatar(self, *, user_id):
            return _RefStub(media_id=media_id, user_id=user_id)

        def presign(self, *, media_id, ttl_seconds):
            return f"https://fake/{media_id}?ttl={ttl_seconds}"

    _set_files_read_client_for_tests(FakeReadClient())  # type: ignore[arg-type]
    try:
        summary = get_avatar_summary(settings=_settings(), user_id=user_id)
        assert summary.has_avatar is True
        assert summary.avatar_url == f"https://fake/{media_id}?ttl=300"
    finally:
        _reset_files_read_client_for_tests()


@dataclass
class _RefStub:
    media_id: uuid.UUID
    user_id: uuid.UUID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/auth-service && uv run pytest tests/test_avatars_read.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.avatars_read'`.

- [ ] **Step 3: Create `services/auth-service/app/services/avatars_read.py`**

```python
"""Read-only avatar helper for /me, /login, /refresh, PATCH /me enrichment.

Calls files-service /internal/files/users/{id}/avatar + /media/{id}/presign
and returns a tiny AvatarSummary. No side effects: avatar ownership lives
in files-service now (media_resources.user_id), so there is no FK in auth_db
to clean up.

The HTTP client shape mirrors FilesClient from the deleted
app.services.files_client, but reduced to the two read methods we need.
"""
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings
from shared.auth.client import ServiceHttpClient
from shared.utils.exceptions import NotFoundError


@dataclass(frozen=True)
class AvatarSummary:
    has_avatar: bool
    avatar_url: Optional[str]


@dataclass(frozen=True)
class MediaRef:
    media_id: uuid.UUID
    bucket: str
    key: str
    size_bytes: int
    mimetype: str
    purpose: str


class FilesReadClient(ServiceHttpClient):
    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        issuer: str,
        timeout: float = 10.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        kwargs = {"timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        super().__init__(secret=secret, issuer=issuer, base_url=base_url, **kwargs)

    def get_avatar(self, *, user_id: uuid.UUID) -> MediaRef:
        resp = self.get(f"/internal/files/users/{user_id}/avatar")
        if resp.status_code == 404:
            raise NotFoundError("no avatar")
        resp.raise_for_status()
        body = resp.json()
        return MediaRef(
            media_id=uuid.UUID(body["media_id"]),
            bucket=body["bucket"],
            key=body["key"],
            size_bytes=body["size_bytes"],
            mimetype=body["mimetype"],
            purpose=body["purpose"],
        )

    def presign(self, *, media_id: uuid.UUID, ttl_seconds: int) -> str:
        resp = self.get(
            f"/internal/files/media/{media_id}/presign",
            params={"ttl": ttl_seconds},
        )
        if resp.status_code == 404:
            raise NotFoundError("media not found")
        resp.raise_for_status()
        return resp.json()["url"]


_FILES_READ_CLIENT_OVERRIDE: Optional[FilesReadClient] = None


def _set_files_read_client_for_tests(client: Optional[FilesReadClient]) -> None:
    global _FILES_READ_CLIENT_OVERRIDE
    _FILES_READ_CLIENT_OVERRIDE = client


def _reset_files_read_client_for_tests() -> None:
    global _FILES_READ_CLIENT_OVERRIDE
    _FILES_READ_CLIENT_OVERRIDE = None


def _resolve_read_client(
    settings: Settings,
    files_client: Optional[FilesReadClient],
) -> FilesReadClient:
    if files_client is not None:
        return files_client
    if _FILES_READ_CLIENT_OVERRIDE is not None:
        return _FILES_READ_CLIENT_OVERRIDE
    return FilesReadClient(
        base_url=settings.FILES_SERVICE_URL,
        secret=settings.INTER_SERVICE_SECRET,
        issuer=settings.SERVICE_NAME,
    )


def get_avatar_summary(
    *,
    settings: Settings,
    user_id: uuid.UUID,
    files_client: Optional[FilesReadClient] = None,
) -> AvatarSummary:
    client = _resolve_read_client(settings, files_client)
    try:
        media = client.get_avatar(user_id=user_id)
    except NotFoundError:
        return AvatarSummary(has_avatar=False, avatar_url=None)
    except Exception:
        # 5xx, timeout, or anything else: graceful degradation per spec §7.3.
        return AvatarSummary(has_avatar=False, avatar_url=None)
    try:
        url = client.presign(media_id=media.media_id, ttl_seconds=settings.PRESIGN_TTL_SECONDS)
    except Exception:
        return AvatarSummary(has_avatar=False, avatar_url=None)
    return AvatarSummary(has_avatar=True, avatar_url=url)


__all__ = [
    "AvatarSummary",
    "FilesReadClient",
    "MediaRef",
    "_reset_files_read_client_for_tests",
    "_set_files_read_client_for_tests",
    "get_avatar_summary",
]
```

- [ ] **Step 4: Re-run tests to verify they pass**

Run: `cd services/auth-service && uv run pytest tests/test_avatars_read.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add services/auth-service/app/services/avatars_read.py services/auth-service/tests/test_avatars_read.py
git commit -m "feat(auth): avatars_read helper for /me enrichment"
```

---

### Task D2: Wire `_build_user_response` to `get_avatar_summary`

**Files:**
- Modify: `services/auth-service/app/controller.py:53-80` (the `_build_user_response` function only)
- Modify: `services/auth-service/tests/conftest.py:1-164` (drop `FakeFilesClient`, drop `fake_files_client`, drop `AVATAR_*`/`PRESIGN_*` settings; add `fake_files_read_client` and patch `_FILES_READ_CLIENT_OVERRIDE` in the `client` fixture)
- Modify: `services/auth-service/tests/test_me_endpoint.py:1-57` (no functional change; ensure `has_avatar=False` default test still passes)

**Interfaces:**
- Consumes: `app.services.avatars_read.get_avatar_summary`, `app.services.avatars_read._set_files_read_client_for_tests`.
- Produces: `_build_user_response(*, user, db, settings)` calls `get_avatar_summary(settings=settings, user_id=user.id)` and uses the returned `AvatarSummary` to populate `UserResponse`. The function no longer touches `user.avatar_media_id` (the field is gone in Task E4, but we keep the function compatible until then by NOT referencing the field — see Step 1 below).

**Important:** at this task we **only** change `_build_user_response`. The three handler functions `get_my_avatar_response`, `post_my_avatar`, `delete_my_avatar` are still in the file; we delete them in Phase E. The migration dropping `avatar_media_id` happens in E4. To keep the build green between D2 and E4, `_build_user_response` must NOT reference `user.avatar_media_id`. Use `user.id` only.

- [ ] **Step 1: Write a failing test in `test_me_endpoint.py` that checks avatar fields are still populated when remote has an avatar**

Append to `services/auth-service/tests/test_me_endpoint.py`:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd services/auth-service && uv run pytest tests/test_me_endpoint.py -v`
Expected: FAIL — `fixture 'fake_files_read_client' not found`.

- [ ] **Step 3: Replace `tests/conftest.py` with the new version**

This is a big step because the conftest currently hosts `FakeFilesClient` (deleted in E2) and the `_FILES_CLIENT_OVERRIDE` seam. We replace the file now so that D2's tests work; the `FakeFilesClient` class and the `fake_files_client` fixture are dropped here, ahead of E2's file deletion.

Replace `services/auth-service/tests/conftest.py` with:

```python
import os

os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import uuid as _uuid
from typing import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models.entities import User
from app.models.enums import UserStatus
from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.db.engine import get_db

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET=INTER_SERVICE_SECRET,
        SECRET_KEY="test-secret-key-0123456789abcdef",
        REDIS_URL="redis://localhost:6379/15",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_MINUTES=60,
        FILES_SERVICE_URL="http://files-service:8004",
        PRESIGN_TTL_SECONDS=300,
        COOKIE_SECURE=False,
        COOKIE_SAMESITE="lax",
        COOKIE_PATH="/api/auth",
        COOKIE_DOMAIN="",
    )


@pytest.fixture
def identity() -> Identity:
    return Identity(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        role_id=1,
        is_superuser=True,
    )


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_event_bus(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    from shared.events.bus import EventBus

    return EventBus("redis://localhost:6379/15")


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


class FakeFilesReadClient:
    """In-process stand-in for FilesReadClient used by avatars_read."""

    def __init__(self) -> None:
        self.has_avatar = False
        self.url = None
        self.calls = {"get_avatar": 0, "presign": 0}

    def set_has_avatar(self, has_avatar: bool, *, url: str | None = None) -> None:
        self.has_avatar = has_avatar
        self.url = url

    def get_avatar(self, *, user_id):
        from shared.utils.exceptions import NotFoundError

        self.calls["get_avatar"] += 1
        if not self.has_avatar:
            raise NotFoundError("no avatar")
        return _FakeRef(media_id=_uuid.uuid4(), user_id=user_id)

    def presign(self, *, media_id, ttl_seconds):
        self.calls["presign"] += 1
        return self.url or f"https://test/{media_id}.png?ttl={ttl_seconds}"


class _FakeRef:
    def __init__(self, *, media_id, user_id):
        self.media_id = media_id
        self.user_id = user_id
        self.bucket = "avatars"
        self.key = f"users/{user_id}/x.png"
        self.size_bytes = 42
        self.mimetype = "image/png"
        self.purpose = "profile_photo"


@pytest.fixture
def fake_files_read_client() -> FakeFilesReadClient:
    return FakeFilesReadClient()


@pytest.fixture
def client(
    settings,
    db_session,
    fake_event_bus,
    svc_headers,
    fake_files_read_client,
    monkeypatch,
):
    from app.services import avatars_read as avatars_read_module

    monkeypatch.setattr(
        avatars_read_module, "_FILES_READ_CLIENT_OVERRIDE", fake_files_read_client,
    )

    from app.main import create_app

    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="x", tenant_id="x", role_id=None, is_superuser=False,
    )
    with TestClient(app) as c:
        c.headers.update(svc_headers)
        yield c
```

- [ ] **Step 4: Update `_build_user_response` in `app/controller.py`**

Replace `services/auth-service/app/controller.py` lines 53-80 (the entire `_build_user_response` function) with:

```python
def _build_user_response(
    *, user: User, db, settings: Settings
) -> dict:
    from app.services.avatars_read import get_avatar_summary

    summary = get_avatar_summary(settings=settings, user_id=user.id)
    return UserResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        status=user.status,
        has_avatar=summary.has_avatar,
        avatar_url=summary.avatar_url,
        created_at=user.created_at.isoformat(),
        modified_at=user.modified_at.isoformat(),
    ).model_dump()
```

> **Note:** the function still takes `db` (unused now) to keep the existing call sites in `login`, `refresh`, `get_me`, `patch_me` working without changes. We leave `db` in the signature; callers don't change.

- [ ] **Step 5: Run `test_me_endpoint.py` to verify the new tests pass**

Run: `cd services/auth-service && uv run pytest tests/test_me_endpoint.py -v`
Expected: PASS (5 tests: 3 existing + 2 new).

- [ ] **Step 6: Run the full auth-service test suite**

Run: `cd services/auth-service && uv run pytest -q`
Expected: PASS for everything except the tests that import the soon-to-be-deleted `app.services.avatars` (test_avatar_endpoint, test_avatars_service, test_files_client). These are expected to fail at this stage; we delete them in Phase E.

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/app/controller.py \
        services/auth-service/tests/conftest.py \
        services/auth-service/tests/test_me_endpoint.py
git commit -m "refactor(auth): _build_user_response uses avatars_read"
```

---

## Phase E — auth-service: delete endpoints, modules, and column

### Task E1: Remove `GET/POST/DELETE /me/avatar` routes from `router.py`

**Files:**
- Modify: `services/auth-service/app/router.py:1-170`

**Interfaces:**
- Consumes: (existing imports; we drop `Response`, `UploadFile`, `JSONResponse` if they become unused).
- Produces: a router with 7 endpoints: `POST /onboarding`, `POST /login`, `POST /logout`, `POST /refresh`, `GET /validate`, `GET /me`, `PATCH /me`. The three `/me/avatar` routes are gone.

**Important:** this task removes the routes only. The controller functions `get_my_avatar_response`, `post_my_avatar`, `delete_my_avatar` remain in `controller.py` for now (deleted in E2). This means the controller code is "dead" between E1 and E2 — that's acceptable because nothing references it.

- [ ] **Step 1: Delete tests that hit `/me/avatar`**

Delete these files entirely (they will be re-created or absorbed in later tasks; for now, just remove):
- `services/auth-service/tests/test_avatar_endpoint.py` (the entire file)

```bash
rm services/auth-service/tests/test_avatar_endpoint.py
```

- [ ] **Step 2: Run the auth-service test suite to confirm only the removed tests are gone**

Run: `cd services/auth-service && uv run pytest -q`
Expected: FAIL only for `test_avatar_endpoint.py` (deleted), `test_avatars_service.py` and `test_files_client.py` (deleted in E2). Other tests still PASS.

- [ ] **Step 3: Edit `services/auth-service/app/router.py`**

Remove these blocks from `services/auth-service/app/router.py`:
- Lines 133-142 (the `GET /me/avatar` route)
- Lines 144-157 (the `POST /me/avatar` route)
- Lines 160-169 (the `DELETE /me/avatar` route)

Also, the `from fastapi import ...` line at line 4 currently imports `Response, UploadFile`. After removal, `UploadFile` is unused; remove it from the import. `Response` is still used by `_with_set_cookie`, so keep it.

The `JSONResponse` import at line 5 is still used. Keep it.

- [ ] **Step 4: Run the test suite**

Run: `cd services/auth-service && uv run pytest -q`
Expected: same as Step 2 (only the files deleted in E1 and E2 fail).

- [ ] **Step 5: Commit**

```bash
git add services/auth-service/app/router.py
git commit -m "refactor(auth): drop /me/avatar routes"
```

---

### Task E2: Delete the avatar controller functions, the modules, the schema

**Files:**
- Modify: `services/auth-service/app/controller.py` (remove `get_my_avatar_response`, `post_my_avatar`, `delete_my_avatar` from lines 207-303; remove the now-unused `UploadFile` import at line 3)
- Modify: `services/auth-service/app/services/__init__.py:7-12` and `__all__` entries (lines 25, 27, 32-34, 44)
- Delete: `services/auth-service/app/services/avatars.py`
- Delete: `services/auth-service/app/services/files_client.py`
- Delete: `services/auth-service/app/schemas/avatar.py`
- Delete: `services/auth-service/tests/test_files_client.py`
- Delete: `services/auth-service/tests/test_avatars_service.py`

- [ ] **Step 1: Delete the four test/source files**

```bash
rm services/auth-service/app/services/avatars.py \
   services/auth-service/app/services/files_client.py \
   services/auth-service/app/schemas/avatar.py \
   services/auth-service/tests/test_files_client.py \
   services/auth-service/tests/test_avatars_service.py
```

- [ ] **Step 2: Run the test suite to verify what's left failing**

Run: `cd services/auth-service && uv run pytest -q`
Expected: import errors / collection errors in `app/services/__init__.py` and `app/controller.py` because they still reference deleted modules. Some tests will fail at import time.

- [ ] **Step 3: Fix `app/services/__init__.py`**

Replace `services/auth-service/app/services/__init__.py` contents with:

```python
from app.services.auth_tokens import (
    decode_access_token,
    hash_refresh,
    mint_access_token,
    mint_refresh_token,
)
from app.services.avatars_read import (
    AvatarSummary,
    FilesReadClient,
    MediaRef,
    get_avatar_summary,
)
from app.services.login import LoginOutcome, authenticate_and_open_session
from app.services.logout import revoke_session_for_token
from app.services.onboarding import (
    handle_tenant_created,
    publish_pending,
    start_onboarding,
)
from app.services.refresh import RefreshOutcome, rotate_refresh
from app.services.users import get_user_by_id, update_user
from app.services.validate import ValidateResult, validate_access_token

__all__ = [
    "AvatarSummary",
    "FilesReadClient",
    "LoginOutcome",
    "MediaRef",
    "RefreshOutcome",
    "ValidateResult",
    "authenticate_and_open_session",
    "decode_access_token",
    "get_avatar_summary",
    "get_user_by_id",
    "handle_tenant_created",
    "hash_refresh",
    "mint_access_token",
    "mint_refresh_token",
    "publish_pending",
    "revoke_session_for_token",
    "rotate_refresh",
    "start_onboarding",
    "update_user",
    "validate_access_token",
]
```

- [ ] **Step 4: Fix `app/controller.py`**

In `services/auth-service/app/controller.py`:
- Remove the `UploadFile` import at line 3: change `from fastapi import Response, UploadFile` to `from fastapi import Response`.
- Delete the three controller functions `get_my_avatar_response` (lines 207-228), `post_my_avatar` (lines 231-275), `delete_my_avatar` (lines 278-303).
- Verify that no other code in the file references `UploadFile`, `AvatarResponse`, `upload_avatar_for_user`, `delete_avatar_for_user`, `get_avatar_for_user` from the deleted modules.

- [ ] **Step 5: Run the test suite**

Run: `cd services/auth-service && uv run pytest -q`
Expected: PASS for all remaining tests (those not deleted in E1/E2). If any test still imports a deleted symbol, fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add services/auth-service/app/controller.py \
        services/auth-service/app/services/__init__.py \
        services/auth-service/app/services/avatars.py \
        services/auth-service/app/services/files_client.py \
        services/auth-service/app/schemas/avatar.py \
        services/auth-service/tests/test_files_client.py \
        services/auth-service/tests/test_avatars_service.py
git commit -m "refactor(auth): delete avatar orchestration modules and controller fns"
```

---

### Task E3: Drop `AVATAR_*` and `PRESIGN_*` settings from `app/config.py`

**Files:**
- Modify: `services/auth-service/app/config.py:46-48, 71-76`

**Interfaces:**
- Consumes: (existing config).
- Produces: `Settings` without `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS`. The `_split_avatar_mimetypes` validator is also removed. `PRESIGN_TTL_SECONDS` is **kept** because `avatars_read.py:get_avatar_summary` reads it from settings — see Step 3.

Wait: re-reading D1's `get_avatar_summary`, it does `client.presign(media_id=..., ttl_seconds=settings.PRESIGN_TTL_SECONDS)`. So we must **keep `PRESIGN_TTL_SECONDS`**. We only drop `AVATAR_*` (the validation settings now live in `files-service`).

- [ ] **Step 1: Edit `services/auth-service/app/config.py`**

- Delete the `# Avatar configuration` block at lines 45-48 (the comment and the `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES` fields). Keep `PRESIGN_TTL_SECONDS`.
- Delete the `_split_avatar_mimetypes` validator at lines 71-76.
- Update the `Settings` docstring if needed (no docstring change required).

The result should have `PRESIGN_TTL_SECONDS` still present (lines 47 becomes line 44 or similar after deletions) and no `AVATAR_*` fields.

- [ ] **Step 2: Verify the test suite still passes**

Run: `cd services/auth-service && uv run pytest -q`
Expected: PASS. (The conftest in D2 no longer references `AVATAR_*`.)

- [ ] **Step 3: Commit**

```bash
git add services/auth-service/app/config.py
git commit -m "refactor(auth): drop AVATAR_* settings (kept PRESIGN_TTL_SECONDS for /me)"
```

---

### Task E4: Drop `User.avatar_media_id` column via migration

**Files:**
- Modify: `services/auth-service/app/models/entities.py:37` (remove the field)
- Create: `services/auth-service/migrations/versions/0003_drop_avatar_media_id.py`
- Modify: `services/auth-service/tests/test_refresh_token_model.py:1-55` (remove `test_user_has_avatar_media_id_column` at lines 47-55)

- [ ] **Step 1: Remove the `test_user_has_avatar_media_id_column` test**

In `services/auth-service/tests/test_refresh_token_model.py`:
- Delete lines 47-55 (the `test_user_has_avatar_media_id_column` function).
- Update the file's docstring (line 1) from `"Schema-level tests for the new RefreshToken model and User.avatar_media_id."` to `"Schema-level tests for the RefreshToken model."`.

- [ ] **Step 2: Run the tests to confirm only the deleted one is gone**

Run: `cd services/auth-service && uv run pytest tests/test_refresh_token_model.py -v`
Expected: PASS (1 remaining test).

- [ ] **Step 3: Remove the `avatar_media_id` field from `User`**

In `services/auth-service/app/models/entities.py`, delete line 37:
```python
    avatar_media_id: Optional[uuid.UUID] = Field(default=None, nullable=True)
```

Also remove the now-unused `Optional` import from `typing` if it is no longer referenced (line 3). Verify by grepping the file: `grep -n Optional app/models/entities.py`. If only line 3 remains, remove the line; otherwise leave it.

- [ ] **Step 4: Create the Alembic migration**

Create `services/auth-service/migrations/versions/0003_drop_avatar_media_id.py`:

```python
"""drop users.avatar_media_id

The avatar FK lived in auth_db only as a convenience pointer; ownership now
lives in files_db.media_resources.user_id. Removing this column completes
the decoupling of auth-service from files-service (no cross-DB FK).
Revision ID: 0003_drop_avatar_media_id
Revises: 0002_refresh_tokens_and_avatar
Create Date: 2026-08-07 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003_drop_avatar_media_id"
down_revision = "0002_refresh_tokens_and_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "avatar_media_id")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_media_id", UUID(as_uuid=True), nullable=True),
    )
```

- [ ] **Step 5: Verify the migration applies cleanly in a throwaway DB**

Run (from `services/auth-service/`):

```bash
uv run alembic upgrade head
```

Expected: succeeds (Postgres dialect). If you don't have Postgres locally, skip and rely on the test suite + the production deploy.

To downgrade and re-upgrade to verify both directions:

```bash
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: both succeed.

If `alembic` complains about env config (e.g. DATABASE_URL), set it manually:

```bash
DATABASE_URL=sqlite:///:memory: uv run alembic upgrade head
```

(Note: SQLite doesn't support `drop_column` of all types, but our migration only drops a nullable UUID column, which SQLite handles fine. If a real Postgres is unavailable, this validation is best-effort.)

- [ ] **Step 6: Run the full auth-service test suite**

Run: `cd services/auth-service && uv run pytest -q`
Expected: PASS for all tests. The conftest in D2 does `SQLModel.metadata.create_all(engine)` which now produces a `users` table without `avatar_media_id`, matching the migration. The tests that set `user.avatar_media_id` would fail — but no such tests remain (test_avatar_endpoint was deleted in E1, test_avatars_service was deleted in E2).

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/app/models/entities.py \
        services/auth-service/migrations/versions/0003_drop_avatar_media_id.py \
        services/auth-service/tests/test_refresh_token_model.py
git commit -m "refactor(auth): drop users.avatar_media_id column + migration"
```

---

## Phase F — Smoke script and docs

### Task F1: Replace the old smoke script with one for the new path

**Files:**
- Delete: `scripts/smoke-auth-avatar.sh` (if it exists; verify first)
- Create: `scripts/smoke-files-avatar.sh`

**Why:** the old script exercises the deleted `/api/auth/me/avatar` endpoints. We replace it with one that exercises the new `/api/files/users/me/avatar` path.

- [ ] **Step 1: Find and inspect the existing smoke script**

Run: `ls scripts/`
Then read the existing `scripts/smoke-auth-avatar.sh` (if present) to see what it currently does; we don't need to preserve it, but we want to know what tests it ran so the new script covers the same ground.

- [ ] **Step 2: Create `scripts/smoke-files-avatar.sh`**

The new script must:
1. `POST /api/auth/login` with a known test user → obtain access token.
2. `POST /api/files/users/me/avatar` with a small PNG (multipart `file`) → assert 201.
3. `GET /api/files/users/me/avatar` → assert 302 with `Location` header.
4. `curl -I <Location>` → assert 200 (the presigned URL serves the file).
5. `GET /api/auth/me` → assert `has_avatar=true` and `avatar_url` matches the presigned URL.
6. `DELETE /api/files/users/me/avatar` → assert 204.
7. `GET /api/files/users/me/avatar` → assert 404.
8. `GET /api/auth/me` → assert `has_avatar=false`.

Use `set -euo pipefail` and clear error messages. Assume `BASE_URL` defaults to `http://localhost:8000`. The script does NOT need to provision a test user — assume one already exists in the dev DB (e.g. seeded by `make up`). Document this in a comment at the top.

Create the file with this skeleton (fill in the exact curl invocations and JSON parsing):

```bash
#!/usr/bin/env bash
# Smoke test for direct file-service access via api-gateway.
#
# Requires:
# - The full stack running (make up).
# - A test user with known credentials in the dev DB. Override via
#   SMOKE_USER_EMAIL and SMOKE_USER_PASSWORD env vars.
#
# Asserts:
# - Login works.
# - POST /api/files/users/me/avatar returns 201.
# - GET /api/files/users/me/avatar returns 302 to a presigned URL that
#   serves a 200 with the uploaded bytes.
# - GET /api/auth/me shows has_avatar=true and the same avatar_url.
# - DELETE /api/files/users/me/avatar returns 204.
# - Subsequent GET /api/files/users/me/avatar returns 404.
# - GET /api/auth/me shows has_avatar=false.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${SMOKE_USER_EMAIL:-alice@acme.com}"
PASSWORD="${SMOKE_USER_PASSWORD:-correctpw-12345}"
PNG_PATH="${PNG_PATH:-/tmp/smoke-avatar.png}"

# 1x1 transparent PNG
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' > "$PNG_PATH"

login_response=$(curl -fsS -X POST "$BASE_URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
access_token=$(echo "$login_response" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')

auth_header="Authorization: Bearer $access_token"

# Upload
upload_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X POST "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header" \
    -F "file=@$PNG_PATH;type=image/png")
[[ "$upload_status" == "201" ]] || { echo "upload expected 201, got $upload_status"; exit 1; }

# Get (302)
get_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$get_status" == "302" ]] || { echo "get expected 302, got $get_status"; exit 1; }

location=$(curl -fsS -D - -o /dev/null \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header" | tr -d '\r' | awk '/^[Ll]ocation:/ {print $2}')
[[ -n "$location" ]] || { echo "no Location header in 302 response"; exit 1; }

presign_status=$(curl -fsS -o /dev/null -w '%{http_code}' "$location")
[[ "$presign_status" == "200" ]] || { echo "presigned URL expected 200, got $presign_status"; exit 1; }

# /me shows avatar
me_response=$(curl -fsS -X GET "$BASE_URL/api/auth/me" -H "$auth_header")
has_avatar=$(echo "$me_response" | python3 -c 'import sys, json; print(json.load(sys.stdin)["has_avatar"])')
[[ "$has_avatar" == "True" ]] || { echo "/me has_avatar expected True, got $has_avatar"; exit 1; }

# Delete
delete_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X DELETE "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$delete_status" == "204" ]] || { echo "delete expected 204, got $delete_status"; exit 1; }

# Get after delete (404)
get_after_status=$(curl -fsS -o /dev/null -w '%{http_code}' \
    -X GET "$BASE_URL/api/files/users/me/avatar" \
    -H "$auth_header")
[[ "$get_after_status" == "404" ]] || { echo "get-after expected 404, got $get_after_status"; exit 1; }

# /me shows no avatar
me_response_after=$(curl -fsS -X GET "$BASE_URL/api/auth/me" -H "$auth_header")
has_avatar_after=$(echo "$me_response_after" | python3 -c 'import sys, json; print(json.load(sys.stdin)["has_avatar"])')
[[ "$has_avatar_after" == "False" ]] || { echo "/me has_avatar expected False, got $has_avatar_after"; exit 1; }

echo "OK: direct file-service access smoke test passed"
```

- [ ] **Step 3: Make the script executable**

```bash
chmod +x scripts/smoke-files-avatar.sh
```

- [ ] **Step 4: Delete the old smoke script if it exists**

```bash
rm -f scripts/smoke-auth-avatar.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke-files-avatar.sh
git rm scripts/smoke-auth-avatar.sh 2>/dev/null || true
git commit -m "test(smoke): replace auth-avatar smoke with files-avatar smoke"
```

> **Note:** the smoke script cannot be unit-tested. Manual run against a live stack is the only validation. The script is intentionally short and uses bash + python3 stdlib only.

---

### Task F2: Update `services/files-service/README.md` to document the dual-router layout

**Files:**
- Modify: `services/files-service/README.md:1-41`

**Why:** the README currently says "No expone endpoints públicos". That's no longer true.

- [ ] **Step 1: Replace the README contents**

Replace `services/files-service/README.md` with:

```markdown
# files-service

Propietario de los archivos binarios (avatares, media, assets públicos) y de la
tabla `media_resources`. Expone **dos routers**:

- `/internal/files/*` — solo para la red interna, protegido por
  `ServiceTokenMiddleware`. Después de este spec, sólo conserva dos endpoints
  de lectura (`GET /users/{user_id}/avatar`, `GET /media/{media_id}/presign`)
  que `auth-service` usa para enriquecer `/me`. **No** expone escritura.
- `/public/files/*` — para clientes a través del `api-gateway`, protegido por
  `PublicAuthMiddleware` que valida `X-User-Id` (que el gateway inyecta
  desde el JWT del usuario) y aplica ownership: cada usuario solo opera
  sobre sus propios recursos. Endpoints:
  - `POST /users/me/avatar` — upload (reemplaza el anterior). Devuelve `MediaRef`.
  - `GET /users/me/avatar` — 302 a URL presignada (TTL = `PRESIGN_TTL_SECONDS`).
  - `DELETE /users/me/avatar` — borra.
  - `GET /media/{media_id}/presign?ttl=N` — 302 a URL presignada; ownership enforced.

## Por qué hay dos routers

`auth-service` ya no es proxy de archivos. El frontend habla directo con
`files-service` (vía gateway) para subir, leer y borrar avatares. La
superficie `/public/*` se mantiene estrecha: solo avatar, validación de
size/mime en el servicio, ownership por `user_id`. No hay admin override
(queda para un plan futuro cuando exista el rol).

`auth-service` conserva una ruta interna mínima para llenar `has_avatar` /
`avatar_url` en las respuestas de `/me`, `/login`, `/refresh`. Esa ruta usa
el `/internal/files/*` de este servicio y `ServiceHttpClient`.

## Storage

Hoy la única implementación de `StorageBackend` es `MinioBackend` (SDK
`minio-py`, S3-compatible). El Protocol vive en `app/storage/base.py` y la
factoría en `app/storage/__init__.py` selecciona el backend según
`STORAGE_BACKEND` (`minio` por defecto; un placeholder `LocalBackend` lanza
`NotImplementedError`).

Los buckets se inicializan al arranque (`lifespan`) según `INIT_BUCKETS`
desde cada `services/<svc>/.env` (`INIT_BUCKETS_JSON`). Si MinIO está
caído, `files-service` falla rápido.

## Eventos

`files-service` publica `user.avatar.changed` y `user.avatar.removed` en el
stream `events:onboarding` después de un upload/delete exitoso del router
público. Consumidores futuros (notification, search index) se suscriben a
ese stream. Si Redis está caído, la publicación se loguea y se descarta —
el upload/delete sigue siendo exitoso (no hay outbox).

## Variables de entorno

Ver `services/files-service/.env.example`. Las relevantes para el router
público: `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS`.
```

- [ ] **Step 2: Commit**

```bash
git add services/files-service/README.md
git commit -m "docs(files): document dual-router layout (internal + public)"
```

---

## Final verification

After all tasks are committed, run the entire test suite from the repo root to confirm no regression anywhere.

```bash
cd shared && uv run pytest -q
cd ../services/api-gateway && uv run pytest -q
cd ../services/auth-service && uv run pytest -q
cd ../services/files-service && uv run pytest -q
cd ../services/tenant-service && uv run pytest -q
```

Expected: every suite passes. If `api-gateway` or `tenant-service` break, the change is in `shared` (Phase A) — review the middleware change.

Also verify the full stack still starts:

```bash
make up
```

Once the stack is up, run the smoke script:

```bash
bash scripts/smoke-files-avatar.sh
```

Expected: prints `OK: direct file-service access smoke test passed`.
