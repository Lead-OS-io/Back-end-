# lead_os — Auth completa + CRUD de usuario + Avatar (MinIO)

**Fecha:** 2026-08-06
**Estado:** Borrador para revisión
**Construye sobre:** `docs/superpowers/specs/2026-08-05-clean-slate-onboarding-design.md`

---

## Contexto

`lead_os` ya tiene:

- **auth-service** con un único endpoint `POST /api/auth/onboarding` que crea un `User` en estado `pending_tenant` y publica `onboarding.pending`.
- **files-service** con la tabla `media_resources` (enum `MediaPurpose` incluye `PROFILE_PHOTO`), pero sin endpoints ni lógica.
- **tenant-service** con `router.py` y `controller.py` vacíos a propósito.
- **api-gateway** que enruta `/api/auth/*` → auth-service, `/api/tenants/*` y `/api/files/*` → sus respectivos servicios.
- **shared/** como paquete `lead-os-shared` con `Identity`, `ServiceHttpClient`, `ServiceTokenMiddleware`, base de settings, eventos Redis Streams, etc.
- **Regla arquitectónica explícita** (sección 4.6 del spec 2026-08-05): *file-service y tenant-service NO exponen endpoints al exterior*. Toda interacción con archivos vive dentro de un router interno accesible solo vía `INTER_SERVICE_SECRET`.

Hoy el sistema **no permite** a un usuario hacer login, ni refrescar tokens, ni editar su perfil, ni subir un avatar. La superficie útil de cara al cliente es solo el alta inicial.

---

## Objetivo

Habilitar:

1. **Autenticación completa** en `auth-service`: `login`, `logout`, `refresh`, `validate`.
2. **CRUD de usuario "myself"** en `auth-service`: `GET /me`, `PATCH /me`.
3. **Avatar de usuario** en `auth-service` (gestión expuesta) + `files-service` (gestión interna con MinIO).
4. **Storage de archivos reemplazable** vía capa abstracta (`StorageBackend` Protocol).
5. **Infraestructura de MinIO** instanciada por `docker-compose`.
6. **`.env` por servicio** en lugar de `.env` raíz inyectado globalmente.
7. **Documentación de la decisión arquitectónica** en `services/files-service/README.md` y `services/tenant-service/README.md`.

---

## Decisiones de diseño

### D1. Storage backend

- **Capa abstracta** en `services/files-service/app/storage/` con un `StorageBackend` Protocol (métodos: `put_object`, `get_object`, `delete_object`, `presigned_get_url`, `ensure_bucket`, `set_bucket_public`).
- **Implementación única por ahora: `MinioBackend`** usando el SDK oficial `minio-py` (compatible con S3).
- **Placeholder `local_backend.py`** que lanza `NotImplementedError` con mensaje claro (para evitar regresiones si alguien intenta usar local disk).
- **Factory `get_storage(settings)`** devuelve el backend según `STORAGE_BACKEND=minio` (default). Hoy solo se soporta `minio`; añadir otros = nueva clase que implemente el Protocol.
- **Reemplazable en producción** sin tocar controllers: cualquier backend que implemente el Protocol funciona.

### D2. Buckets hardcodeados al arranque

- Lista fija en `ServicesConfig.INIT_BUCKETS: tuple[tuple[name, is_public], ...]`:
  ```python
  (
      ("avatars",       False),   # avatares de usuario; privado
      ("media",         False),   # archivos generales; privado
      ("public_assets", True),    # assets globales servibles publicamente
  )
  ```
- En el `lifespan` de files-service, **antes de devolver** el control a FastAPI, `get_storage(settings).ensure_bucket(name)` y `set_bucket_public(name, public=is_public)` para cada bucket.
- `ensure_bucket` y `set_bucket_public` son **idempotentes**: chequean existencia antes de crear, aplican la policy una sola vez.
- Si MinIO no responde, `files-service` **falla rápido** (el contenedor no arranca). Coherente con la regla `alembic upgrade head` fail-fast.
- **Codificación de `INIT_BUCKETS` en env**: pydantic-settings no soporta tuplas anidadas en env vars de forma nativa. Se codifica como JSON string (`INIT_BUCKETS_JSON='[["avatars",false],["media",false],["public_assets",true]]'`) y se decodifica en el método `model_post_init` o en un `@field_validator` que produce la tupla tipada.
- **Futuro**: cuando se implemente el rol administrador en un plan aparte, esta lista pasará a leerse de una tabla; el Protocol no cambia.

### D3. Exposición de files-service

- `files-service` **no tiene router público**: el cliente jamás llega a él.
- Mantiene un **router interno** con prefijo `/internal/files/*`, montado en `main.py` con `include_router` pero **NO** enrutado por el api-gateway (el gateway solo conoce `service_routes`, así que cualquier path que no empiece con `/api/auth`, `/api/tenants`, `/api/files`, `/api/resolve` no se proxy).
- Protegido por `ServiceTokenMiddleware` (igual que el resto del servicio): todas las llamadas internas deben firmar el token con `INTER_SERVICE_SECRET`.
- `tenant-service` sigue **sin router público**. Lo único que cambia en su lifecycle es el README documentando la decisión.

### D4. Tabla de medios extendida

`media_resources` gana:

- `tenant_id: UUID | None` (índice)
- `user_id: UUID | None` (índice)
- `created_at: datetime`

Migración: `services/files-service/migrations/versions/0002_media_owner.py`.

`purpose = profile_photo` representa el avatar. El servicio `MediaManager.upload_avatar` usa un **upsert**: si ya existe una fila para `(user_id, purpose='profile_photo')` actualiza `bucket`, `path`, `original_filename`, `mimetype`, `size_bytes`, `metadata`; si no, crea. **Un usuario = una fila de avatar**, no muchas.

### D5. Identificación del avatar en auth-service

- Se añade `users.avatar_media_id: UUID | None` (campo nuevo en auth, **sin FK cross-DB** — la convención se valida en service layer).
- En `GET /me` y `/me/avatar`, auth-service consulta `files-service` (vía HTTP interno) para saber si el media existe y obtener URL presigned.
- Si `files-service` devuelve 404 al pedir el media_id guardado, auth limpia la FK (`avatar_media_id = None`) en la misma transacción — autocorrección si alguien borra desde fuera.

### D6. Tokens y sesiones

- **Access token**: JWT firmado con `SECRET_KEY` (HS256), TTL `ACCESS_TOKEN_EXPIRE_MINUTES` (default 15min). Devuelto en **cuerpo del response** y consumido en `Authorization: Bearer <token>`.
- **Refresh token**: token opaco (secreto aleatorio de 32 bytes, base64url). TTL `REFRESH_TOKEN_EXPIRE_MINUTES` (default 60min = 1h). Guardado en **cookie httpOnly**, `Secure` cuando `ENVIRONMENT != "local"`, `SameSite=Strict`, `Path=/api/auth`. **Solo guardamos el `sha256(token)` en la tabla** `refresh_tokens` (mismo principio que password_hash — el raw vive solo en el cliente).
- **Rotación**: cada `/refresh` revoca el refresh viejo y emite uno nuevo. Refresh reutilizado después de rotar → 401 (sospecha de robo, se revocan **todos** los refresh tokens del usuario).
- **Revocación granular**: `logout` marca el refresh como `revoked_at=now, revoked_reason='user_logout'`. La fila queda en DB por trazabilidad.
- **Refresh tokens por sesión**: 1 fila por cada login (no se reusan ids), con `ip` y `user_agent` capturados para auditoría.

### D7. `validate`

- `GET /auth/validate` recibe solo el `Authorization: Bearer <access>` y **devuelve `{valid, expires_at, claims}` o 401**. No emite, no rota, no crea filas. Sirve para que clientes u otros servicios validen un access token sin necesidad de hablar con el gateway.
- Hoy el gateway ya valida con `SECRET_KEY` por su cuenta; este endpoint es para **consumidores que no tienen el gateway en su path** (otro servicio en el futuro, scripts de admin, etc.).

### D8. Comunicación entre auth y files

- `auth-service/app/services/files_client.py` envuelve `shared.auth.client.ServiceHttpClient` (ya existente) y expone métodos:
  - `upload_avatar(user_id, content, filename, content_type) → MediaRef`
  - `get_avatar(user_id) → MediaRef | None`
  - `delete_avatar(user_id) → None`
  - `presign_media(media_id, ttl) → str`
- Cada método hace una request HTTP interna a `http://files-service:8004/internal/files/...` con firma de `INTER_SERVICE_SECRET` automática (heredada de `ServiceHttpClient`).

### D9. Configuración por servicio (no global)

- El `.env` raíz **deja de inyectarse** en los microservicios. Solo mantiene `POSTGRES_PASSWORD` y `SKIP_SERVICES` (si el Makefile los necesita).
- Cada servicio tiene su propio `services/<svc>/.env` con sus vars. En `docker-compose.yml` se monta como `:ro` en el path del WORKDIR, así pydantic-settings lo lee.
- `env_file: .env` se **elimina** de las definiciones de `api-gateway`, `auth-service`, `tenant-service`, `files-service` en compose.
- Cada `.env.example` se commitea; los `.env` reales van a `.gitignore` (`services/*/.env`).
- El servicio `minio` comparte `services/files-service/.env` por `env_file:` en compose — un único archivo de verdad para los dos lados.
- `Makefile`: el target `env-init` se asegura de que cada `services/<svc>/.env` exista (lo copia de `.env.example` si no).

### D10. Documentación de la decisión arquitectónica

- **`services/files-service/README.md`** (nuevo): explica que el router `/internal/files/*` es solo tráfico interno protegido por `INTER_SERVICE_TOKEN`, no se enruta por el gateway, y que el cliente jamás lo alcanza. Justifica la elección en 2-3 párrafos.
- **`services/tenant-service/README.md`** (nuevo): explica por qué `router.py` está vacío (la lógica vive en services; el flujo de onboarding los convoca sin pasar por HTTP público).

---

## Cambios concretos

### `docker-compose.yml` (raíz)

- Quitar `env_file: .env` de los 4 servicios.
- Añadir volumen `./services/<svc>/.env:/app/services/<svc>/.env:ro` en cada uno.
- Añadir servicio `minio` (imagen `minio/minio:latest`, comando `server /data --console-address ":9001"`, env_file desde `services/files-service/.env`, healthcheck con `curl -f http://localhost:9000/minio/health/ready`, puertos `9000:9000` y `9001:9001` para dev).
- Añadir `minio: { condition: service_healthy }` a `depends_on` de `files-service`.
- Añadir volumen `minio_data:`.

### `.gitignore` (raíz)

- Añadir `services/*/.env`.

### `Makefile` (raíz)

- `make up` ya no presupone `.env` raíz presente.
- Añadir target `make env-init` (idempotente): copia cada `services/<svc>/.env.example` a `services/<svc>/.env` si no existe.

### `services/files-service/`

- **Crear**:
  - `app/storage/__init__.py` — `get_storage(settings) -> StorageBackend` factory.
  - `app/storage/base.py` — `StorageBackend` Protocol con `put_object`, `get_object`, `delete_object`, `presigned_get_url`, `ensure_bucket`, `set_bucket_public`.
  - `app/storage/minio_backend.py` — `MinioBackend`.
  - `app/storage/local_backend.py` — placeholder que lanza `NotImplementedError`.
  - `app/storage/manager.py` — `MediaManager(db: Session, backend, bucket)` con `upload_avatar`, `get_avatar`, `delete_avatar`, `presigned_url_for`.
  - `app/internal_router.py` — router `APIRouter()` con los 4 endpoints internos.
  - `app/internal_controller.py` — facade que llama al `MediaManager`.
  - `app/services/__init__.py` — re-exports vacíos (placeholder simétrico con auth).
  - `migrations/versions/0002_media_owner.py` — añade `tenant_id`, `user_id`, `created_at` a `media_resources`.
  - `tests/conftest.py` — añadir fixture `fake_backend` (clase `FakeStorage` que implementa el Protocol).
  - `tests/test_storage_protocol.py` — chequea que `MinioBackend` y `FakeStorage` cumplen el Protocol.
  - `tests/test_minio_backend.py` — tests del backend con fake (subir, presign, borrar, ensure/set_public idempotentes).
  - `tests/test_media_manager.py` — tests del manager con fake backend y sqlite in-memory.
  - `tests/test_internal_router_avatar.py` — tests de los 4 endpoints internos con TestClient.
  - `README.md` — decisión arquitectónica.
  - `.env.example` — todas las vars MinIO documentadas.

- **Modificar**:
  - `app/models/entities.py` — añadir `tenant_id`, `user_id`, `created_at` a `MediaResources`.
  - `app/main.py` — en `lifespan` llamar a `get_storage(settings).ensure_bucket()` + `set_bucket_public()` para cada bucket en `INIT_BUCKETS`. Montar `internal_router` con `prefix="/internal/files"` (NO exponer por el gateway).
  - `app/config.py` — añadir `STORAGE_BACKEND`, vars MinIO, `INIT_BUCKETS`, `PRESIGN_TTL_SECONDS`, `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`.
  - `app/services/__init__.py` — si existe, dejarlo vacío/placeholder.
  - `pyproject.toml` — añadir `minio==7.2.7` (o la última compatible con Python 3.12).

### `services/auth-service/`

- **Crear**:
  - `app/schemas/auth.py` — `LoginRequest`, `LoginResponse`, `RefreshResponse`, `ValidateResponse`.
  - `app/schemas/user.py` — `UserResponse`, `UserUpdateRequest`.
  - `app/schemas/avatar.py` — `AvatarResponse`.
  - `app/services/auth_tokens.py` — `mint_access_token`, `mint_refresh_token`, `hash_refresh`, `decode_access_token`, `verify_access_token`.
  - `app/services/users.py` — `get_me`, `update_me`.
  - `app/services/avatars.py` — `get_my_avatar`, `upload_my_avatar`, `delete_my_avatar`.
  - `app/services/files_client.py` — wrapper sobre `ServiceHttpClient`.
  - `app/services/login.py` — `authenticate`, `create_session`.
  - `app/services/refresh.py` — `rotate_refresh`.
  - `app/services/logout.py` — `revoke_session`.
  - `app/services/validate.py` — `validate_token`.
  - `migrations/versions/0002_refresh_tokens_and_avatar.py` — crea tabla `refresh_tokens` y añade `users.avatar_media_id`.
  - `tests/test_auth_tokens.py` — mint/hash/decode unit.
  - `tests/test_login.py` — happy path, 401 con email/password incorrecto, 401 con usuario no existe (mismo mensaje), refresh cookie set.
  - `tests/test_logout.py` — 204, cookie desaparece, fila tiene `revoked_at`.
  - `tests/test_refresh.py` — rotación, 401 con cookie expirada, 401 con cookie revocada, 401 al reusar refresh viejo después de rotar.
  - `tests/test_validate.py` — 200 con Bearer válido, 401 sin Bearer, 401 con Bearer expirado, 401 con Bearer firma inválida.
  - `tests/test_me.py` — GET devuelve perfil, PATCH actualiza, PATCH email → 422, PATCH no toca password.
  - `tests/test_avatar.py` — POST sube, GET 302, DELETE borra, mimetype no permitido → 415, size > 5MB → 413, segundo POST reemplaza.
  - `tests/test_files_client.py` — wrapper sobre `ServiceHttpClient` con `httpx.MockTransport`.
  - `.env.example` — vars nuevas (ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_MINUTES, COOKIE_SECURE, COOKIE_SAMESITE, FILES_SERVICE_URL) + las heredadas.

- **Modificar**:
  - `app/models/entities.py` — añadir `RefreshToken` (mismo archivo) y `avatar_media_id` a `User`.
  - `app/router.py` — añadir las rutas nuevas.
  - `app/controller.py` — añadir funciones facade nuevas.
  - `app/services/onboarding.py` — añadir publicación de evento `user.updated` al cambiar `users.full_name` o `phone` (opcional, MVP puede vivir en tasks futuras si se prefiere). **Decisión**: lo implementamos.
  - `app/config.py` — añadir `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_MINUTES`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_PATH`, `FILES_SERVICE_URL`.
  - `app/main.py` — nada nuevo (no requiere cambios estructurales; las rutas se añaden via `router.py`).

### `services/tenant-service/`

- **Crear**:
  - `README.md` — decisión arquitectónica.
  - `.env.example` — placeholder si no existe (las vars actuales son las mismas del .env raíz).

- **Modificar**: nada funcional.

### Raíz

- **Crear**:
  - `docs/superpowers/plans/2026-08-06-...md` (lo escribimos en el siguiente skill, no aquí).
- **Modificar**:
  - `README.md` (raíz) — actualizar tabla "Variables requeridas por servicio" para reflejar las nuevas vars de auth y files.
  - `docker-compose.yml` — los cambios arriba.
  - `.env.example` (raíz) — dejar `POSTGRES_PASSWORD` y `SKIP_SERVICES`; eliminar el resto o marcarlos como deprecados.
  - `.gitignore` — `services/*/.env`.
  - `Makefile` — añadir `env-init`, ajustar `up`.

---

## Contratos API

### `auth-service` (todos bajo `/api/auth/*`)

#### `POST /api/auth/login`

- **Body**:
  ```json
  { "email": "user@acme.com", "password": "••••••••" }
  ```
- **200**:
  ```json
  {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 900,
    "user": {
      "user_id": "uuid",
      "email": "user@acme.com",
      "full_name": "Ana",
      "phone": "+14155550100",
      "status": "active",
      "has_avatar": false,
      "avatar_url": null,
      "created_at": "2026-08-06T12:00:00Z",
      "modified_at": "2026-08-06T12:00:00Z"
    }
  }
  ```
- **Headers de respuesta**: `Set-Cookie: refresh_token=<opaque>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth; Max-Age=3600`.
- **401**: credenciales inválidas (mensaje genérico `"invalid credentials"` para evitar user enumeration).
- **429**: rate limit por IP (`RATE_LIMIT_LOGIN`, default 5/min).

#### `POST /api/auth/logout`

- **Auth**: `Authorization: Bearer <access>`.
- **204** + `Set-Cookie: refresh_token=; Max-Age=0` (que pisa la cookie existente).
- **401**: access token inválido.

#### `POST /api/auth/refresh`

- **Auth**: cookie `refresh_token` válida (no requiere Bearer).
- **200**:
  ```json
  { "access_token": "eyJ...", "token_type": "bearer", "expires_in": 900, "user": {...} }
  ```
- **Set-Cookie** con nuevo refresh (rotación).
- **401**: cookie ausente, expirada, revocada, o reuso de un refresh ya rotado (en este caso se revocan **todos** los refresh del usuario — sospecha de robo).

#### `GET /api/auth/validate`

- **Auth**: `Authorization: Bearer <access>`.
- **200**:
  ```json
  { "valid": true, "expires_at": "2026-08-06T13:00:00Z", "claims": {...} }
  ```
- **401**: Bearer ausente, expirado o firma inválida. Mismo código para los tres casos.

#### `GET /api/auth/me`

- **Auth**: Bearer.
- **200**: `UserResponse` (mismo shape que en login).
- **401**: Bearer inválido.

#### `PATCH /api/auth/me`

- **Auth**: Bearer.
- **Body**:
  ```json
  { "full_name": "Ana María", "phone": "+14155550100" }
  ```
  Ambos campos opcionales; solo se aplican los provistos. `email` y `status` **NO** son modificables.
- **200**: `UserResponse` actualizado.
- **422**: el body incluye `email` o `status` (`extra="forbid"` en el schema).
- **401**: Bearer inválido.

#### `GET /api/auth/me/avatar`

- **Auth**: Bearer.
- **302**: redirige a URL presigned GET (TTL `PRESIGN_TTL_SECONDS`, default 300s).
- **404**: el usuario no tiene avatar.
- **401**: Bearer inválido.

#### `POST /api/auth/me/avatar`

- **Auth**: Bearer.
- **Body**: `multipart/form-data` con campo `file` (imagen JPG/PNG/WEBP, ≤ 5MB).
- **200**:
  ```json
  {
    "media_id": "uuid",
    "avatar_url": "https://minio:9000/avatars/users/<uuid>/avatar.png?...",
    "size_bytes": 184234,
    "mimetype": "image/png"
  }
  ```
- **413**: archivo > 5MB.
- **415**: mimetype no permitido.
- **422**: multipart sin campo `file`.
- **401**: Bearer inválido.

#### `DELETE /api/auth/me/avatar`

- **Auth**: Bearer.
- **204**.
- **404**: el usuario no tiene avatar.
- **401**: Bearer inválido.

### `files-service` interno (`/internal/files/*`)

> Todos estos endpoints requieren `X-Service-Token` válido (lo inyecta `ServiceTokenMiddleware`).

#### `POST /internal/files/users/{user_id}/avatar`

- **Auth**: Bearer + headers `X-Tenant-Id`, `X-User-Id` propagados por el gateway.
- **Body**: `multipart/form-data` campo `file` + headers `X-Tenant-Id`, `X-User-Id`.
- **201**:
  ```json
  {
    "media_id": "uuid",
    "bucket": "avatars",
    "key": "users/<uuid>/<random>.png",
    "size_bytes": 184234,
    "mimetype": "image/png"
  }
  ```
- **404**: `user_id` no existe en auth-service (validación cross-service opcional; MVP lo acepta).

#### `GET /internal/files/users/{user_id}/avatar`

- **200**: `MediaRef`. **404**: sin avatar.

#### `DELETE /internal/files/users/{user_id}/avatar`

- **204**.

#### `GET /internal/files/media/{media_id}/presign`

- **Query**: `?ttl=300`.
- **200**: `{ "url": "https://..." }`. **404**: media_id desconocido.

---

## Eventos publicados

auth-service sigue publicando sobre el stream `auth-service`:

| Evento | Post-commit | Payload | Consumidores hoy |
|---|---|---|---|
| `onboarding.pending` | `POST /onboarding` (existente) | `{user_id, email, full_name, phone, business_name, legal_name, support_inbox, timezone}` | tenant-service (existente) |
| `onboarding.completed` | `tenant.created` consumed (existente) | `{user_id, tenant_id, email, ...}` | ninguno (auditoría) |
| `user.updated` | `PATCH /me` con cambios | `{user_id, tenant_id, changes: {full_name?, phone?}, new_values: {...}}` | ninguno (futuro users-service) |
| `user.avatar.changed` | `POST /me/avatar` (nuevo o reemplazo) | `{user_id, tenant_id, media_id, mimetype, size_bytes}` | ninguno |
| `user.avatar.removed` | `DELETE /me/avatar` | `{user_id, tenant_id, media_id}` | ninguno |

---

## Configuración

### `services/auth-service/.env.example` (nuevo, commiteado)

```
SERVICE_NAME=auth-service
ENVIRONMENT=local
DEBUG=false
PORT=8001
HOST=0.0.0.0
DATABASE_URL=postgresql+psycopg2://lead_os:lead_os_dev@postgres:5432/auth_db
REDIS_URL=redis://redis:6379/0
INTER_SERVICE_SECRET=dev-inter-service-secret-change-me

# JWT de usuarios
SECRET_KEY=dev-secret-key-change-me-0123456789
ALGORITHM=HS256

# Token TTL (en minutos)
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_MINUTES=60

# Cookies de refresh token
COOKIE_SECURE=false       # true en producción (cuando ENVIRONMENT != local)
COOKIE_SAMESITE=strict
COOKIE_PATH=/api/auth
COOKIE_DOMAIN=            # vacío = sin atributo Domain (recomendado)

# Fernet para cifrado interno
FERNET_KEY=fjCrghwKLywM1-Z8Vt2kHFCxY0_7RZZ8p8Gvzi-eyy0=

# Comunicación interna
FILES_SERVICE_URL=http://files-service:8004
TENANT_SERVICE_URL=http://tenant-service:8002
FRONTEND_URL=http://localhost:3000
```

### `services/files-service/.env.example` (nuevo, commiteado)

```
SERVICE_NAME=files-service
ENVIRONMENT=local
DEBUG=false
PORT=8004
HOST=0.0.0.0
DATABASE_URL=postgresql+psycopg2://lead_os:lead_os_dev@postgres:5432/files_db
REDIS_URL=redis://redis:6379/0
INTER_SERVICE_SECRET=dev-inter-service-secret-change-me
SECRET_KEY=dev-secret-key-change-me-0123456789
ALGORITHM=HS256

# Storage
STORAGE_BACKEND=minio
MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=localhost:9000

# Estas dos vars se inyectan TANTO al contenedor `minio` (como MINIO_ROOT_USER/PASSWORD)
# COMO al SDK de files-service. En producción rotar ambos lados a la vez.
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_SECURE=false
MINIO_BUCKET=media

# Buckets hardcodeados al arranque. (Futuro: vendrán de tabla al implementar rol admin.)
# (nombre_snake_case, is_public)
INIT_BUCKETS_JSON='[["avatars",false],["media",false],["public_assets",true]]'

# Upload constraints
AVATAR_MAX_BYTES=5242880           # 5 MB
AVATAR_ALLOWED_MIMETYPES=image/jpeg,image/png,image/webp
PRESIGN_TTL_SECONDS=300
```

> Detalle de codificación de `INIT_BUCKETS`: ver Decisión D2 — se almacena como `INIT_BUCKETS_JSON` (string JSON) y se decodifica vía `@field_validator` en el `Settings`.

### `services/tenant-service/.env.example` (crear si no existe)

Mantiene las vars actuales que ya estaban en el `.env.example` raíz (`CLOUDFLARE_*` opcionales, etc.).

### `services/api-gateway/.env.example` (crear si no existe)

`SECRET_KEY`, `RATE_LIMIT_PER_MINUTE`, `FRONTEND_URL`, `MEDIA_ROOT`, `CORS_ORIGIN_REGEX`, `AUTH_SERVICE_URL`, `TENANT_SERVICE_URL`, `FILES_SERVICE_URL`.

### `.env` raíz (`/.env`)

Mantener **solo**:

```
POSTGRES_PASSWORD=lead_os_dev
SKIP_SERVICES=
```

El resto se mueve a cada `services/<svc>/.env`. El `.env.example` raíz se reduce a estas dos vars (o se elimina).

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| MinIO caído al arranque → files-service no inicia | Healthcheck en compose + fail-fast en `ensure_bucket`/`set_bucket_public`. README documenta cómo inspeccionar logs. |
| `COOKIE_SECURE=true` rompe dev local con http | Default `COOKIE_SECURE=false` cuando `ENVIRONMENT=local`. Variables separadas. |
| Cross-service FK `users.avatar_media_id → media_resources.id` no se puede a nivel DB (otra DB) | Validamos por convención en service layer. Si files devuelve 404 al pedir `media_id`, auth limpia la FK en la misma transacción. |
| URL presigned filtrada a logs | No logueamos URLs completas. Solo `media_id` y `ttl_seconds` estructurados. |
| Refresh token robado | Mitigación múltiple: cookie httpOnly + SameSite=Strict + rotación por uso + revocación explícita + revocación en cascada si se detecta reuso. |
| Tests de MinIO acoplados al SDK | `StorageBackend` Protocol + `FakeStorage` en conftest. Tests del Manager sin tocar MinIO real. Tests de integración contra MinIO real marcados como opcionales / manuales. |
| Re-deploy de un servicio en producción sin haber actualizado `.env` | Documentado en README raíz: "rotar `SECRET_KEY` y `INTER_SERVICE_SECRET` requiere tocar todos los `.env` por servicio simultáneamente". |

---

## Criterios de éxito

- [ ] `make up` arranca Postgres + Redis + MinIO + gateway + auth-service + tenant-service + files-service, todos `healthy`.
- [ ] `docker compose exec minio curl -f http://localhost:9000/minio/health/ready` → 200.
- [ ] `minio/9001` (consola) accesible en `localhost:9001` con `minioadmin/minioadmin`. Muestra buckets `avatars`, `media`, `public_assets` con sus policies correctas.
- [ ] `POST /api/auth/login` con creds válidas → 200 con access token + Set-Cookie refresh + `user.has_avatar=false`. Creds inválidas → 401 (mismo mensaje para email inexistente / password incorrecto).
- [ ] `POST /api/auth/refresh` con cookie válida → 200 + nuevo refresh rotado (cookie vieja queda invalidada en DB).
- [ ] Reusar la cookie vieja después de rotar → 401 + cascade de revocación (todos los refresh del usuario quedan revocados).
- [ ] `POST /api/auth/logout` → 204. Cookie desaparece. La fila `refresh_tokens` tiene `revoked_at`.
- [ ] `GET /api/auth/validate` con Bearer válido → 200 con claims + exp. Sin Bearer → 401.
- [ ] `GET /api/auth/me` con Bearer → 200 con perfil. PATCH con `{full_name: "X"}` → 200 actualizado. Intentar PATCH `email` → 422.
- [ ] `POST /api/auth/me/avatar` con multipart imagen PNG 2MB → 200 + URL presigned. Imagen > 5MB → 413. mimetype `image/gif` → 415. Segunda subida → reemplaza (mismo endpoint, key distinta en MinIO).
- [ ] `GET /api/auth/me/avatar` → 302 a URL presigned MinIO válida 5min. Sin avatar → 404.
- [ ] `DELETE /api/auth/me/avatar` → 204. Verificar en MinIO consola que el objeto ya no existe y la fila `media_resources` se borró.
- [ ] `grep -r "router.include_router" services/files-service/app/main.py` → solo `internal_router`, prefix `/internal/files`, **sin** `service_routes` que apunte a `/api/files` o `/internal/files` desde el gateway.
- [ ] `services/api-gateway/app/config.py` mantiene las mismas 4 rutas (`/api/auth`, `/api/tenants`, `/api/files`, `/api/resolve`) y **ninguna referencia nueva** a `/internal/*`.
- [ ] `services/files-service/README.md` y `services/tenant-service/README.md` existen, con su decisión arquitectónica justificada en 2-3 párrafos cada uno.
- [ ] `services/api-gateway/.env.example`, `services/auth-service/.env.example`, `services/tenant-service/.env.example`, `services/files-service/.env.example` existen y están commiteados. Sus contrapartes `.env` están en `.gitignore`.
- [ ] `pytest -q` en cada servicio pasa al 100% (auth + tenant + files + shared).
- [ ] Smoke E2E manual con `curl` siguiendo los criterios anteriores documentados en `scripts/smoke-auth-avatar.sh`.

---

## Fuera de alcance (planes futuros)

- Reset / forgot password.
- Cambio de email (verification flow).
- Cambio de contraseña desde el usuario (con current password).
- Login con Google OAuth (el README menciona `GOOGLE_CREDENTIALS_JSON` pero los endpoints no existen; vivirá en otro plan).
- Listado de usuarios / búsqueda (solo admin).
- Roles y permisos finos (admin-only mutations).
- Avatar cropping / variants (thumbnail, retina, etc.).
- Rate-limit middleware global configurable.
- Migración del bucket config de hardcoded → tabla (cuando exista rol admin).
