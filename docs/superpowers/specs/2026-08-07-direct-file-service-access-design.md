# Direct File-Service Access — Design

> Decouples `files-service` from `auth-service` so the frontend can talk directly to it via the API gateway for avatar lifecycle (upload / get / delete), while `auth-service` keeps a narrow internal read path to enrich `/auth/me`, `/auth/login` and `/auth/refresh` with the user's avatar.

**Author:** brainstorming session 2026-08-07
**Status:** Draft for review
**Scope:** files-service (new public router + ownership guard + DB migration), auth-service (delete file endpoints + DB migration), api-gateway (no config changes), shared (no changes), docker-compose (no changes).

---

## 1. Goals

1. Frontend can upload, get (presigned), and delete its own avatar by calling `file-service` directly via the API gateway, without going through `auth-service`.
2. `auth-service` loses its avatar lifecycle endpoints (`POST/GET/DELETE /api/auth/me/avatar`) and the `FilesClient` / `avatars` service module entirely.
3. `auth-service` keeps a thin internal read path to `files-service` so that `UserResponse` (returned by `/api/auth/me`, `/api/auth/login`, `/api/auth/refresh`, `PATCH /api/auth/me`) still includes `has_avatar` and `avatar_url`.
4. Public endpoints enforce `user_id` ownership: a user can only operate on their own resources. Admin override is out of scope (a future plan).
5. `users.avatar_media_id` column is removed from auth-service DB. The avatar FK is gone.
6. `files-service` publishes `user.avatar.changed` and `user.avatar.removed` events after successful uploads and deletes from its public endpoint.

## 2. Non-goals

- Admin override for ownership (deferred to a future plan when an admin role exists).
- Generic file upload (only avatar, only `profile_photo` purpose).
- Replacing the `X-Service-Token` inter-service mechanism with something else.
- OAuth flows or any new auth method.
- Changing the gateway config (the `/api/files` route already exists).
- New rate limiting specific to uploads.
- File-service storage backend swap (still MinIO today).

## 3. Architecture

### 3.1 Topology

```
Frontend  ──►  api-gateway  ──►  files-service  (public router, JWT + ownership)
                              ─►  auth-service   (login/me/refresh)

auth-service  ──►  files-service  (internal router, X-Service-Token, read-only for /me enrichment)
```

- `api-gateway` keeps its existing `service_routes` config; no changes.
- `files-service` runs **two routers in the same FastAPI app**:
  - `/internal/files/*` — narrow read-only path for auth-service (`GET /users/{user_id}/avatar`, `GET /media/{media_id}/presign`). Authenticated by `X-Service-Token` via existing `ServiceTokenMiddleware`. The `POST` and `DELETE` internal avatar endpoints are removed.
  - `/public/files/*` — new router mounted at the app root, validated by a new `PublicAuthMiddleware` that decodes the user JWT (passed through by the gateway) and populates identity. Every endpoint enforces `user_id == X-User-Id` (or 403).

### 3.2 Why two routers, not one with branch logic

- The internal router is mounted before `ServiceTokenMiddleware`, the public one after it (with the middleware skipped). Two routers in one app is the simplest expression of "different auth, different paths" without coupling.
- Keeps `auth-service`'s call to `files-service` for `/me` enrichment identical (still hits `/internal/files/...`, still sends `X-Service-Token`, no path rename).

### 3.3 Endpoint map

| Action | Old path | New path |
|---|---|---|
| Upload avatar | `POST /api/auth/me/avatar` (auth-service) | `POST /api/files/users/me/avatar` (files-service via gateway) |
| Get avatar (302 → presigned) | `GET /api/auth/me/avatar` (auth-service) | `GET /api/files/users/me/avatar` (files-service via gateway) |
| Delete avatar | `DELETE /api/auth/me/avatar` (auth-service) | `DELETE /api/files/users/me/avatar` (files-service via gateway) |
| Presign by media_id | `GET /api/auth/me/avatar` (implicit) | `GET /api/files/media/{media_id}/presign?ttl=300` (files-service via gateway) |
| Get avatar for /me enrichment | `auth-service` → `/internal/files/users/{user_id}/avatar` (auth-service) | **Unchanged.** Same internal call. |
| Presign by media_id (internal) | `auth-service` → `/internal/files/media/{media_id}/presign` | **Unchanged.** Same internal call. |

### 3.4 Identity & ownership

The gateway already decodes the user JWT and injects:
```
X-User-Id
X-Tenant-Id
X-Is-Superuser
X-Role-Id   (only if present)
```

`files-service` PublicAuthMiddleware reads `X-User-Id` and rejects the request with 401 if missing or not a valid UUID (defense in depth: the gateway already validated the JWT). Then each handler enforces ownership by comparing `X-User-Id` to the resource owner:

- For `/users/me/avatar`: the path resolves `me → X-User-Id` server-side; no path param is trusted.
- For `/media/{media_id}/presign`: the row's `user_id` must equal `X-User-Id`; otherwise 403.

### 3.5 Data flow — upload avatar

```
1. Frontend POST /api/files/users/me/avatar (multipart file=...)
2. Gateway decodes JWT, sets X-User-Id, X-Tenant-Id, X-Is-Superuser, X-Service-Token
3. Gateway proxies to files-service:8004 → /public/files/users/me/avatar
4. ServiceTokenMiddleware exempts /public/* (path-prefix allowlist)
5. PublicAuthMiddleware decodes X-User-Id (validates UUID format)
6. Handler validates: file size <= AVATAR_MAX_BYTES, mimetype in AVATAR_ALLOWED_MIMETYPES, file non-empty
7. Handler calls MediaManager.upload_avatar(user_id=X-User-Id, ...) — replaces existing
8. Handler publishes `user.avatar.changed` event via `shared.events.bus` (domain="onboarding", same stream used by `auth-service` for user/onboarding/tenant events).
9. Returns 201 with MediaRef {media_id, bucket, key, size_bytes, mimetype, purpose}
```

### 3.6 Data flow — get avatar

```
1. Frontend GET /api/files/users/me/avatar
2. Gateway → files-service:8004 → /public/files/users/me/avatar
3. PublicAuthMiddleware decodes X-User-Id
4. Handler calls MediaManager.get_avatar(user_id=X-User-Id)
5. If not found → 404 with {detail: "avatar not found"}
6. Else: call MediaManager.presigned_url_for(media_id, ttl=settings.PRESIGN_TTL_SECONDS)
7. Returns 302 with Location header = presigned URL
```

### 3.7 Data flow — delete avatar

```
1. Frontend DELETE /api/files/users/me/avatar
2. Gateway → files-service:8004 → /public/files/users/me/avatar
3. PublicAuthMiddleware decodes X-User-Id
4. Handler calls MediaManager.delete_avatar(user_id=X-User-Id)
5. If not found → 404
6. Else: publish user.avatar.removed event
7. Returns 204 No Content
```

### 3.8 Data flow — `/auth/me` after refactor

```
1. Frontend GET /api/auth/me (Bearer access_token)
2. Gateway decodes JWT, sets identity headers
3. Gateway proxies to auth-service:8001 → /api/auth/me
4. auth-service handler reads X-User-Id (or re-decodes from Authorization header — see §6.3)
5. auth-service loads user from its DB
6. auth-service calls files-service /internal/files/users/{user_id}/avatar with X-Service-Token
7. If 200: get media_id, then GET /internal/files/media/{media_id}/presign → put in avatar_url
8. If 404: has_avatar=false, avatar_url=null, no side effect
9. Return UserResponse as today
```

The `FilesClient` and the `get_avatar_for_user` helper stay in auth-service — they are now ONLY used by `_build_user_response`. The internal upload/delete helpers (`upload_avatar_for_user`, `delete_avatar_for_user`) are deleted from auth-service.

## 4. Components

### 4.1 files-service changes

**New files:**
- `services/files-service/app/public_router.py` — FastAPI router mounted at `/public/files`. Endpoints:
  - `POST /users/me/avatar` → `MediaManager.upload_avatar(user_id=X-User-Id, ...)`. Returns `201` with `MediaRef`.
  - `GET /users/me/avatar` → calls `MediaManager.get_avatar(user_id=X-User-Id)`, then `MediaManager.presigned_url_for(media_id, ttl=settings.PRESIGN_TTL_SECONDS)`. Returns `302` with `Location` header. If no row, `404`.
  - `DELETE /users/me/avatar` → `MediaManager.delete_avatar(user_id=X-User-Id)`. Returns `204`. If no row, `404`.
  - `GET /media/{media_id}/presign?ttl=300` → looks up the row, enforces `row.user_id == X-User-Id` (else `403`), returns `302` with presigned URL using the query `ttl` (default 300, clamped to `[1, settings.PRESIGN_TTL_SECONDS]`).
- `services/files-service/app/auth.py` — `PublicAuthMiddleware` (decodes `X-User-Id` into a request-scoped identity) and `get_current_identity` dependency.
- `services/files-service/tests/test_public_router.py` — Endpoint tests with mock middleware injection.

**Reused schemas (no new file needed):** `MediaRef` and `PresignResponse` from `services/files-service/app/schemas/internal.py` are reused for public responses. No new schema module.

**Modified files:**
- `services/files-service/app/main.py` — Mount the public router. Update `ServiceTokenMiddleware` exempt list to include `/public` paths. Mount order: `ServiceTokenMiddleware` (skips `/public/*` and `/health`), then `PublicAuthMiddleware` (only applies to `/public/*`).
- `services/files-service/app/internal_router.py` — Remove `POST /users/{user_id}/avatar` and `DELETE /users/{user_id}/avatar`. Keep `GET /users/{user_id}/avatar` and `GET /media/{media_id}/presign`.
- `services/files-service/app/config.py` — No new settings required (already has `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS`). Add `PUBLIC_IDENTITY_HEADER = "X-User-Id"` constant for clarity.
- `services/files-service/tests/conftest.py` — Add `client_with_identity` fixture that injects `X-User-Id` headers directly (bypassing JWT decoding — same pattern the existing test suite uses for the internal router).
- `services/files-service/README.md` — Update the "internal-only router" doc block to describe the dual-router layout.

### 4.2 auth-service changes

**Deleted files:**
- `services/auth-service/app/services/files_client.py` — entire file.
- `services/auth-service/app/services/avatars.py` — entire file (upload/delete helpers; the read helper `get_avatar_for_user` is migrated to `users.py` — see below).

**Modified files:**
- `services/auth-service/app/controller.py` — Remove imports of `avatars` and `files_client`. Remove `_FILES_CLIENT_OVERRIDE` plumbing. Remove `_build_user_response`'s dependency on `get_avatar_for_user` (replace with a thin `_load_avatar_summary` helper that returns `(has_avatar, avatar_url)`). Remove `get_my_avatar_response`, the upload portion of `post_my_avatar`, and the delete portion of `delete_my_avatar`.
- `services/auth-service/app/router.py` — Remove the `GET /me/avatar`, `POST /me/avatar`, `DELETE /me/avatar` routes.
- `services/auth-service/app/services/users.py` — Keep `get_user_by_id`. Add a thin `_build_avatar_summary(user, settings)` helper (or move it to `services/avatars_read.py` — see file split below).
- `services/auth-service/app/services/__init__.py` — Drop the avatar/file re-exports.
- `services/auth-service/app/schemas/avatar.py` — Delete (only used by `post_my_avatar`).
- `services/auth-service/app/config.py` — Drop `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS` settings (no consumers remain).
- `services/auth-service/app/main.py` — Stop importing the deleted services (if anything imported them in lifespan).
- `services/auth-service/.env`, `.env.example` — Drop the avatar env vars.
- `services/auth-service/app/models/entities.py` — Remove `User.avatar_media_id`.
- `services/auth-service/migrations/versions/0003_drop_avatar_media_id.py` — New migration: `op.drop_column("users", "avatar_media_id")` with `downgrade()` that re-adds it.
- `services/auth-service/tests/conftest.py` — Remove `FakeFilesClient`, `fake_files_client` fixture, and the `_FILES_CLIENT_OVERRIDE` monkeypatch.
- `services/auth-service/tests/test_avatar_endpoint.py` — Delete.
- `services/auth-service/tests/test_files_client.py` — Delete.
- `services/auth-service/tests/test_avatars_service.py` — Reduce to `test_avatars_read.py` covering only the read helper used by `_build_user_response`.
- `services/auth-service/tests/test_me.py`, `test_login.py`, `test_refresh.py`, `test_patch_me.py` — Update any test that expected `has_avatar`/`avatar_url` to mock the new read helper.

### 4.3 api-gateway changes

**None.** The `/api/files` route is already wired in `app/config.py:26` and points at `files-service:8004`. The gateway's `GatewayAuthMiddleware` already injects `X-User-Id` for any non-public path. We only need to make sure `/api/files/users/me/avatar` is **not** in `PUBLIC_PATH_PREFIXES` (`app/utils/middleware.py:19-29`). It is not.

### 4.4 shared changes

**None.** `ServiceTokenMiddleware` exempt list is configured per-app; we update the files-service `main.py`, not the middleware.

## 5. File split inside auth-service

To keep files focused, the avatar read helper lives in its own module after the split:

- `services/auth-service/app/services/avatars_read.py` — A ~30-line module with:
  - `_FilesReadClient` protocol (minimal: `get_avatar(user_id) -> MediaRef | None`, `presign(media_id, ttl) -> str | None`).
  - `get_avatar_summary(user, settings) -> AvatarSummary` — calls the protocol, returns `(has_avatar, avatar_url)`. No side effects, no FK writes.
  - `_FILES_READ_CLIENT_OVERRIDE` test seam (same pattern as the old `_FILES_CLIENT_OVERRIDE`).
- `services/auth-service/app/services/users.py` — Stays small; only `get_user_by_id`, `update_user_profile`, and the `_build_user_response` glue that calls `get_avatar_summary`.

This preserves the existing test seam pattern and isolates the read-path complexity.

## 6. Data model

### 6.1 files-service — unchanged schema

`media_resources` table is unchanged. New rows still have `user_id`, `tenant_id` (NULL for avatars), `bucket="avatars"`, `path="users/{user_id}/..."`, `purpose="profile_photo"`, `is_public=false`. The public router uses the same `MediaManager` methods.

### 6.2 auth-service — column drop

Migration `0003_drop_avatar_media_id`:
```python
def upgrade() -> None:
    op.drop_column("users", "avatar_media_id")

def downgrade() -> None:
    op.add_column("users", sa.Column("avatar_media_id", postgresql.UUID(as_uuid=True), nullable=True))
```

The column is dropped from `auth_db.users` only. The referenced rows in `files_db.media_resources` are **not** touched — they remain valid for users that still have an avatar object in MinIO. `file-service` is the new authoritative store for `user_id → avatar` linkage (via the `media_resources.user_id` column). Downtime: zero, because `auth-service` no longer references the column after deploy (the endpoint deletion is in the same release).

### 6.3 Event payloads (unchanged shape)

`user.avatar.changed`:
```json
{
  "type": "user.avatar.changed",
  "aggregate_id": "<user_id>",
  "tenant_id": null,
  "payload": {"user_id": "<uuid>", "media_id": "<uuid>", "mimetype": "image/png", "size_bytes": 12345}
}
```

`user.avatar.removed`:
```json
{
  "type": "user.avatar.removed",
  "aggregate_id": "<user_id>",
  "tenant_id": null,
  "payload": {"user_id": "<uuid>"}
}
```

**Event domain:** Both events publish on `domain="onboarding"` (the same stream `auth-service` already uses for `user.registered`, `user.updated`, `tenant.created`, `onboarding.pending`, `onboarding.completed`). No new event stream is introduced. This keeps consumer registration consistent and avoids creating a one-event-per-stream split.

## 7. Error handling

### 7.1 Public router (files-service)

| Status | When |
|---|---|
| 400 | File field missing, mimetype not in allowed set, file empty (explicit check beyond FastAPI's "required") |
| 401 | `X-User-Id` missing or not a UUID |
| 403 | `/media/{media_id}/presign` called by user who is not the owner of the media row |
| 404 | No avatar row exists for the user (**GET and DELETE only**; upload does not consult state) |
| 413 | File size > `AVATAR_MAX_BYTES` |
| 422 | Pydantic validation failure (multipart parsing) |

### 7.2 Internal router (files-service, after deletion of upload/delete)

| Status | When |
|---|---|
| 401 | `X-Service-Token` missing/invalid (existing middleware) |
| 404 | No avatar row for the user, or no media row for the presign call |

### 7.3 auth-service `/me` (after refactor)

- If `files-service` GET 404s → `has_avatar=false`, `avatar_url=null`, no side effect, response 200.
- If `files-service` returns 5xx or times out → `_build_user_response` returns `has_avatar=false`, `avatar_url=null` (graceful degradation; same behavior as the existing 404 path). Logs a warning.
- The endpoint never returns 5xx because of avatar — it always succeeds with avatar fields populated or nulled.

### 7.4 Event publishing failures

If publishing `user.avatar.changed/removed` fails (Redis down), the upload/delete still succeeds. The event publish is wrapped in try/except and logs the failure. YAGNI: no outbox table, no retry queue. If durability becomes a requirement, a future plan adds it.

## 8. Auth & middleware wiring in files-service

### 8.1 ServiceTokenMiddleware update

`app/main.py` mounts `ServiceTokenMiddleware` with `exempt_paths={"/health", "/public"}` (regex or prefix — see implementation). Anything under `/internal/files` still requires `X-Service-Token`. `/public/files` does not.

### 8.2 PublicAuthMiddleware

New middleware class in `app/auth.py`:

```python
class PublicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/public"):
            return await call_next(request)
        user_id_header = request.headers.get("X-User-Id")
        if not user_id_header:
            return JSONResponse({"detail": "missing X-User-Id"}, status_code=401)
        try:
            user_id = uuid.UUID(user_id_header)
        except ValueError:
            return JSONResponse({"detail": "invalid X-User-Id"}, status_code=401)
        request.state.identity = Identity(user_id=user_id, tenant_id=...)
        return await call_next(request)
```

`Identity` is the existing dataclass in `shared/auth/dependencies.py`. No new shared code.

`get_current_identity` dependency reads `request.state.identity` and returns it (FastAPI dep that wraps `request: Request`). Handlers receive it via `Depends(get_current_identity)`.

### 8.3 Mount order

```
ServiceTokenMiddleware  (skips /health and /public/*)
  └─► PublicAuthMiddleware  (only enforces on /public/*)
        └─► FastAPI router dispatch
```

PublicAuthMiddleware is added in `app/main.py:create_app()` after `ServiceTokenMiddleware`.

## 9. Testing

### 9.1 Unit / integration (in-memory, no Docker)

- `services/files-service/tests/test_public_router.py`:
  - `test_upload_avatar_happy_path`: POST /public/files/users/me/avatar with `X-User-Id` → 201 + MediaRef; assert `MediaManager.upload_avatar` called with that user_id.
  - `test_upload_avatar_replaces_existing`: assert second upload deletes first.
  - `test_upload_avatar_rejects_oversize`: 413.
  - `test_upload_avatar_rejects_bad_mimetype`: 400.
  - `test_upload_avatar_rejects_empty`: 400.
  - `test_upload_avatar_missing_identity`: no `X-User-Id` → 401.
  - `test_get_avatar_returns_302`: assert Location header is presigned URL.
  - `test_get_avatar_not_found_returns_404`.
  - `test_delete_avatar_happy_path`: 204.
  - `test_delete_avatar_not_found_returns_404`.
  - `test_presign_ownership_enforced`: user A tries to presign user B's media → 403.
  - `test_presign_happy_path`: 200 + presigned URL.
  - `test_upload_publishes_event`: assert `EventBus.publish` called with `user.avatar.changed`.
  - `test_delete_publishes_event`: assert `EventBus.publish` called with `user.avatar.removed`.
- `services/auth-service/tests/test_avatars_read.py`:
  - `test_get_avatar_summary_returns_url_when_remote_has_avatar`
  - `test_get_avatar_summary_returns_false_on_404`
  - `test_get_avatar_summary_returns_false_on_5xx_graceful`
  - `test_user_response_includes_avatar_fields` (smoke through `/me`)
- `services/auth-service/tests/test_me.py`, `test_login.py`, `test_refresh.py`, `test_patch_me.py`: existing avatar-related assertions preserved, fixture swap from `fake_files_client` → `fake_files_read_client`.

### 9.2 Manual smoke

- Extend `scripts/smoke-auth-avatar.sh` (or replace it with `scripts/smoke-files-avatar.sh`) to exercise the new direct path:
  1. Login → obtain JWT.
  2. `POST /api/files/users/me/avatar` with a small PNG → 201.
  3. `GET /api/files/users/me/avatar` → 302 to presigned URL → curl that URL → 200 with image bytes.
  4. `GET /api/auth/me` → assert `has_avatar=true`, `avatar_url` matches the presigned URL.
  5. `DELETE /api/files/users/me/avatar` → 204.
  6. `GET /api/files/users/me/avatar` → 404.
  7. `GET /api/auth/me` → assert `has_avatar=false`.

### 9.3 What's NOT tested

- Cross-service network integration (no contract test harness in the repo today).
- Real MinIO / Postgres / Redis (out of scope; tests use in-memory sqlite + fakeredis + FakeStorage).

## 10. Rollout

This is a breaking change for any frontend code that:
- Calls `POST/GET/DELETE /api/auth/me/avatar`.
- Reads `users.avatar_media_id` directly (no service does this; safe).

The change ships as one coordinated release across `files-service` (public router + internal POST/DELETE removed), `auth-service` (avatar endpoints deleted + column dropped), and the frontend. Order:

1. Deploy `files-service` with both the new public router AND the internal POST/DELETE removed. Until the frontend switches, any caller of the old `POST/DELETE /api/auth/me/avatar` paths will get 404.
2. Deploy `auth-service` with the avatar endpoints deleted and migration `0003_drop_avatar_media_id` applied.
3. Deploy the frontend pointing at the new `/api/files/users/me/avatar` paths.
4. Run `scripts/smoke-files-avatar.sh` (replaces/extends `scripts/smoke-auth-avatar.sh`).

There is no transitional state where both old and new coexist — the internal POST/DELETE in `files-service` is removed in the same release that adds the public router. We do not use a feature flag; the change is small and coordinated.

## 11. Risk register

| Risk | Mitigation |
|---|---|
| Frontend broken during deploy window | Coordinated deploy, smoke script run before declaring done. |
| `/auth/me` latency increase (now hits files-service on every call) | Acceptable: avatar fetch is presigned (single GET), cached at MinIO. If it becomes a problem, add Redis cache in a future plan. |
| Public router accidentally exposes a write path to another tenant | Ownership check + path resolution `me → X-User-Id`. Tests cover the cross-user case. |
| ServiceTokenMiddleware exempt list accidentally exposes internals | Exempt list is `{"/health", "/public"}` — narrow, explicit, tested. |
| Events silently lost on Redis outage | Acceptable today; documented as future work. |

## 12. Open questions

None at design time. The deferred items (admin override, event durability, generic file uploads, OAuth) are explicitly out of scope and listed in §2.

## 13. Spec coverage check (against original ask)

| User requirement | Covered by |
|---|---|
| "desacoplar file-service de auth-service" | §3.1, §4 |
| "permitir que el frontend hable directo con file-service a través del gateway" | §3.1, §3.5-3.7, §4.1 |
| "cada petición valida token y rechaza si el contenido no le pertenece o el token es inválido" | §3.4, §7.1, §8.2 |
| "el endpoint /auth/me consulta el avatar del usuario" | §3.8, §4.2, §7.3 |
| "no tener que pasar por auth-service para operaciones con archivos" | §3.5-3.7 |
| "borrar endpoints existentes de archivos en auth-service" | §4.2 |
| "presigned GET (302) para descargas" | §3.6 |
| "user_id match + sin override admin por ahora" | §3.4 |
| "file-service valida size/mime" | §3.5, §4.1 |
| "upsert (reemplaza) en upload" | §3.5 |
| "borrar columna avatar_media_id" | §6.2 |
| "file-service publica los eventos" | §6.3 |
| "reusar /api/files en el gateway (no tocar config)" | §3.1, §4.3 |
| "/api/files/users/me/avatar (me-based path)" | §3.3 |
| "rate limit global aplica igual" | §2 non-goals |

All requirements covered. No gaps.
