# lead_os — Restructure: uv, shared core, API Gateway, MVC/Facade, Event-Driven

**Fecha:** 2026-08-03
**Estado:** Aprobado por el usuario (brainstorming completo)

## Contexto

Este proyecto es un **clon temprano de otro proyecto más avanzado**; solo usamos la base para comenzar desarrollo nuevo. Hoy es un "monolito de microservicios" sin patrón: 6 servicios FastAPI con estructura plana copy-pasteada, dos capas de gateway (Traefik YAML + proxy FastAPI en `main.py` raíz), un paquete `shared/` que es código muerto, drift de versiones (fastapi 0.104/0.111, pydantic 2.5/2.7/2.9, Python 3.11/3.12), Alembic sin usar (un `migrations/env.py` huérfano, tablas creadas con `create_all`), cero tests, cero mensajería, y un Dockerfile raíz que levanta todo en un solo contenedor para Railway.

## Objetivo

Reestructurar el monorepo para que:

1. `requirements.txt` → `pyproject.toml` por microservicio gestionado con **uv** (mismas deps/versiones del requirements.txt raíz).
2. Código compartido real centralizado en la raíz: config, database, alembic (patrón único, historial por servicio), auth inter-servicio, y bus de eventos.
3. Arquitectura **event-driven** (Redis Streams) para cambios de estado; HTTP/SELECT directo a la DB del servicio objetivo para lecturas.
4. Un **verdadero API gateway** FastAPI en `services/api-gateway`; ningún microservicio acepta requests que no vengan del gateway.
5. Cada microservicio sigue estrictamente **MVC + patrón FACADE**: carpetas `schemas/`, `serializers/`, `services/`, `utils/`, `models/`, y un solo `controller.py` (facade) + un solo `router.py`.
6. Docker: sin Dockerfile raíz; cada servicio tiene `Dockerfile` (producción) y `Dockerfile.dev` (hot reload); `docker-compose.yml` raíz solo para desarrollo local con exclusión de servicios vía variable de entorno; `Makefile` con `up`/`down`/`prune`.
7. `README.md` documentando arquitectura y cómo levantar local y producción.

## Decisiones de diseño (tomadas en brainstorming, no reabrir)

| # | Decisión | Elección |
|---|----------|----------|
| 1 | Servicios a eliminar primero | `cases-service`, `news-service` (+ archivos muertos asociados) |
| 2 | Tecnología del API gateway | **FastAPI** (absorbe la lógica del `main.py` raíz; Traefik se elimina) |
| 3 | Broker de eventos | **Redis Streams** (Redis ya está en el stack) |
| 4 | Distribución de deps | **pyproject.toml por microservicio** (despliegue independiente), NO workspace |
| 5 | Código compartido | `shared/` como **paquete instalable** (`lead-os-shared`), path dependency editable |
| 6 | Enforcement "solo gateway" | **Red interna sin puertos publicados + service-token JWT** firmado con `INTER_SERVICE_SECRET` |
| 7 | Topología DB | **Database por servicio** en una instancia Postgres; cross-reads con rol read-only |
| 8 | Prod DB | Postgres propio, **NO Supabase**; URLs 100% env-driven |
| 9 | RLS | Se elimina (`db/rls_policies.sql` se borra); aislamiento tenant a nivel aplicación (`WHERE tenant_id`) |
| 10 | Cobertura de tests | **TDD en todo código nuevo** (shared, gateway, controllers/routers) |
| 11 | Ejecución | **Un solo plan en fases** (Fase 0–5), cada fase deja el sistema funcionando |
| 12 | Python | Unificado a **3.12** |
| 13 | Versiones de deps | Las del `requirements.txt` raíz (fin del drift) |

Servicios que quedan: `api-gateway` (nuevo, FastAPI), `auth-service`, `tenant-service`, `users-service`, `files-service`.

---

## Fase 0 — Limpieza inicial

**Eliminar (git rm):**

- `services/cases-service/` (completo)
- `services/news-service/` (completo)
- `Dockerfile` (raíz)
- `entrypoint.sh`
- `Procfile`
- `main.py` (raíz, 656 líneas — su lógica de proxy/media se reimplementa en el gateway, Fase 2)
- `settings.py` (raíz)
- `requirements.txt` (raíz — se reemplaza por pyproject en Fase 1)
- `docker-compose.yml` (raíz — se reescribe en Fase 4)
- `services/api-gateway/traefik.yml` y `services/api-gateway/dynamic.yml` (Traefik se reemplaza por FastAPI)
- `db/rls_policies.sql` y el directorio `db/` (queda vacío)
- `migrations/` (raíz, huérfano: solo tiene `env.py`, sin `alembic.ini` ni `versions/`)
- `services/cases-service/cases_service.log` (ya cubierto por el borrado del servicio)
- `shared/tenant_db/` (código muerto: ningún servicio lo importa)
- `shared/schemas/events.py` viejo (se reescribe en `shared/events/`, Fase 2)

**Referencias a `mailing-service` a eliminar** (el servicio no existe): `MAILING_SERVICE_URL` en `services/cases-service/app/config.py` (desaparece con el borrado), comentarios de celery/resend/jinja2 en requirements (desaparecen con pyproject), cualquier referencia en gateway (desaparece con Traefik/main.py).

**Crear `.gitignore` en raíz:**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.ruff_cache/
dist/
build/

# Env
.env
!.env.example

# Logs
*.log

# Storage local (files-service)
storage/

# uv
.python-version
```

**Nota:** `.python-version` se ignora porque cada servicio fija Python 3.12 en su Dockerfile y pyproject (`requires-python = ">=3.12"`).

---

## Fase 1 — uv + pyproject por microservicio

### Layout de dependencias

Sin workspace de uv (decisión del usuario: despliegue independiente por servicio). Estructura:

```
lead_os/
├── pyproject.toml                 # raíz: SOLO tooling dev (pytest, ruff). Sin app raíz.
├── shared/
│   ├── pyproject.toml             # paquete instalable "lead-os-shared"
│   └── src/shared/...
└── services/<svc>/
    ├── pyproject.toml             # deps del servicio + lead-os-shared (path dep)
    └── uv.lock                    # lock propio por servicio
```

### Versiones unificadas (del requirements.txt raíz, hoy en drift)

Core (todo servicio que use DB/API): `fastapi==0.104.1`, `uvicorn[standard]==0.24.0`, `sqlmodel==0.0.14`, `SQLAlchemy>=2.0,<2.1`, `psycopg2-binary==2.9.11`, `alembic==1.12.1`, `pydantic==2.9.2`, `pydantic-settings==2.12.0`, `redis==5.0.1`, `httpx==0.27.0`, `pyjwt==2.9.0`, `python-jose[cryptography]>=3.4.0`, `cryptography==42.0.5`.

Por servicio (además del core que necesite):
- **auth-service**: `passlib[bcrypt]==1.7.4`, `bcrypt==4.0.1`, `email-validator==2.2.0`, `python-multipart>=0.0.18`, `google-auth==2.23.4`, `google-auth-oauthlib==1.1.0`, `google-auth-httplib2==0.1.1`.
- **users-service**: `google-api-python-client==2.108.0`, `google-auth==2.23.4`, `google-auth-oauthlib==1.1.0`, `google-auth-httplib2==0.1.1`, `googleapis-common-protos>=1.56.2`, `protobuf>=3.19.5`.
- **files-service**: `python-multipart>=0.0.18`, `aiofiles` (streaming; si no está ya en deps transitivas se fija `aiofiles==23.2.1`).
- **tenant-service**: `httpx==0.27.0` (Cloudflare API).
- **api-gateway**: `fastapi`, `uvicorn[standard]`, `httpx==0.27.0`, `pyjwt==2.9.0`, `redis==5.0.1`, `pydantic==2.9.2`, `pydantic-settings==2.12.0` (sin SQLAlchemy/DB).

**Descartadas** (eran del mailing-service inexistente o del monolito): `celery`, `resend`, `jinja2`, `asyncpg` (todos los servicios restantes son sync; asyncpg solo lo usaba cases-service), `python-multipart` solo donde se suben archivos.

Dev (cada servicio, dependency group): `pytest==7.4.3`, `pytest-asyncio==0.21.1`.

### Template de pyproject de servicio

```toml
[project]
name = "auth-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    # ... core + específicas
    "lead-os-shared",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }

[dependency-groups]
dev = ["pytest==7.4.3", "pytest-asyncio==0.21.1"]

[build-system]  # solo si el servicio necesita ser instalable; por defecto NO (app, no librería)
```

Comandos: `cd services/<svc> && uv sync` (crea `.venv` + `uv.lock`), `uv run pytest`, `uv run alembic ...`.

### pyproject raíz

```toml
[project]
name = "lead-os"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []  # sin app raíz

[dependency-groups]
dev = ["pytest==7.4.3", "pytest-asyncio==0.21.1"]
```

---

## Fase 1 (cont.) — Paquete `shared/` instalable

### Estructura

```
shared/
├── pyproject.toml
└── src/shared/
    ├── __init__.py
    ├── config/
    │   ├── __init__.py
    │   └── base.py            # BaseServiceSettings
    ├── db/
    │   ├── __init__.py
    │   ├── engine.py          # create_service_engine(), get_session()
    │   └── readonly.py        # create_readonly_engine(), get_read_session()
    ├── alembic/
    │   ├── __init__.py
    │   └── env_template.py    # run_migrations(get_url, target_metadata)
    ├── auth/
    │   ├── __init__.py
    │   ├── service_token.py   # mint_service_token(), decode_service_token()
    │   ├── middleware.py      # ServiceTokenMiddleware (401 sin token válido)
    │   ├── dependencies.py    # get_current_identity()
    │   └── client.py          # ServiceHttpClient (httpx con firma automática)
    ├── events/
    │   ├── __init__.py
    │   ├── envelope.py        # EventEnvelope (pydantic)
    │   ├── bus.py             # EventBus.publish()
    │   └── consumer.py        # Consumer (consumer groups + DLQ)
    └── utils/
        ├── __init__.py
        ├── logging.py         # setup_logging(service_name)
        └── exceptions.py      # AppError, NotFoundError, ConflictError...
```

### pyproject de shared

```toml
[project]
name = "lead-os-shared"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "sqlmodel==0.0.14",
    "SQLAlchemy>=2.0,<2.1",
    "psycopg2-binary==2.9.11",
    "alembic==1.12.1",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "redis==5.0.1",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/shared"]
```

### API pública de cada módulo (firmas exactas)

**`shared/config/base.py`** — settings base común a todos los servicios:

```python
class BaseServiceSettings(BaseSettings):
    SERVICE_NAME: str
    ENVIRONMENT: str = "local"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DATABASE_URL: str                      # DB propia del servicio
    REDIS_URL: str = "redis://localhost:6379/0"
    INTER_SERVICE_SECRET: str              # firma de service-tokens
    GATEWAY_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

Cada servicio: `class Settings(BaseServiceSettings)` + sus campos propios (`SECRET_KEY`, `FERNET_KEY`, etc. en auth; `CLOUDFLARE_*` en tenant; `STORAGE_PATH` en files).

**`shared/db/engine.py`**:

```python
def create_service_engine(url: str, *, pool_size: int = 5, max_overflow: int = 10,
                          echo: bool = False) -> Engine: ...
def get_session_factory(engine: Engine) -> sessionmaker[Session]: ...
```

**`shared/db/readonly.py`** — para SELECTs cross-servicio (decisión #7):

```python
def create_readonly_engine(url: str) -> Engine: ...   # pool pequeño, sin echo
def get_read_session(engine: Engine) -> Generator[Session, None, None]: ...
```

Uso: un servicio que necesita leer de otro declara en su `Settings` p.ej. `USERS_DATABASE_URL_RO: str | None = None`, crea el engine readonly en lifespan, y lo inyecta en sus services. **Solo SELECT**: el rol DB es read-only (ver Fase 1, init.sql); el código nunca ejecuta writes por esta vía.

**`shared/utils/logging.py`**: `setup_logging(service_name: str, level: str = "INFO") -> None` (formato JSON una línea, incluye `service` en cada registro).

**`shared/utils/exceptions.py`**: `AppError(status_code, detail)`, `NotFoundError`, `ConflictError`, `ForbiddenError` + `app_error_handler` para registrar en FastAPI.

---

## Fase 1 (cont.) — Arquitectura de datos

### Database por servicio

Una instancia Postgres; una database por servicio:

| Servicio | Database | Puerto host (dev) |
|----------|----------|-------------------|
| auth-service | `auth_db` | 5432 (misma instancia) |
| tenant-service | `tenant_db` | " |
| users-service | `users_db` | " |
| files-service | `files_db` | " |

`DATABASE_URL` por servicio apunta a su DB: `postgresql+psycopg2://lead_os:<pass>@postgres:5432/auth_db`.

**Dev:** contenedor `postgres:16-alpine` en compose con script de inicialización `infra/postgres/init.sql` (montado en `/docker-entrypoint-initdb.d/`):

```sql
CREATE ROLE lead_os LOGIN PASSWORD :'password';  -- vía env del contenedor
CREATE DATABASE auth_db OWNER lead_os;
CREATE DATABASE tenant_db OWNER lead_os;
CREATE DATABASE users_db OWNER lead_os;
CREATE DATABASE files_db OWNER lead_os;

CREATE ROLE readonly LOGIN PASSWORD 'readonly_dev_password';
-- Por cada DB (el script se conecta a cada una con \connect):
--   GRANT CONNECT ON DATABASE <db> TO readonly;
--   GRANT USAGE ON SCHEMA public TO readonly;
--   ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;
```

`ALTER DEFAULT PRIVILEGES` garantiza que las tablas creadas después por migraciones sean legibles por `readonly` sin grants manuales. URLs cross-read: `<TARGET>_DATABASE_URL_RO=postgresql+psycopg2://readonly:...@postgres:5432/<target>_db`.

**Prod:** cada servicio recibe su `DATABASE_URL` (Postgres propio, NO Supabase) y los `_RO` que necesite, vía secrets del orquestador. Nada cambia en código.

### Aislamiento tenant

Sin RLS (decisión #9). Todo query multi-tenant filtra `WHERE tenant_id = :tenant_id` en la capa `services/` (el `tenant_id` viene de la identidad inyectada por el gateway). Se mantiene la columna `tenant_id` de los modelos actuales.

### Alembic: patrón centralizado, historial por servicio

**`shared/alembic/env_template.py`** (patrón único):

```python
def run_migrations(get_url: Callable[[], str], target_metadata: MetaData) -> None:
    """env.py estándar: offline+online, compare_type=True, transaction per migration."""
```

**Cada servicio:**

```
services/<svc>/
├── alembic.ini              # script_location = migrations (sin sqlalchemy.url hardcodeada)
└── migrations/
    ├── env.py               # 6 líneas: importa settings + models.metadata, llama run_migrations()
    ├── script.py.mako
    └── versions/            # historial PROPIO del servicio
```

`migrations/env.py` de cada servicio:

```python
from app.config import settings
from app.models import *  # noqa: F401,F403  (registra todos los modelos en metadata)
from sqlmodel import SQLModel
from shared.alembic.env_template import run_migrations

run_migrations(lambda: settings.DATABASE_URL, SQLModel.metadata)
```

**Revisión inicial por servicio:** `uv run alembic revision --autogenerate -m "initial schema"` contra una DB vacía, generada desde los modelos actuales (que hoy se crean con `create_all` o manualmente). Comandos documentados en README: `uv run alembic upgrade head`, `uv run alembic revision --autogenerate -m "..."`.

**Regla:** ningún servicio vuelve a llamar `SQLModel.metadata.create_all()` en lifespan (se elimina de users/files; auth/tenant ya lo tienen como no-op). Las tablas las crean las migraciones.

---

## Fase 2 — Autenticación inter-servicio (enforcement "solo gateway")

### Modelo

1. El **gateway** valida el JWT de usuario del cliente (claves por plataforma, ver §Gateway).
2. El gateway **elimina** cualquier header `X-User-Id`, `X-Tenant-Id`, `X-Role-Id`, `X-Is-Superuser`, `X-Service-Token` que venga del cliente.
3. El gateway **inyecta**: `X-Service-Token: <jwt>` + headers de identidad (`X-User-Id`, `X-Tenant-Id`, `X-Role-Id`, `X-Is-Superuser`) extraídos del JWT validado.
4. Cada servicio corre `ServiceTokenMiddleware`: todo request sin `X-Service-Token` válido → **401**. Excepciones: `/health` (y nada más).
5. Llamadas servicio→servicio directas (sin gateway, p.ej. consumers de eventos que necesitan leer de otro servicio vía HTTP) usan `ServiceHttpClient`, que mintea su propio token.

### Service-token JWT

- Firma: **HS256** con `INTER_SERVICE_SECRET` (env compartido, obligatorio, sin default).
- Claims: `{"iss": "<service_name>", "type": "service", "iat": ..., "exp": iat+60}` — vida de **60 segundos**.
- Validación: firma + `exp` + `type == "service"`. El `iss` solo se loguea.

### API de `shared/auth/`

```python
# service_token.py
def mint_service_token(*, secret: str, issuer: str, ttl_seconds: int = 60) -> str: ...
def decode_service_token(token: str, *, secret: str) -> dict: ...
    # lanza jwt.ExpiredSignatureError / jwt.InvalidTokenError

# middleware.py
class ServiceTokenMiddleware:
    """ASGI puro. Deja pasar EXEMPT_PATHS = {"/health"}. Resto: 401 sin token válido."""
    def __init__(self, app: ASGIApp, *, secret: str, exempt_paths: frozenset[str] = EXEMPT_PATHS): ...

# dependencies.py
@dataclass(frozen=True)
class Identity:
    user_id: int
    tenant_id: int
    role_id: int | None
    is_superuser: bool

def get_current_identity(request: Request) -> Identity:
    """Lee X-User-Id/X-Tenant-Id/X-Role-Id/X-Is-Superuser (seguros: el middleware ya
    validó origen gateway). 401 si faltan en endpoints que la requieran."""

# client.py
class ServiceHttpClient(httpx.Client):
    """httpx.Client que inyecta X-Service-Token fresco en cada request."""
    def __init__(self, *, secret: str, issuer: str, base_url: str = "", timeout: float = 10.0): ...
```

**Nota:** el JWT de usuario actual (HS256, claves por plataforma desk/hub/nest, refresh tokens, etc.) NO cambia en esta fase — los servicios siguen pudiendo decodificarlo si lo necesitan, pero la fuente de verdad de identidad pasa a ser los headers inyectados por el gateway. Los `verify_token`/`_decode_bearer` inline duplicados se reemplazan por `get_current_identity()` en la Fase 3.

---

## Fase 2 (cont.) — Event-driven con Redis Streams

### Modelo

- **Cambios de estado → eventos.** Lecturas simples → SELECT directo a la DB del servicio dueño (rol readonly) o HTTP vía gateway si hace falta lógica.
- Un stream por dominio: `events:<domain>` (p.ej. `events:auth`, `events:users`, `events:tenants`).
- Consumer groups por servicio consumidor: group = nombre del servicio; cada instancia es un consumer (`<service>-<hostname>`).
- **DLQ**: tras `max_deliveries` (default 5) fallos, el mensaje se mueve a `events:<domain>:dlq` y se ACKea en el principal.

### API de `shared/events/`

```python
# envelope.py — contrato Pydantic de todo evento
class EventEnvelope(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str                       # "user.registered", "tenant.created", ...
    aggregate_id: str               # id del recurso afectado
    tenant_id: int | None = None
    payload: dict[str, Any] = {}
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

# bus.py
class EventBus:
    def __init__(self, redis_url: str): ...
    def publish(self, domain: str, event: EventEnvelope) -> str:
        """XADD events:<domain> con el envelope serializado (JSON). Retorna el stream id."""

# consumer.py
EventHandler = Callable[[EventEnvelope], None]  # handler lanza excepción → retry/DLQ

class Consumer:
    def __init__(self, redis_url: str, *, domain: str, group: str,
                 consumer_name: str, handlers: dict[str, EventHandler],
                 max_deliveries: int = 5, block_ms: int = 5000): ...
    def run_forever(self) -> None: ...   # XREADGROUP loop; XAUTOCLAIM para pendientes
    def stop(self) -> None: ...          # shutdown limpio (lifespan)
```

### Uso en servicios

- Productor: `services/` (capa de negocio) recibe el `EventBus` por inyección desde lifespan; publica tras commit de la transacción.
- Consumidor: `app/events.py` define handlers; `main.py` arranca un `Consumer` en un thread de fondo dentro del lifespan (`stop()` en shutdown).

### Cableado de referencia (obligatorio en el plan, prueba el patrón end-to-end)

- **auth-service** publica `user.registered` (domain `auth`) tras registrar un usuario.
- **users-service** consume `user.registered` (group `users-service`) → crea el perfil en `users_db`.

Este es el único flujo de eventos concreto de esta fase (YAGNI); la infraestructura queda lista para añadir más.

---

## Fase 2 (cont.) — API Gateway FastAPI

`services/api-gateway/` es un microservicio más (misma estructura MVC/Facade, sin DB ni alembic).

### Responsabilidades (heredadas del main.py raíz + Traefik)

1. **Reverse proxy** genérico con `httpx.AsyncClient` (pool 150 conexiones, timeout 45s), retry con backoff exponencial (3 intentos, solo GET/HEAD idempotentes, ante 502/503/504 o ConnectError).
2. **Tabla de rutas** por config (env-driven), prefijo → upstream:

```python
SERVICE_ROUTES: dict[str, str] = {
    "/api/auth":    settings.AUTH_SERVICE_URL,     # http://auth-service:8001
    "/api/users":   settings.USERS_SERVICE_URL,    # http://users-service:8003
    "/api/tenants": settings.TENANT_SERVICE_URL,   # http://tenant-service:8002
    "/api/files":   settings.FILES_SERVICE_URL,    # http://files-service:8004
    "/api/saas/webhooks": settings.USERS_SERVICE_URL,  # webhook Aria (contrato externo, ruta pública)
}
```

**Endpoints internos NO se proxifican:** las rutas `/api/internal/*` (p.ej. `/api/internal/tenants/{id}/db-credentials` de tenant-service) no tienen entrada en `SERVICE_ROUTES` — el gateway responde 404/502. Solo son alcanzables servicio↔servicio dentro de la red interna con `ServiceHttpClient`.

**Contrato externo preservado:** el endpoint del webhook de Aria se mantiene exactamente en `/api/saas/webhooks/aria` (lo expone users-service; el gateway lo mapea como ruta pública). Los callers externos no cambian su URL.

3. **Cadena de middleware** (orden): CORS (`*.airedesk.com` regex actual + localhost:3000) → security headers (HSTS, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy) → rate limit (fixed-window en Redis: 100 req/min por IP, 429 al exceder; exempto `/health`) → **auth**: rutas públicas (`/api/auth/login`, `/api/auth/token`, `/api/auth/register`, `/api/auth/google/*`, `/api/auth/password-*`, `/health`, `/media/*`, `/tutorials/*`) pasan directo; el resto valida el JWT de usuario (clave por claim `platform`: `DESK_SECRET_KEY`/`HUB_SECRET_KEY`/`NEST_SECRET_KEY`, fallback `SECRET_KEY`; lógica portada de `auth-service/app/security.py:decode_token`) → strip de headers de identidad del cliente → inyección de service-token + `X-User-Id`, `X-Tenant-Id`, `X-Role-Id`, `X-Is-Superuser`.
4. **Media estática**: `/media/*` y `/tutorials/*` servidos desde `MEDIA_ROOT` con soporte de HTTP Range (portado del main.py raíz).
5. **Health**: `/health` propio; `/health/services` agrega el `/health` de cada upstream (para el README y debugging local).

### Estructura del gateway

```
services/api-gateway/
├── pyproject.toml, uv.lock
├── Dockerfile, Dockerfile.dev
├── app/
│   ├── main.py            # app factory + lifespan (httpx client, redis)
│   ├── config.py          # Settings(BaseServiceSettings): SERVICE_ROUTES urls, claves JWT, MEDIA_ROOT
│   ├── schemas/           # HealthResponse, ServiceHealth, ErrorResponse (pydantic)
│   ├── serializers/       # identity_from_claims() → headers
│   ├── services/          # proxy.py (forward+retry), ratelimit.py, media.py (range responses)
│   ├── utils/             # jwt_keys.py (selección de clave por platform)
│   ├── controller.py      # FACADE: proxy_request(), health(), services_health()
│   └── router.py          # /health, /health/services, /media/{path}, /tutorials/{path}, catch-all proxy
└── tests/
```

El proxy es un **catch-all** `/{full_path:path}` para métodos GET/POST/PUT/PATCH/DELETE que resuelve upstream por prefijo más largo; 502 si el prefijo no mapea o el upstream no responde tras retries.

### Puertos normalizados

| Servicio | Puerto (red interna) | Publicado al host (dev) |
|----------|---------------------|------------------------|
| api-gateway | 8000 | **8000:8000 (único publicado)** |
| auth-service | 8001 | no |
| tenant-service | 8002 | no |
| users-service | 8005→**8003** | no |
| files-service | 8011→**8004** | no |

En dev, para depurar un servicio directo se puede `docker compose exec` o publicar temporalmente editando compose (documentado en README); por defecto nada expone puertos salvo el gateway.

---

## Fase 3 — Restructure MVC + FACADE por servicio

Orden: **auth → tenant → users → files** (auth primero porque define `user.registered` y es el más referenciado). Cada servicio se reestructura de forma independiente y queda funcionando antes de pasar al siguiente.

### Estructura objetivo (estricta, igual en los 4 servicios)

```
services/<svc>/
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── Dockerfile                 # producción
├── Dockerfile.dev             # hot reload
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                # app factory: lifespan (engine, redis, consumer de eventos),
│   │                          #   middlewares (ServiceTokenMiddleware, CORS interno),
│   │                          #   exception handlers, include_router(router), /health
│   ├── config.py              # Settings(BaseServiceSettings) + campos propios
│   ├── models/                # SQLModel: tablas (Modelo del MVC)
│   │   ├── __init__.py        # re-exporta todo para migrations/env.py
│   │   └── ...
│   ├── schemas/               # Pydantic: DTOs request/response = contrato de la API (Vista)
│   ├── serializers/           # model (SQLModel) ↔ schema (Pydantic)
│   ├── services/              # lógica de negocio por dominio; publica eventos; queries con tenant_id
│   ├── utils/                 # helpers específicos del servicio
│   ├── controller.py          # FACADE (Controlador): un método por endpoint; orquesta
│   │                          #   services + serializers; recibe Identity, sesiones DB, EventBus
│   ├── router.py              # ÚNICO APIRouter: declara rutas, parsea/valida request con schemas,
│   │                          #   inyecta dependencias, llama controller.<metodo>(), devuelve schema
│   └── events.py              # handlers de eventos consumidos (si aplica)
└── tests/
    ├── conftest.py            # fixtures: app de test (sin middleware de service-token o con secret de test),
    │                          #   sesión DB sqlite/rollback, identity fake, bus mock
    ├── test_router.py         # tests HTTP del router→controller (contrato)
    └── test_services.py       # tests unitarios de services (lógica)
```

### Reglas del patrón

1. **`router.py` no contiene lógica de negocio**: solo declaración de rutas, dependency injection y llamadas al controller. Un endpoint = una llamada a un método del controller.
2. **`controller.py` es el FACADE**: orquesta uno o varios services, usa serializers para convertir modelos↔schemas, maneja transacciones (commit/rollback) y traduce excepciones de dominio (`AppError`) a respuestas. Los endpoints NO tocan `services/` directamente.
3. **`services/`** contiene toda la lógica de negocio y acceso a datos (queries SQLModel con filtro `tenant_id`). Publica eventos vía `EventBus` inyectado. No conocen FastAPI (nada de `Request`/`Depends`).
4. **`schemas/`** define el contrato: todo request body y response es un modelo Pydantic (`response_model=` siempre). Validaciones de dominio simples (formato, rangos) viven aquí.
5. **`serializers/`**: funciones puras `to_schema(model) -> Schema`, `to_model(schema) -> Model`, `update_model(model, schema) -> Model`. Sin lógica de negocio.
6. **Un solo `router.py` y un solo `controller.py`** por servicio (aunque crezcan: se ordenan con secciones comentadas por dominio). Lo que hoy son routers anidados (`google_routes`, `webhooks`, `calendar_routes`) se fusionan en `router.py` y su lógica pasa a `services/` (p.ej. `services/google_oauth.py`, `services/webhooks.py`, `services/calendar.py`).
7. **Identidad**: los endpoints que requieren auth usan `Depends(get_current_identity)`; el `tenant_id` del filtro de queries sale de `Identity.tenant_id`. Se eliminan los `verify_token`/`get_tenant_db` inline duplicados y los `SET LOCAL app.tenant_id` (RLS eliminado).
8. **`/health`** sin auth en cada servicio.

### Notas por servicio

- **auth-service** (8001): conserva `security.py` → se mueve a `services/security.py` (JWT multi-plataforma, bcrypt, Fernet); Google OAuth → `services/google_oauth.py`; publica `user.registered`. Rutas `/api/auth/*` (incl. `/api/auth/google/*` — el rewrite de Traefik desaparece, las rutas canónicas ya son `/api/auth/google/*`).
- **tenant-service** (8002): Cloudflare custom hostnames → `services/cloudflare.py`. Sus endpoints `/api/internal/tenants/*` (db-credentials, active-ids) pasan a validar service-token (mismo middleware, ya no `require_service_token` inline).
- **users-service** (8003): webhooks Aria (`WEBHOOK_API_KEY`, no JWT) → `services/webhooks.py` + verificación en el endpoint (sigue sin pasar por JWT de usuario; el gateway lo deja pasar como ruta pública `/api/users/webhooks/*`); Google Calendar → `services/calendar.py`. Consume `user.registered` → `app/events.py` crea perfil.
- **files-service** (8004): storage en disco (`STORAGE_PATH`), streaming con Range, límite 500MB → `services/storage.py`. Sin cambios funcionales.

---

## Fase 4 — Docker

### `services/<svc>/Dockerfile` (producción, multi-stage)

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build
COPY shared/ ./shared/
COPY services/<svc>/ ./services/<svc>/
WORKDIR /build/services/<svc>
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /build/services/<svc>/.venv /app/.venv
COPY shared/ /app/shared/
COPY services/<svc>/app /app/app
COPY services/<svc>/alembic.ini services/<svc>/migrations /app/
USER app
EXPOSE <port>
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:<port>/health')" || exit 1
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "<port>"]
```

Reglas: **build context = raíz del repo** (para `COPY shared/`); `uv sync --frozen --no-dev --no-editable` (instala `lead-os-shared` como paquete normal, no editable); usuario no-root; HEALTHCHECK; migraciones se ejecutan como paso de deploy (`uv run alembic upgrade head` o comando one-off del orquestador — documentado en README).

### `services/<svc>/Dockerfile.dev` (desarrollo, hot reload)

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/<svc>/ ./services/<svc>/
WORKDIR /app/services/<svc>
RUN uv sync --frozen
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "<port>", \
     "--reload", "--reload-dir", "/app/services/<svc>/app", "--reload-dir", "/app/shared/src"]
```

En compose se montan volúmenes `./services/<svc>` y `./shared` sobre `/app/...` para que el reload vea los cambios sin rebuild (el `uv sync` del build ya dejó el `.venv`; el volumen no lo pisa porque `.venv` está en `.dockerignore`... **no**: los volúmenes pisan todo el dir, así que compose monta el código y un volumen anónimo protege `.venv`: `- <svc>_venv:/app/services/<svc>/.venv`).

### `.dockerignore` raíz

```
.git
.venv
**/.venv
__pycache__
*.pyc
.pytest_cache
.env
*.log
storage/
docs/
```

---

## Fase 4 (cont.) — docker-compose.yml (raíz, SOLO desarrollo local)

```yaml
name: lead-os

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: lead_os
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-lead_os_dev}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./infra/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U lead_os"], interval: 5s, retries: 10 }
    # sin profiles: siempre corre (lo necesitan todos)

  redis:
    image: redis:7-alpine
    healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, retries: 10 }

  api-gateway:
    build: { context: ., dockerfile: services/api-gateway/Dockerfile.dev }
    env_file: .env
    environment:
      AUTH_SERVICE_URL: http://auth-service:8001
      TENANT_SERVICE_URL: http://tenant-service:8002
      USERS_SERVICE_URL: http://users-service:8003
      FILES_SERVICE_URL: http://files-service:8004
      REDIS_URL: redis://redis:6379/0
    ports: ["8000:8000"]          # ÚNICO puerto publicado
    volumes:
      - ./services/api-gateway:/app/services/api-gateway
      - ./shared:/app/shared
      - gateway_venv:/app/services/api-gateway/.venv
    depends_on: { postgres: {condition: service_healthy}, redis: {condition: service_healthy} }
    # sin profiles: el gateway siempre corre

  auth-service:
    build: { context: ., dockerfile: services/auth-service/Dockerfile.dev }
    profiles: ["auth-service"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://lead_os:${POSTGRES_PASSWORD:-lead_os_dev}@postgres:5432/auth_db
      REDIS_URL: redis://redis:6379/0
      PORT: "8001"
    volumes:
      - ./services/auth-service:/app/services/auth-service
      - ./shared:/app/shared
      - auth_venv:/app/services/auth-service/.venv
    depends_on: { postgres: {condition: service_healthy}, redis: {condition: service_healthy} }
  # ... tenant-service (profile "tenant-service", PORT 8002, tenant_db),
  #     users-service (profile "users-service", PORT 8003, users_db),
  #     files-service (profile "files-service", PORT 8004, files_db + volumen ./storage)

volumes:
  pgdata:
  gateway_venv:
  auth_venv:
  # ... uno por servicio
```

**Exclusión por variable de entorno:** `.env` raíz define `SKIP_SERVICES` (p.ej. `SKIP_SERVICES=files-service,users-service`). Compose no soporta exclusión nativa → el **Makefile** la implementa con profiles: `COMPOSE_PROFILES` = (todos los servicios) − `SKIP_SERVICES`. Postgres, redis y gateway no tienen profile (siempre corren). Servicios en `SKIP_SERVICES` simplemente no levantan; el gateway devolverá 502 en sus rutas (aceptable en dev, se documenta).

## Fase 4 (cont.) — Makefile (raíz, SOLO desarrollo; exactamente 3 comandos: up/down/prune)

```makefile
SHELL := /bin/bash

COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)

ALL_SERVICES := auth-service tenant-service users-service files-service
SKIP_SERVICES ?= $(shell grep -E '^SKIP_SERVICES=' .env 2>/dev/null | cut -d= -f2 | tr ',' ' ')
PROFILES := $(subst $(SPACE),$(COMMA),$(strip $(filter-out $(SKIP_SERVICES),$(ALL_SERVICES))))

.PHONY: up down prune

up:      ## Levanta el stack (todos los servicios menos SKIP_SERVICES)
	COMPOSE_PROFILES=$(PROFILES) docker compose up --build -d
	COMPOSE_PROFILES=$(PROFILES) docker compose ps

down:    ## Apaga todos los contenedores
	docker compose down

prune:   ## Borra contenedores y sus volúmenes (nada más)
	docker compose down -v --remove-orphans
```

Si `SKIP_SERVICES` lista todos, `PROFILES` queda vacío y solo levantan postgres, redis y gateway (servicios sin profile).

## Fase 4 (cont.) — `.env.example` (raíz)

```bash
# Stack
SKIP_SERVICES=
POSTGRES_PASSWORD=lead_os_dev

# Compartidos
INTER_SERVICE_SECRET=dev-inter-service-secret-change-me
REDIS_URL=redis://localhost:6379/0
ENVIRONMENT=local

# JWT de usuarios (mismas claves que hoy)
SECRET_KEY=dev-secret-change-me
DESK_SECRET_KEY=dev-desk-secret
HUB_SECRET_KEY=dev-hub-secret
NEST_SECRET_KEY=dev-nest-secret

# auth-service
FERNET_KEY=
BCRYPT_PEPPER=

# tenant-service (Cloudflare)
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ZONE_ID=
CLOUDFLARE_ACCOUNT_ID=
BASE_DOMAIN=airedesk.com

# users-service
WEBHOOK_API_KEY=
GOOGLE_CREDENTIALS_JSON=

# files-service
STORAGE_PATH=./storage

# gateway
MEDIA_ROOT=./media
FRONTEND_URL=http://localhost:3000
```

---

## Fase 5 — README.md (raíz)

Contenido (único archivo de documentación pedido):

1. **Arquitectura**: diagrama ASCII del flujo `cliente → gateway (8000) → servicios → DBs/Redis/Streams`; qué vive en `shared/`; por qué MVC+Facade; event-driven vs SELECT directo.
2. **Requisitos**: Docker + Docker Compose, uv (para correr sin Docker), make.
3. **Levantar en local**: `cp .env.example .env` → `make up` → gateway en `http://localhost:8000` (`/health/services` para verificar); cómo excluir servicios con `SKIP_SERVICES`; `make down` / `make prune`; correr tests: `cd services/<svc> && uv run pytest`; migraciones: `cd services/<svc> && uv run alembic upgrade head` y cómo generar nuevas (`revision --autogenerate`).
4. **Producción**: build por servicio (`docker build -f services/<svc>/Dockerfile .`), variables de entorno requeridas por servicio (tabla), paso de migraciones en deploy, red interna + gateway como único entrypoint, rotación de `INTER_SERVICE_SECRET` y claves JWT.
5. **Convenciones**: estructura de carpetas, reglas del Facade, cómo publicar/consumir un evento nuevo, cómo añadir un microservicio nuevo (checklist).

---

## Testing (transversal, TDD en código nuevo)

- **Framework**: `pytest==7.4.3` + `pytest-asyncio==0.21.1` por servicio y en `shared/`; `httpx` para clientes de test (ASGITransport).
- **shared/tests/**: unitarios puros — service-token (mint/decode/expirado/firma inválida), middleware (401/200/exempt), envelope (validación pydantic), bus publish/consume/DLQ contra **fakeredis** (`fakeredis==2.20.0` se añade como dev dep), factories de engine contra SQLite en memoria (salvo features PG-only).
- **gateway/tests/**: proxy (upstream mock con respx o ASGI app de test), middleware auth (JWT válido/inválido/expirado/público), rate limit (fakeredis), strip+inyección de headers, health agregado.
- **servicios/tests/**: contrato router→controller (app de test con `INTER_SERVICE_SECRET` de test y dependency overrides para DB), services unitarios (lógica de negocio, tenant filtering), serializers.
- **Regla del plan**: todo paso de implementación sigue test-rojo → implementación → verde → commit. Los servicios reestructurados se validan además con un smoke test de integración en compose (gateway → servicio → DB) ejecutado manualmente al final de cada servicio (documentado en el plan).

## Fuera de alcance (YAGNI explícito)

- Backfill de tests para lógica de negocio heredada (cloudflare, calendar, streaming) — solo tests nuevos.
- Refactor de la lógica interna heredada (se mueve tal cual a `services/`, salvo eliminación de RLS/`SET LOCAL` y duplicados de auth).
- Observabilidad (OpenTelemetry, Prometheus), CI/CD pipelines, despliegue real a un orquestador.
- Más eventos de dominio que `user.registered`.
- Migración de datos desde Supabase (las DBs nuevas arrancan vacías con migraciones).
- Rate limiting avanzado, WAF, mTLS real.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| El restructure MVC de users-service toca webhooks/calendar con lógica delicada | Mover código tal cual primero, tests de contrato antes/después |
| `ALTER DEFAULT PRIVILEGES` no cubre DBs creadas antes del script | init.sql corre en DB vacía del volumen pgdata; `make prune` resetea |
| uv.lock por servicio diverge en versiones compartidas | Versiones pineadas exactas en cada pyproject (del requirements raíz) |
| Gateway como punto único de fallo en dev | `/health/services` + logs estructurados; aceptable en dev |





