# lead_os

Monorepo de microservicios para lead_os: API gateway FastAPI como único entrypoint, 3 microservicios (auth, tenant, files) con estructura MVC + Facade, paquete compartido `shared/`, Postgres por servicio, eventos con Redis Streams y Docker Compose para desarrollo.

**Stack:** Python 3.12, FastAPI, uv, SQLModel/SQLAlchemy 2.0, Alembic, Pydantic v2, Postgres 16, Redis 7 (cache + Streams), Docker + Docker Compose v2.

## Arquitectura

```
cliente ──► api-gateway:8000 (único puerto publicado)
              │
              ├──► auth-service:8001   ──► auth_db   (Postgres)
              ├──► tenant-service:8002 ──► tenant_db
              └──► files-service:8004  ──► files_db  (+ storage en disco)
                     └── Redis (cache + eventos) ── Postgres (compartido)
```

- **(a) API gateway (FastAPI, `services/api-gateway`)**: valida el JWT de usuario (firmado con `SECRET_KEY` única por auth-service), inyecta `X-Service-Token` (JWT de 60s firmado con `INTER_SERVICE_SECRET`) + headers de identidad (`X-User-Id`, `X-Tenant-Id`, `X-Role-Id`, `X-Is-Superuser`), rate limit por IP (fixed window por minuto), proxy con retry para GET/HEAD y sirve `/media`/`/tutorials` localmente con soporte HTTP Range.
- **(b) Enforcement**: todo request sin `X-Service-Token` válido recibe 401 (middleware global `ServiceTokenMiddleware` en cada servicio, exento solo `/health`). Los servicios no publican puertos al host: solo se comunican por la red interna de Docker.
- **(c) `shared/`** (`lead-os-shared`, paquete pip instalable como path dependency editable): `config` (`BaseServiceSettings`), `db` (factories de engine/sesión, `get_db`, `readonly_dependency` para cross-reads), `alembic` (patrón único de `env.py`), `auth` (`ServiceHttpClient` que firma cada request, middleware, `Identity`/`get_current_identity`/`require_admin`), `events` (`EventEnvelope`, `EventBus`, `Consumer` con DLQ), `cache` (`cached`, `invalidate_pattern`), `utils` (logging, excepciones `AppError`/`NotFoundError`/`ConflictError`/`ForbiddenError`).
- **(d) Datos**: una base por servicio (misma instancia Postgres en dev). Cross-reads con rol `readonly` (ver `infra/postgres/init.sql`) + `readonly_dependency`. Migraciones por servicio con el patrón compartido `shared.alembic` (`migrations/env.py` de 4 líneas).
- **(e) Eventos**: Redis Streams, un stream por dominio (`events:auth`), consumer groups con DLQ (`events:<domain>:dlq`) y reintentos (max 5). Ejemplo real: `user.registered` — auth-service lo publica al registrar (no hay consumer wired todavía; pendiente en Plan).
- **(f) MVC + Facade por servicio**: `models/` (SQLModel), `schemas/` (Pydantic = contrato API), `serializers/` (conversiones puras), `services/` (toda la lógica; **todo query sobre tablas con `tenant_id` filtra explícitamente**), un solo `controller.py` (FACADE que orquesta services + maneja commit/rollback) y un solo `router.py` (rutas con `response_model=`, sin lógica).

## Requisitos

- Docker + Docker Compose v2
- make
- uv (solo para correr los servicios sin Docker)

## Desarrollo local

```bash
echo "POSTGRES_PASSWORD=lead_os_dev" > .env       # root .env: solo stack-level
make env-init                                    # crea services/<svc>/.env desde .env.example
make up
```

Cada microservicio tiene su propio `.env` (de `services/<svc>/.env`) y su
`.env.example` commiteado. `make env-init` es idempotente: si el `.env` ya
existe, no lo sobrescribe.

| Comando | Descripción |
|---|---|
| `make env-init` | Crea los `.env` por servicio si faltan |
| `make up` | Levanta el stack completo |
| `make down` | Apaga los contenedores |
| `make prune` | Borra contenedores y volúmenes |

**`.env` por servicio**: los secretos comunes a varios servicios
(`INTER_SERVICE_SECRET`, `SECRET_KEY`) deben coincidir entre todos los
`.env` por servicio. En producción, montá los secretos vía Docker secrets
o un gestor externo — **no commits los `.env` reales**.

**Migraciones** (primera vez y cada vez que cambien los modelos):

```bash
for svc in auth-service tenant-service files-service; do
  docker compose exec $svc uv run alembic upgrade head
done
```

Nueva migración: `docker compose exec <svc> uv run alembic revision --autogenerate -m "descripcion"` (revisar el archivo generado antes de aplicarla).

**Tests**:

```bash
cd shared && uv run pytest -q
cd services/<svc> && uv run pytest -q     # api-gateway, auth-service, tenant-service, files-service
```

**Hot reload**: los `Dockerfile.dev` montan `./services/<svc>` y `./shared` como volúmenes; editar código recarga automáticamente.

**Depurar un servicio por dentro**: `docker compose exec <svc> bash` (el venv vive en `.venv`; usar `uv run` para scripts).

## Producción

Build por servicio (contexto = raíz del repo, necesita `shared/`):

```bash
docker build -f services/<svc>/Dockerfile -t registry/lead-os-<svc>:<tag> .
```

| Servicio | Variables en `services/<svc>/.env` |
|---|---|
| api-gateway | `SECRET_KEY`, `RATE_LIMIT_PER_MINUTE`, `FRONTEND_URL`, `MEDIA_ROOT`, `CORS_ORIGIN_REGEX` |
| auth-service | `SECRET_KEY`, `FERNET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_MINUTES`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_PATH`, `COOKIE_DOMAIN`, `FILES_SERVICE_URL`, `TENANT_SERVICE_URL`, `FRONTEND_URL` |
| tenant-service | `SECRET_KEY`, `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ZONE_ID`/`CLOUDFLARE_ACCOUNT_ID` (opcionales), `BASE_DOMAIN`, `CNAME_TARGET` |
| files-service | `SECRET_KEY`, `STORAGE_BACKEND=minio`, `MINIO_ENDPOINT`, `MINIO_PUBLIC_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `MINIO_SECURE`, `MINIO_BUCKET`, `INIT_BUCKETS_JSON`, `AVATAR_MAX_BYTES`, `AVATAR_ALLOWED_MIMETYPES`, `PRESIGN_TTL_SECONDS` |

Compartidas: `SERVICE_NAME`, `DATABASE_URL` (por servicio: `auth_db`/`tenant_db`/`files_db`), `REDIS_URL`, `INTER_SERVICE_SECRET`, `ENVIRONMENT`, `DEBUG`, `PORT`, `HOST`.

**Deploy**: cada servicio con DB corre `alembic upgrade head` automáticamente al arrancar el contenedor (idempotente: solo aplica migraciones pendientes; si falla, el contenedor no arranca — fail-fast). No hace falta job de migraciones manual. Con varias réplicas por servicio, desplegar primero una sola (las migraciones compiten al arrancar simultáneo). Cada servicio recibe su propio conjunto de variables de entorno (el `.env` raíz es solo para desarrollo local); las compartidas (`INTER_SERVICE_SECRET`, `SECRET_KEY`, `REDIS_URL`) deben tener el mismo valor en todos los servicios que las usan. Solo el gateway se expone al exterior; los servicios viven en la red privada. Rotar `INTER_SERVICE_SECRET` y las claves JWT con cuidado (invalidan tokens en tránsito).

**Nota**: no se usa Supabase — Postgres propio con una base por servicio.

## Convenciones

**Añadir un endpoint**: schema Pydantic (`schemas/`) → función en `services/` → método en `controller.py` → ruta en `router.py` con `response_model=` → test de contrato. Todo query sobre tablas con `tenant_id` filtra `Model.tenant_id == identity.tenant_id`.

**Publicar/consumir un evento nuevo**:
1. Publicar post-commit con `event_bus.publish("<domain>", EventEnvelope(type=..., aggregate_id=..., tenant_id=..., payload={...}))` (ver `register_user` → `user.registered` en auth-service).
2. En el consumidor, registrar un handler idempotente en `app/events.py` (ver `build_handlers` en tenant-service).

**Añadir un microservicio nuevo** (checklist):
1. `services/<svc>/pyproject.toml` con `lead-os-shared` como path dependency (`[tool.uv.sources]`).
2. `alembic.ini` + `migrations/` con el `env.py` de 4 líneas (patrón `shared.alembic`).
3. `Dockerfile` (multi-stage uv) + `Dockerfile.dev` (hot reload), puerto interno propio.
4. Entrada en `docker-compose.yml` con `profiles: ["<svc>"]` (sin puertos publicados).
5. Ruta en `service_routes` del gateway (`services/api-gateway/app/config.py`).
6. Estructura MVC + Facade (`models/`, `schemas/`, `serializers/`, `services/`, `controller.py`, `router.py`) con tests de contrato.
