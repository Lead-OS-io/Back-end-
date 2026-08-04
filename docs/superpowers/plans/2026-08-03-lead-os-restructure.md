# lead_os Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reestructurar el monorepo lead_os: uv + pyproject por servicio, paquete `shared/` instalable (config, db, alembic, auth inter-servicio, eventos Redis Streams), API gateway FastAPI como único entrypoint, y reestructura MVC+Facade de los 4 microservicios restantes, con Docker por servicio, compose+Makefile para dev y README.

**Architecture:** Monorepo de microservicios FastAPI (Python 3.12). `shared/` es un paquete pip instalable (`lead-os-shared`, hatchling, path dependency editable por servicio). API gateway FastAPI valida JWT de usuario e inyecta service-token JWT (60s, `INTER_SERVICE_SECRET`) + headers de identidad; cada servicio rechaza requests sin service-token válido. Database por servicio en una instancia Postgres (cross-reads con rol `readonly`). Eventos con Redis Streams (un stream por dominio, consumer groups, DLQ). Cada servicio: MVC con `models/`, `schemas/` (Pydantic = contrato API), `serializers/`, `services/`, `utils/`, un solo `controller.py` (FACADE) y un solo `router.py`.

**Tech Stack:** Python 3.12, uv, FastAPI 0.104.1, SQLModel 0.0.14 / SQLAlchemy 2.0 (sync, psycopg2), Alembic 1.12.1, Pydantic 2.9.2, Redis 5.0.1 (cache + Streams), httpx 0.27.0, PyJWT 2.9.0, Docker + docker compose, pytest 7.4.3 + pytest-asyncio 0.21.1 + fakeredis 2.20.0.

**Spec de referencia:** `docs/superpowers/specs/2026-08-03-lead-os-restructure-design.md` (decisiones de diseño; NO reabrir). El repo hoy: ver "Estado actual" en cada Fase.

## Global Constraints

- Versiones EXACTAS (del requirements.txt raíz original): `fastapi==0.104.1`, `uvicorn[standard]==0.24.0`, `sqlmodel==0.0.14`, `SQLAlchemy>=2.0,<2.1`, `psycopg2-binary==2.9.11`, `alembic==1.12.1`, `pydantic==2.9.2`, `pydantic-settings==2.12.0`, `redis==5.0.1`, `httpx==0.27.0`, `pyjwt==2.9.0`, `python-jose[cryptography]>=3.4.0`, `cryptography==42.0.5`, `passlib[bcrypt]==1.7.4`, `bcrypt==4.0.1`, `email-validator==2.2.0`, `python-multipart>=0.0.18`, `google-api-python-client==2.108.0`, `google-auth==2.23.4`, `google-auth-oauthlib==1.1.0`, `google-auth-httplib2==0.1.1`, `googleapis-common-protos>=1.56.2`, `protobuf>=3.19.5`. Dev: `pytest==7.4.3`, `pytest-asyncio==0.21.1`, `fakeredis==2.20.0`.
- Python `>=3.12` en todos los pyproject y Dockerfiles.
- NO usar: celery, resend, jinja2, asyncpg, Traefik. NO workspace de uv. NO Supabase en prod.
- `requires-python = ">=3.12"`, paquete compartido importado como `shared.*` en todo el código.
- Puertos internos: gateway 8000 (único publicado), auth 8001, tenant 8002, users 8003, files 8004.
- Ningún servicio publica puertos al host en compose; solo el gateway (`8000:8000`).
- Todo endpoint nuevo/reestructurado usa `response_model=` con schema Pydantic. TDD: test rojo → implementación → verde → commit, en cada task.
- Commits en español técnico o inglés, formato `tipo: mensaje` (feat/chore/refactor/docs/test).
- Tras cada task: `cd <dir> && uv run pytest -q` debe pasar (o la suite del módulo tocado).

## Convenciones de nombres usadas en todo el plan (type consistency)

- `shared.config.base.BaseServiceSettings(BaseSettings)`
- `shared.db.engine.create_service_engine(url, *, pool_size=5, max_overflow=10, echo=False) -> Engine`
- `shared.db.engine.get_session_factory(engine) -> sessionmaker`
- `shared.db.engine.get_db(request) -> Generator[Session, None, None]` (dependency; lee `request.app.state.session_factory`)
- `shared.db.readonly.create_readonly_engine(url) -> Engine`
- `shared.db.readonly.readonly_dependency(name) -> dependency` (lee `request.app.state.readonly_factories[name]`)
- `shared.alembic.env_template.run_migrations(get_url, target_metadata) -> None`
- `shared.auth.service_token.mint_service_token(*, secret, issuer, ttl_seconds=60) -> str` / `decode_service_token(token, *, secret) -> dict`
- `shared.auth.middleware.ServiceTokenMiddleware(app, *, secret, exempt_paths=frozenset({"/health"}))`
- `shared.auth.dependencies.Identity` (dataclass: `user_id: int`, `tenant_id: int`, `role_id: int | None`, `is_superuser: bool`) / `get_current_identity(request) -> Identity`
- `shared.auth.client.ServiceHttpClient(*, secret, issuer, base_url="", timeout=10.0)` (subclase de `httpx.Client`)
- `shared.events.envelope.EventEnvelope(BaseModel)`
- `shared.events.bus.EventBus(redis_url)` → `.publish(domain: str, event: EventEnvelope) -> str`
- `shared.events.consumer.Consumer(redis_url, *, domain, group, consumer_name, handlers: dict[str, EventHandler], max_deliveries=5, block_ms=5000)` → `.run_forever()`, `.stop()`
- `shared.utils.logging.setup_logging(service_name: str, level: str = "INFO") -> None`
- `shared.utils.exceptions.AppError(status_code, detail)`, `NotFoundError`, `ConflictError`, `ForbiddenError`, `register_exception_handlers(app) -> None`
- Headers de identidad: `X-User-Id`, `X-Tenant-Id`, `X-Role-Id`, `X-Is-Superuser`; header de servicio: `X-Service-Token`.

---

# FASE 0 — Limpieza inicial

**Estado actual:** repo con 6 servicios, gateway Traefik (YAML), proxy FastAPI en `main.py` raíz, `shared/` muerto, `requirements.txt` raíz + por servicio, Dockerfile raíz + por servicio, `docker-compose.yml` raíz, `migrations/` huérfano, `db/rls_policies.sql`.

### Task 1: Borrar código muerto y crear .gitignore

**Files:**
- Delete: `services/cases-service/` (completo), `services/news-service/` (completo), `Dockerfile` (raíz), `entrypoint.sh`, `Procfile`, `main.py` (raíz), `settings.py` (raíz), `docker-compose.yml` (raíz), `services/api-gateway/traefik.yml`, `services/api-gateway/dynamic.yml`, `db/` (completo), `migrations/` (raíz, completo), `shared/tenant_db/`, `shared/schemas/events.py`
- Create: `.gitignore`
- NOT delete yet: `requirements.txt` (raíz ni por servicio — se borran en Task 6 cuando existen los pyproject), `shared/` resto (se reemplaza en Task 2), Dockerfiles por servicio (se reemplazan en Fase 3).

**Interfaces:**
- Consumes: nada.
- Produces: repo sin servicios ni archivos muertos; `cases-service`/`news-service` no deben ser referenciados en ningún archivo restante.

- [ ] **Step 1: Verificar referencias antes de borrar**

Run: `grep -rn "cases-service\|news-service\|mailing-service\|MAILING_SERVICE_URL\|CASES_SERVICE_URL\|NEWS_SERVICE_URL" --include="*.py" --include="*.yml" --include="*.yaml" --include="*.sh" --include="Dockerfile*" --include="*.txt" . | grep -v ".git/"`
Expected: solo referencias en archivos que se borran en esta task (services/cases-service, services/news-service, main.py raíz, docker-compose.yml, dynamic.yml, Dockerfile raíz, requirements.txt raíz). Si aparece alguna referencia en `services/auth-service/`, `services/tenant-service/`, `services/users-service/`, `services/files-service/` o `shared/`: eliminarla del archivo (líneas de config/URLs huérfanas) antes de continuar.

- [ ] **Step 2: Borrar con git**

```bash
git rm -r services/cases-service services/news-service db migrations shared/tenant_db
git rm Dockerfile entrypoint.sh Procfile main.py settings.py docker-compose.yml \
  services/api-gateway/traefik.yml services/api-gateway/dynamic.yml shared/schemas/events.py
```

- [ ] **Step 3: Crear `.gitignore` raíz**

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

- [ ] **Step 4: Verificar que no quedan referencias rotas**

Run: `grep -rn "cases\|news" --include="*.py" services/ shared/ | grep -iv "case_id\|newspaper" || echo OK`
Expected: OK (o solo coincidencias de dominio propio de los servicios restantes, p.ej. nada).

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: eliminar cases-service, news-service, gateway viejo y archivos muertos"
```

---

# FASE 1 — uv + paquete shared + Alembic

**Estado tras Fase 0:** servicios auth/tenant/users/files con estructura plana vieja (`app/config.py`, `app/database.py`, `app/models.py`, `app/schemas.py`, `app/routes.py`, `app/services.py`, `app/redis_client.py`, `app/redis_cache.py`), `requirements.txt` por servicio con drift, `shared/` con código muerto (`auth/`, `schemas/`, `utils/`), sin tests.

**Contexto clave para el implementador:** en esta fase los servicios SIGUEN funcionando con su código viejo; solo migramos gestión de dependencias, construimos `shared/` nuevo y preparamos Alembic. Nadie importa `shared` todavía.

### Task 2: pyproject raíz + esqueleto del paquete shared + utils

**Files:**
- Create: `pyproject.toml` (raíz)
- Delete: `shared/__init__.py`, `shared/auth/`, `shared/schemas/`, `shared/utils/` (contenido viejo completo de `shared/`)
- Create: `shared/pyproject.toml`, `shared/src/shared/__init__.py`, `shared/src/shared/{config,db,alembic,auth,events,utils}/__init__.py`
- Create: `shared/src/shared/utils/logging.py`, `shared/src/shared/utils/exceptions.py`
- Test: `shared/tests/test_utils.py`

**Interfaces:**
- Consumes: nada.
- Produces: `setup_logging(service_name, level="INFO") -> None`; `AppError(status_code: int, detail: str)`, `NotFoundError(detail)` (404), `ConflictError(detail)` (409), `ForbiddenError(detail)` (403), `register_exception_handlers(app) -> None`; paquete `lead-os-shared` instalable.

- [ ] **Step 1: Borrar shared viejo y crear estructura**

```bash
git rm -r shared/__init__.py shared/auth shared/schemas shared/utils
mkdir -p shared/src/shared/{config,db,alembic,auth,events,utils} shared/tests
touch shared/src/shared/__init__.py shared/src/shared/config/__init__.py \
      shared/src/shared/db/__init__.py shared/src/shared/alembic/__init__.py \
      shared/src/shared/auth/__init__.py shared/src/shared/events/__init__.py \
      shared/src/shared/utils/__init__.py shared/tests/__init__.py
```

- [ ] **Step 2: Crear `pyproject.toml` raíz (solo tooling, sin app)**

```toml
[project]
name = "lead-os"
version = "0.1.0"
description = "lead_os monorepo - tooling raíz (sin aplicación)"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
]
```

- [ ] **Step 3: Crear `shared/pyproject.toml`**

```toml
[project]
name = "lead-os-shared"
version = "0.1.0"
description = "Código compartido de los microservicios lead_os"
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

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/shared"]
```

- [ ] **Step 4: Escribir el test que falla — `shared/tests/test_utils.py`**

```python
import logging
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.utils.exceptions import (
    AppError, ConflictError, ForbiddenError, NotFoundError, register_exception_handlers,
)
from shared.utils.logging import setup_logging


def test_setup_logging_configures_root_logger():
    setup_logging("test-service", level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert any("test-service" in (h.formatter._fmt or "") for h in root.handlers)


def test_app_error_maps_to_status_code():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x")
    def x():
        raise NotFoundError("no existe")

    resp = TestClient(app).get("/x")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "no existe"}


def test_error_subclasses_status_codes():
    assert NotFoundError("x").status_code == 404
    assert ConflictError("x").status_code == 409
    assert ForbiddenError("x").status_code == 403
    assert AppError(418, "x").status_code == 418
```

- [ ] **Step 5: Instalar el paquete en modo editable y ver el test fallar**

```bash
cd shared && uv sync
uv run pytest tests/test_utils.py -q
```
Expected: FAIL (`ModuleNotFoundError: No module named 'shared.utils.logging'`). `uv sync` debe crear `shared/uv.lock` y `shared/.venv` instalando `lead-os-shared` editable.

- [ ] **Step 6: Implementar `shared/src/shared/utils/logging.py`**

```python
import logging
import sys


def setup_logging(service_name: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s %(levelname)s [{service_name}] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
```

- [ ] **Step 7: Implementar `shared/src/shared/utils/exceptions.py`**

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "not found"):
        super().__init__(404, detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "conflict"):
        super().__init__(409, detail)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "forbidden"):
        super().__init__(403, detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
```

- [ ] **Step 8: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add pyproject.toml shared/ uv.lock 2>/dev/null || git add pyproject.toml shared/
git commit -m "feat(shared): paquete lead-os-shared instalable + utils (logging, exceptions)"
```
(Nota: `uv.lock` de la raíz se genera con `uv lock` en raíz si se desea `uv sync` raíz; no es obligatorio — el lock raíz solo sirve para tooling. Ejecutar `uv lock` en raíz e incluirlo.)

### Task 3: shared/config — BaseServiceSettings

**Files:**
- Create: `shared/src/shared/config/base.py`
- Test: `shared/tests/test_config.py`

**Interfaces:**
- Consumes: `pydantic-settings`.
- Produces: `BaseServiceSettings` con campos exactos: `SERVICE_NAME: str`, `ENVIRONMENT: str = "local"`, `DEBUG: bool = False`, `PORT: int = 8000`, `HOST: str = "0.0.0.0"`, `DATABASE_URL: str`, `REDIS_URL: str = "redis://localhost:6379/0"`, `INTER_SERVICE_SECRET: str`, `GATEWAY_URL: str = "http://localhost:8000"`; `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_config.py`**

```python
import pytest

from shared.config.base import BaseServiceSettings


class _SvcSettings(BaseServiceSettings):
    MY_OWN_FIELD: str = "default"


def test_reads_env_and_service_fields(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "auth-service")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/auth_db")
    monkeypatch.setenv("INTER_SERVICE_SECRET", "s3cr3t")
    s = _SvcSettings()
    assert s.SERVICE_NAME == "auth-service"
    assert s.PORT == 8000
    assert s.REDIS_URL == "redis://localhost:6379/0"
    assert s.MY_OWN_FIELD == "default"


def test_missing_required_fields_raise(monkeypatch):
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("INTER_SERVICE_SECRET", raising=False)
    monkeypatch.chdir("/tmp")  # lejos de cualquier .env
    with pytest.raises(Exception):
        _SvcSettings(_env_file=None)
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_config.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'shared.config.base'`).

- [ ] **Step 3: Implementar `shared/src/shared/config/base.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    SERVICE_NAME: str
    ENVIRONMENT: str = "local"
    DEBUG: bool = False
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    INTER_SERVICE_SECRET: str
    GATEWAY_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

- [ ] **Step 4: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/config shared/tests/test_config.py
git commit -m "feat(shared): BaseServiceSettings común para todos los servicios"
```

### Task 4: shared/db — engine factories + dependencies

**Files:**
- Create: `shared/src/shared/db/engine.py`, `shared/src/shared/db/readonly.py`
- Test: `shared/tests/test_db.py`

**Interfaces:**
- Consumes: `BaseServiceSettings` (no directamente; recibe URLs).
- Produces: `create_service_engine(url, *, pool_size=5, max_overflow=10, echo=False) -> Engine`; `get_session_factory(engine) -> sessionmaker`; `get_db(request) -> Generator[Session, None, None]`; `create_readonly_engine(url) -> Engine`; `readonly_dependency(name: str) -> Callable[[Request], Generator[Session, None, None]]`.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_db.py`**

```python
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import Field, Session, SQLModel

from shared.db.engine import create_service_engine, get_db, get_session_factory
from shared.db.readonly import create_readonly_engine, readonly_dependency


class _Widget(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


def _make_app(url: str) -> FastAPI:
    app = FastAPI()
    engine = create_service_engine(url)
    SQLModel.metadata.create_all(engine)
    app.state.session_factory = get_session_factory(engine)
    app.state.readonly_factories = {"widgets": get_session_factory(create_readonly_engine(url))}

    @app.post("/widgets")
    def create(name: str, db: Session = Depends(get_db)):
        w = Widget(name=name)
        db.add(w)
        db.commit()
        db.refresh(w)
        return {"id": w.id}

    @app.get("/widgets")
    def list_(db: Session = Depends(readonly_dependency("widgets"))):
        return {"count": len(db.query(Widget).all())}

    return app


def test_engine_session_and_dependencies_roundtrip():
    app = _make_app("sqlite://")
    client = TestClient(app)
    assert client.post("/widgets", params={"name": "a"}).json() == {"id": 1}
    assert client.get("/widgets").json() == {"count": 1}


def test_get_db_requires_factory_on_app_state():
    app = FastAPI()

    @app.get("/x")
    def x(db: Session = Depends(get_db)):
        return {}

    with pytest.raises(AttributeError):
        list(TestClient(app, raise_server_exceptions=True).get("/x").iter_bytes())
```

Nota: el test usa `Widget` importado como `_Widget` solo para evitar warnings de colección de pytest; usar `Widget` como nombre real en el archivo (el alias es ilustrativo — escribir la clase como `Widget` y referenciarla normal).

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_db.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'shared.db.engine'`).

- [ ] **Step 3: Implementar `shared/src/shared/db/engine.py`**

```python
from typing import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, sessionmaker


def create_service_engine(
    url: str, *, pool_size: int = 5, max_overflow: int = 10, echo: bool = False
) -> Engine:
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if not url.startswith("sqlite"):
        # SQLite no acepta pool_size/max_overflow
        kwargs.update(pool_size=pool_size, max_overflow=max_overflow)
    return create_engine(url, **kwargs)


def get_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(class_=Session, bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
```

Añadir al test de la Task 4 (`test_db.py`) este caso extra:

```python
def test_create_service_engine_accepts_sqlite():
    engine = create_service_engine("sqlite://", pool_size=5, max_overflow=10)
    assert engine is not None  # no lanza TypeError por pool args
```

- [ ] **Step 4: Implementar `shared/src/shared/db/readonly.py`**

```python
from typing import Callable, Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import Session, sessionmaker


def create_readonly_engine(url: str) -> Engine:
    return create_engine(url, pool_size=2, max_overflow=3, pool_pre_ping=True)


def readonly_dependency(name: str) -> Callable[[Request], Generator[Session, None, None]]:
    def dep(request: Request) -> Generator[Session, None, None]:
        factories: dict[str, sessionmaker] = request.app.state.readonly_factories
        session: Session = factories[name]()
        try:
            yield session
        finally:
            session.close()

    return dep
```

- [ ] **Step 5: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/db shared/tests/test_db.py
git commit -m "feat(shared): factories de engine/sesión y dependencies get_db/readonly"
```

### Task 5: shared/alembic — env_template

**Files:**
- Create: `shared/src/shared/alembic/env_template.py`
- Test: `shared/tests/test_alembic_env.py`

**Interfaces:**
- Consumes: `alembic`, `sqlmodel.SQLModel.metadata`.
- Produces: `run_migrations(get_url: Callable[[], str], target_metadata: MetaData) -> None` — usado por el `migrations/env.py` de cada servicio (Task 7).

**Contexto:** un `env.py` de Alembic se ejecuta dentro del proceso `alembic`, con `alembic.context` disponible. El template soporta modo offline (`context.is_offline_mode()`) y online, con `compare_type=True`. El test no puede ejecutar migraciones reales sin DB; verifica comportamiento offline generando SQL contra SQLite en memoria vía `alembic command` API… más simple y robusto: test unitario de que `run_migrations` invoca `context.configure` con la URL resuelta y `target_metadata` dados, mockeando `alembic.context`.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_alembic_env.py`**

```python
from unittest.mock import MagicMock, patch

from sqlalchemy import MetaData

from shared.alembic.env_template import run_migrations


def test_run_migrations_offline_configures_url_and_metadata():
    metadata = MetaData()
    fake_context = MagicMock()
    fake_context.is_offline_mode.return_value = True

    with patch("shared.alembic.env_template.context", fake_context):
        run_migrations(lambda: "sqlite:///:memory:", metadata)

    fake_context.configure.assert_called_once()
    kwargs = fake_context.configure.call_args.kwargs
    assert kwargs["url"] == "sqlite:///:memory:"
    assert kwargs["target_metadata"] is metadata
    assert kwargs["compare_type"] is True
    fake_context.run_migrations.assert_called_once()


def test_run_migrations_online_uses_engine_from_url():
    metadata = MetaData()
    fake_context = MagicMock()
    fake_context.is_offline_mode.return_value = False

    with patch("shared.alembic.env_template.context", fake_context):
        run_migrations(lambda: "sqlite:///:memory:", metadata)

    fake_context.configure.assert_called_once()
    kwargs = fake_context.configure.call_args.kwargs
    assert kwargs["target_metadata"] is metadata
    assert kwargs["compare_type"] is True
    assert "connection" in kwargs
    fake_context.run_migrations.assert_called_once()
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_alembic_env.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/alembic/env_template.py`**

```python
from typing import Callable

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool


def run_migrations(get_url: Callable[[], str], target_metadata: MetaData) -> None:
    url = get_url()

    if context.is_offline_mode():
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        {"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()
```

- [ ] **Step 4: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/alembic shared/tests/test_alembic_env.py
git commit -m "feat(shared): env_template de Alembic (patrón único para todos los servicios)"
```

### Task 6: pyproject.toml por servicio + eliminar requirements.txt

**Files:**
- Create: `services/auth-service/pyproject.toml`, `services/tenant-service/pyproject.toml`, `services/users-service/pyproject.toml`, `services/files-service/pyproject.toml`
- Delete: `requirements.txt` (raíz), `services/auth-service/requirements.txt`, `services/tenant-service/requirements.txt`, `services/users-service/requirements.txt`, `services/files-service/requirements.txt`

**Interfaces:**
- Consumes: `lead-os-shared` (path dep `../../shared`).
- Produces: cada servicio con `uv.lock` propio y `.venv` funcional (`uv sync` OK). Los servicios siguen corriendo con su código viejo (`uv run uvicorn main:app`).

**Contexto:** los servicios aún tienen su estructura vieja (entrypoint `main.py` en la raíz del servicio, paquete `app/`). El pyproject NO define build-system (proyecto "virtual": uv solo instala deps, no empaqueta la app).

- [ ] **Step 1: Crear `services/auth-service/pyproject.toml`**

```toml
[project]
name = "auth-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "sqlmodel==0.0.14",
    "SQLAlchemy>=2.0,<2.1",
    "psycopg2-binary==2.9.11",
    "alembic==1.12.1",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "redis==5.0.1",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
    "python-jose[cryptography]>=3.4.0",
    "cryptography==42.0.5",
    "passlib[bcrypt]==1.7.4",
    "bcrypt==4.0.1",
    "email-validator==2.2.0",
    "python-multipart>=0.0.18",
    "google-auth==2.23.4",
    "google-auth-oauthlib==1.1.0",
    "google-auth-httplib2==0.1.1",
    "lead-os-shared",
]

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }
```

- [ ] **Step 2: Crear `services/tenant-service/pyproject.toml`**

```toml
[project]
name = "tenant-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "sqlmodel==0.0.14",
    "SQLAlchemy>=2.0,<2.1",
    "psycopg2-binary==2.9.11",
    "alembic==1.12.1",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "redis==5.0.1",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
    "lead-os-shared",
]

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }
```

- [ ] **Step 3: Crear `services/users-service/pyproject.toml`**

```toml
[project]
name = "users-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "sqlmodel==0.0.14",
    "SQLAlchemy>=2.0,<2.1",
    "psycopg2-binary==2.9.11",
    "alembic==1.12.1",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "redis==5.0.1",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
    "google-api-python-client==2.108.0",
    "google-auth==2.23.4",
    "google-auth-oauthlib==1.1.0",
    "google-auth-httplib2==0.1.1",
    "googleapis-common-protos>=1.56.2",
    "protobuf>=3.19.5",
    "lead-os-shared",
]

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }
```

- [ ] **Step 4: Crear `services/files-service/pyproject.toml`**

```toml
[project]
name = "files-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "sqlmodel==0.0.14",
    "SQLAlchemy>=2.0,<2.1",
    "psycopg2-binary==2.9.11",
    "alembic==1.12.1",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "redis==5.0.1",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
    "python-multipart>=0.0.18",
    "lead-os-shared",
]

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }
```

- [ ] **Step 5: Borrar todos los requirements.txt**

```bash
git rm requirements.txt services/auth-service/requirements.txt \
  services/tenant-service/requirements.txt services/users-service/requirements.txt \
  services/files-service/requirements.txt
```

- [ ] **Step 6: Sync de los 4 servicios y verificación de import**

```bash
for svc in auth-service tenant-service users-service files-service; do
  (cd services/$svc && uv sync && uv run python -c "import fastapi, sqlmodel, shared; print('$svc OK')")
done
```
Expected: los 4 imprimen `OK` y generan `services/<svc>/uv.lock` + `.venv/`. Si `uv sync` falla por conflicto de versiones, NO relajar pines: corregir el pyproject para respetar Global Constraints.

- [ ] **Step 7: Commit**

```bash
git add services/*/pyproject.toml services/*/uv.lock
git commit -m "chore: migrar requirements.txt a pyproject.toml + uv por servicio"
```

### Task 7: Alembic por servicio (patrón shared) + revisiones iniciales

**Files:**
- Create: `infra/postgres/init.sql`
- Create por servicio (×4): `services/<svc>/alembic.ini`, `services/<svc>/migrations/env.py`, `services/<svc>/migrations/script.py.mako`, `services/<svc>/migrations/versions/.gitkeep`
- Create (generado): `services/<svc>/migrations/versions/<rev>_initial_schema.py` por servicio

**Interfaces:**
- Consumes: `shared.alembic.env_template.run_migrations` (Task 5), settings viejos de cada servicio (`app.config.settings.DATABASE_URL`), modelos actuales (`app.models`).
- Produces: historial de migraciones propio por servicio; `infra/postgres/init.sql` reutilizado por compose en Task 33.

**Contexto:** hoy las tablas se crean con `create_all` (users/files) o manualmente. Aquí se genera la revisión inicial autogenerada desde los modelos actuales contra un Postgres desechable. En Fase 3 se eliminarán los `create_all` de los lifespan.

- [ ] **Step 1: Crear `infra/postgres/init.sql`**

```sql
-- Dev local: databases por servicio + rol readonly para cross-reads.
-- Se ejecuta en docker-entrypoint-initdb.d (usuario POSTGRES_USER = lead_os).
CREATE ROLE readonly LOGIN PASSWORD 'readonly_dev_password';

CREATE DATABASE auth_db OWNER lead_os;
CREATE DATABASE tenant_db OWNER lead_os;
CREATE DATABASE users_db OWNER lead_os;
CREATE DATABASE files_db OWNER lead_os;

GRANT CONNECT ON DATABASE auth_db TO readonly;
GRANT CONNECT ON DATABASE tenant_db TO readonly;
GRANT CONNECT ON DATABASE users_db TO readonly;
GRANT CONNECT ON DATABASE files_db TO readonly;

\connect auth_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect tenant_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect users_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

\connect files_db
GRANT USAGE ON SCHEMA public TO readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE lead_os IN SCHEMA public GRANT SELECT ON TABLES TO readonly;
```

- [ ] **Step 2: Crear `alembic.ini` (mismo archivo en los 4 servicios)**

```ini
[alembic]
script_location = migrations
prepend_sys_path = .
file_template = %%(year)d%%(month)02d%%(day)02d_%%(hour)02d%%(minute)02d_%%(rev)s_%%(slug)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 3: Crear `migrations/env.py` (mismo archivo en los 4 servicios)**

```python
from app.config import settings  # noqa: E402
from app.models import *  # noqa: F401,F403,E402  (registra todos los modelos en metadata)
from sqlmodel import SQLModel  # noqa: E402

from shared.alembic.env_template import run_migrations  # noqa: E402

run_migrations(lambda: settings.DATABASE_URL, SQLModel.metadata)
```

- [ ] **Step 4: Crear `migrations/script.py.mako` (mismo archivo en los 4 servicios)**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 5: Levantar Postgres desechable e inicializar DBs**

```bash
docker run -d --name leados-mig \
  -e POSTGRES_USER=lead_os -e POSTGRES_PASSWORD=lead_os_dev \
  -p 55432:5432 postgres:16-alpine
until docker exec leados-mig pg_isready -U lead_os > /dev/null 2>&1; do sleep 1; done
docker cp infra/postgres/init.sql leados-mig:/tmp/init.sql
docker exec leados-mig psql -U lead_os -d postgres -f /tmp/init.sql
```
Expected: CREATE ROLE/DATABASE/GRANT sin errores (4 bases: auth_db, tenant_db, users_db, files_db).

- [ ] **Step 6: Generar revisión inicial por servicio (repetir en los 4)**

Por servicio, primero leer `services/<svc>/app/config.py` y exportar TODAS las variables requeridas (p.ej. auth exige `SECRET_KEY` con validator; usar valores dummy de ≥32 chars). Luego:

```bash
cd services/<svc>
DATABASE_URL="postgresql+psycopg2://lead_os:lead_os_dev@localhost:55432/<db_del_servicio>" \
SECRET_KEY="dev-secret-key-for-migrations-0123456789" \
INTER_SERVICE_SECRET="dev-inter-service" \
uv run alembic revision --autogenerate -m "initial schema"
```
Mapping: auth-service→auth_db, tenant-service→tenant_db, users-service→users_db, files-service→files_db.

Expected: `migrations/versions/YYYYMMDD_HHMM_<rev>_initial_schema.py` creado. Revisar el archivo generado: si contiene FKs hacia tablas de OTRO servicio (tablas no presentes en `app/models.py` de este servicio), eliminar esos `ForeignKeyConstraint`/`ForeignKey` de la revisión Y del modelo (FKs cross-database son inválidas — la integridad cross-servicio es a nivel aplicación/eventos). Anotar cualquier ocurrencia: se resuelve en la Fase 3 del servicio correspondiente.

- [ ] **Step 7: Verificar que las migraciones aplican en una DB limpia (por servicio)**

```bash
docker exec leados-mig psql -U lead_os -d postgres -c "CREATE DATABASE <svc>_verify OWNER lead_os;"
cd services/<svc>
DATABASE_URL="postgresql+psycopg2://lead_os:lead_os_dev@localhost:55432/<svc>_verify" \
SECRET_KEY="dev-secret-key-for-migrations-0123456789" \
INTER_SERVICE_SECRET="dev-inter-service" \
uv run alembic upgrade head
docker exec leados-mig psql -U lead_os -d postgres -c "DROP DATABASE <svc>_verify;"
```
Expected: `Running upgrade -> <rev>, initial schema` sin errores en los 4 servicios.

- [ ] **Step 8: Apagar el Postgres desechable y commit**

```bash
docker rm -f leados-mig
git add infra/ services/*/alembic.ini services/*/migrations/
git commit -m "feat: alembic por servicio con patrón compartido + revisiones iniciales"
```

---

# FASE 2 — Auth inter-servicio, eventos y API Gateway

**Estado tras Fase 1:** `shared/` instalable con config/db/alembic/utils; servicios con pyproject+uv y migraciones iniciales. Aún nadie importa `shared` en runtime; el gateway no existe como código.

### Task 8: shared/auth — service_token (mint/decode)

**Files:**
- Create: `shared/src/shared/auth/service_token.py`
- Test: `shared/tests/test_service_token.py`

**Interfaces:**
- Consumes: `pyjwt`.
- Produces: `mint_service_token(*, secret: str, issuer: str, ttl_seconds: int = 60) -> str`; `decode_service_token(token: str, *, secret: str) -> dict` (lanza `jwt.ExpiredSignatureError`/`jwt.InvalidTokenError`). Claims: `iss`, `type="service"`, `iat`, `exp`.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_service_token.py`**

```python
import time

import jwt
import pytest

from shared.auth.service_token import decode_service_token, mint_service_token

SECRET = "test-inter-service-secret"


def test_mint_and_decode_roundtrip():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    claims = decode_service_token(token, secret=SECRET)
    assert claims["iss"] == "api-gateway"
    assert claims["type"] == "service"
    assert 0 < claims["exp"] - claims["iat"] <= 60


def test_decode_rejects_wrong_secret():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    with pytest.raises(jwt.InvalidTokenError):
        decode_service_token(token, secret="other-secret")


def test_decode_rejects_expired():
    token = mint_service_token(secret=SECRET, issuer="api-gateway", ttl_seconds=-1)
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_service_token(token, secret=SECRET)


def test_decode_rejects_non_service_type():
    token = jwt.encode({"type": "user", "exp": 9999999999}, SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_service_token(token, secret=SECRET)
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_service_token.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/auth/service_token.py`**

```python
from datetime import UTC, datetime, timedelta

import jwt


def mint_service_token(*, secret: str, issuer: str, ttl_seconds: int = 60) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "type": "service",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_service_token(token: str, *, secret: str) -> dict:
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    if claims.get("type") != "service":
        raise jwt.InvalidTokenError("not a service token")
    return claims
```

- [ ] **Step 4: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/auth/service_token.py shared/tests/test_service_token.py
git commit -m "feat(shared): service-token JWT (mint/decode) para auth inter-servicio"
```

### Task 9: shared/auth — ServiceTokenMiddleware + get_current_identity

**Files:**
- Create: `shared/src/shared/auth/middleware.py`, `shared/src/shared/auth/dependencies.py`
- Test: `shared/tests/test_auth_middleware.py`

**Interfaces:**
- Consumes: `mint_service_token`/`decode_service_token` (Task 8), `AppError` (Task 2).
- Produces: `ServiceTokenMiddleware(app, *, secret, exempt_paths=frozenset({"/health"}))` (ASGI puro, 401 JSON sin token válido); `Identity` (dataclass frozen: `user_id: int`, `tenant_id: int`, `role_id: int | None`, `is_superuser: bool`); `get_current_identity(request) -> Identity` (lee headers `X-User-Id`/`X-Tenant-Id`/`X-Role-Id`/`X-Is-Superuser`; 401 vía `AppError` si faltan/malformados).

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_auth_middleware.py`**

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.middleware import ServiceTokenMiddleware
from shared.auth.service_token import mint_service_token
from shared.utils.exceptions import register_exception_handlers

SECRET = "test-inter-service-secret"


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=SECRET)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/me")
    def me(identity: Identity = Depends(get_current_identity)):
        return {"user_id": identity.user_id, "tenant_id": identity.tenant_id,
                "role_id": identity.role_id, "is_superuser": identity.is_superuser}

    return app


def test_health_is_exempt():
    assert TestClient(_make_app()).get("/health").status_code == 200


def test_request_without_service_token_is_401():
    assert TestClient(_make_app()).get("/me").status_code == 401


def test_request_with_invalid_service_token_is_401():
    resp = TestClient(_make_app()).get("/me", headers={"X-Service-Token": "garbage"})
    assert resp.status_code == 401


def test_valid_service_token_passes_and_identity_is_parsed():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    resp = TestClient(_make_app()).get("/me", headers={
        "X-Service-Token": token,
        "X-User-Id": "7",
        "X-Tenant-Id": "42",
        "X-Role-Id": "1",
        "X-Is-Superuser": "true",
    })
    assert resp.status_code == 200
    assert resp.json() == {"user_id": 7, "tenant_id": 42, "role_id": 1, "is_superuser": True}


def test_valid_token_but_missing_identity_headers_is_401():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    resp = TestClient(_make_app()).get("/me", headers={"X-Service-Token": token})
    assert resp.status_code == 401
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_auth_middleware.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/auth/middleware.py`**

```python
import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from shared.auth.service_token import decode_service_token

EXEMPT_PATHS = frozenset({"/health"})


class ServiceTokenMiddleware:
    def __init__(self, app: ASGIApp, *, secret: str,
                 exempt_paths: frozenset[str] = EXEMPT_PATHS):
        self.app = app
        self.secret = secret
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
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

- [ ] **Step 4: Implementar `shared/src/shared/auth/dependencies.py`**

```python
from dataclasses import dataclass

from fastapi import Request

from shared.utils.exceptions import AppError


@dataclass(frozen=True)
class Identity:
    user_id: int
    tenant_id: int
    role_id: int | None
    is_superuser: bool


def get_current_identity(request: Request) -> Identity:
    headers = request.headers
    try:
        role_id_raw = headers.get("x-role-id")
        return Identity(
            user_id=int(headers["x-user-id"]),
            tenant_id=int(headers["x-tenant-id"]),
            role_id=int(role_id_raw) if role_id_raw else None,
            is_superuser=headers.get("x-is-superuser", "").lower() == "true",
        )
    except (KeyError, ValueError):
        raise AppError(401, "missing or malformed identity headers")
```

- [ ] **Step 5: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/auth/middleware.py shared/src/shared/auth/dependencies.py shared/tests/test_auth_middleware.py
git commit -m "feat(shared): ServiceTokenMiddleware + get_current_identity"
```

### Task 10: shared/auth — ServiceHttpClient

**Files:**
- Create: `shared/src/shared/auth/client.py`
- Test: `shared/tests/test_auth_client.py`

**Interfaces:**
- Consumes: `mint_service_token` (Task 8).
- Produces: `ServiceHttpClient(*, secret, issuer, base_url="", timeout=10.0)` — subclase de `httpx.Client` que inyecta `X-Service-Token` fresco en CADA request (preserva headers del caller).

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_auth_client.py`**

```python
import httpx

from shared.auth.client import ServiceHttpClient
from shared.auth.service_token import decode_service_token

SECRET = "test-inter-service-secret"


def _capture_app(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"token": request.headers.get("x-service-token"),
                                     "other": request.headers.get("x-other")})


def test_client_injects_fresh_service_token_on_each_request():
    client = ServiceHttpClient(secret=SECRET, issuer="users-service",
                               transport=httpx.MockTransport(_capture_app))
    r1 = client.get("http://tenant-service:8002/api/internal/tenants/active-ids")
    r2 = client.get("http://tenant-service:8002/api/internal/tenants/active-ids")
    for resp in (r1, r2):
        claims = decode_service_token(resp.json()["token"], secret=SECRET)
        assert claims["iss"] == "users-service"


def test_client_preserves_caller_headers():
    client = ServiceHttpClient(secret=SECRET, issuer="users-service",
                               transport=httpx.MockTransport(_capture_app))
    resp = client.get("http://x/", headers={"X-Other": "keep-me"})
    assert resp.json()["other"] == "keep-me"
```

Nota: `ServiceHttpClient` debe aceptar `**kwargs` extra de `httpx.Client` (como `transport`) y pasarlos a `super().__init__`.

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_auth_client.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/auth/client.py`**

```python
from typing import Any

import httpx

from shared.auth.service_token import mint_service_token


class ServiceHttpClient(httpx.Client):
    def __init__(self, *, secret: str, issuer: str, base_url: str = "",
                 timeout: float = 10.0, **kwargs: Any):
        super().__init__(base_url=base_url, timeout=timeout, **kwargs)
        self._secret = secret
        self._issuer = issuer

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})
        headers["X-Service-Token"] = mint_service_token(
            secret=self._secret, issuer=self._issuer
        )
        return super().request(method, url, headers=headers, **kwargs)
```

- [ ] **Step 4: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/auth/client.py shared/tests/test_auth_client.py
git commit -m "feat(shared): ServiceHttpClient con firma automática service-token"
```

### Task 11: shared/events — EventEnvelope + EventBus (publish)

**Files:**
- Create: `shared/src/shared/events/envelope.py`, `shared/src/shared/events/bus.py`
- Test: `shared/tests/test_events_bus.py`

**Interfaces:**
- Consumes: `redis==5.0.1` (sync), pydantic.
- Produces: `EventEnvelope` (campos exactos: `id: UUID` default uuid4, `type: str`, `aggregate_id: str`, `tenant_id: int | None = None`, `payload: dict = {}`, `occurred_at: datetime` default now UTC, `version: int = 1`); `EventBus(redis_url: str)` con `.publish(domain: str, event: EventEnvelope) -> str` (XADD a stream `events:<domain>`, campo `data` = JSON del envelope; retorna el stream id) y `EventBus.stream_name(domain) -> str` estático.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_events_bus.py`**

```python
import fakeredis
import pytest

from shared.events import bus as bus_module
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus_module.redis.Redis, "from_url", lambda *a, **k: client)
    return client


def test_envelope_defaults():
    e = EventEnvelope(type="user.registered", aggregate_id="123")
    assert e.version == 1
    assert e.tenant_id is None
    assert e.payload == {}
    assert e.id is not None and e.occurred_at is not None


def test_envelope_requires_type_and_aggregate_id():
    with pytest.raises(Exception):
        EventEnvelope()


def test_publish_xadds_envelope_to_domain_stream(fake_redis):
    bus = EventBus("redis://fake:6379/0")
    event = EventEnvelope(type="user.registered", aggregate_id="123",
                          tenant_id=42, payload={"email": "a@b.c"})
    stream_id = bus.publish("auth", event)
    entries = fake_redis.xrange("events:auth")
    assert len(entries) == 1
    assert entries[0][0] == stream_id
    stored = EventEnvelope.model_validate_json(entries[0][1]["data"])
    assert stored == event


def test_stream_name():
    assert EventBus.stream_name("users") == "events:users"
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_events_bus.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/events/envelope.py`**

```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str
    aggregate_id: str
    tenant_id: int | None = None
    payload: dict[str, Any] = {}
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
```

- [ ] **Step 4: Implementar `shared/src/shared/events/bus.py`**

```python
import redis

from shared.events.envelope import EventEnvelope


class EventBus:
    def __init__(self, redis_url: str):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def stream_name(domain: str) -> str:
        return f"events:{domain}"

    def publish(self, domain: str, event: EventEnvelope) -> str:
        return self._redis.xadd(
            self.stream_name(domain), {"data": event.model_dump_json()}
        )
```

- [ ] **Step 5: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/events shared/tests/test_events_bus.py
git commit -m "feat(shared): EventEnvelope (contrato pydantic) + EventBus publish (Redis Streams)"
```

### Task 12: shared/events — Consumer (consumer groups + DLQ)

**Files:**
- Create: `shared/src/shared/events/consumer.py`
- Test: `shared/tests/test_events_consumer.py`

**Interfaces:**
- Consumes: `EventEnvelope`, `EventBus.stream_name`.
- Produces: `EventHandler = Callable[[EventEnvelope], None]`; `Consumer(redis_url, *, domain, group, consumer_name, handlers: dict[str, EventHandler], max_deliveries=5, block_ms=5000)` con `.run_forever()` (loop XREADGROUP; crea el group con MKSTREAM si no existe), `.stop()` (thread-safe), DLQ: tras `max_deliveries` fallos el mensaje va a `events:<domain>:dlq` y se ACKea; tipos sin handler registrado se ACKean sin procesar.

- [ ] **Step 1: Escribir el test que falla — `shared/tests/test_events_consumer.py`**

```python
import threading
import time

import fakeredis
import pytest

from shared.events import bus as bus_module
from shared.events import consumer as consumer_module
from shared.events.bus import EventBus
from shared.events.consumer import Consumer
from shared.events.envelope import EventEnvelope


@pytest.fixture
def fake_redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(bus_module.redis.Redis, "from_url", lambda *a, **k: client)
    monkeypatch.setattr(consumer_module.redis.Redis, "from_url", lambda *a, **k: client)
    return client


def _make_consumer(handlers, max_deliveries=3):
    return Consumer("redis://fake:6379/0", domain="auth", group="users-service",
                    consumer_name="users-1", handlers=handlers,
                    max_deliveries=max_deliveries, block_ms=50)


def _publish_one(fake_redis):
    bus = EventBus("redis://fake:6379/0")
    return bus.publish("auth", EventEnvelope(type="user.registered", aggregate_id="1"))


def test_handler_receives_event_and_acks(fake_redis):
    received = []
    consumer = _make_consumer({"user.registered": received.append})
    consumer._ensure_group()
    msg_id = _publish_one(fake_redis)
    _, fields = fake_redis.xrange("events:auth")[0]
    consumer._handle(msg_id, fields)
    assert len(received) == 1 and received[0].aggregate_id == "1"
    pending = fake_redis.xpending("events:auth", "users-service")
    assert pending["pending"] == 0


def test_unknown_event_type_is_acked_without_handler(fake_redis):
    consumer = _make_consumer({})
    consumer._ensure_group()
    bus = EventBus("redis://fake:6379/0")
    msg_id = bus.publish("auth", EventEnvelope(type="unknown.thing", aggregate_id="9"))
    _, fields = fake_redis.xrange("events:auth")[0]
    consumer._handle(msg_id, fields)
    assert fake_redis.xpending("events:auth", "users-service")["pending"] == 0


def test_failing_message_lands_in_dlq_after_max_deliveries(fake_redis):
    def boom(event):
        raise RuntimeError("handler exploded")

    consumer = _make_consumer({"user.registered": boom}, max_deliveries=3)
    consumer._ensure_group()
    msg_id = _publish_one(fake_redis)
    _, fields = fake_redis.xrange("events:auth")[0]
    for _ in range(3):
        consumer._handle(msg_id, fields)
    dlq = fake_redis.xrange("events:auth:dlq")
    assert len(dlq) == 1
    assert fake_redis.xpending("events:auth", "users-service")["pending"] == 0


def test_run_forever_processes_until_stopped(fake_redis):
    received = []
    consumer = _make_consumer({"user.registered": received.append})
    thread = threading.Thread(target=consumer.run_forever, daemon=True)
    thread.start()
    _publish_one(fake_redis)
    deadline = time.time() + 5
    while not received and time.time() < deadline:
        time.sleep(0.05)
    consumer.stop()
    thread.join(timeout=5)
    assert len(received) == 1
```

- [ ] **Step 2: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_events_consumer.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `shared/src/shared/events/consumer.py`**

```python
import logging
import threading
from typing import Callable

import redis

from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)

EventHandler = Callable[[EventEnvelope], None]


class Consumer:
    def __init__(self, redis_url: str, *, domain: str, group: str, consumer_name: str,
                 handlers: dict[str, EventHandler], max_deliveries: int = 5,
                 block_ms: int = 5000):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.stream = EventBus.stream_name(domain)
        self.dlq_stream = f"{self.stream}:dlq"
        self.deliveries_key = f"{self.stream}:deliveries"
        self.group = group
        self.consumer_name = consumer_name
        self.handlers = handlers
        self.max_deliveries = max_deliveries
        self.block_ms = block_ms
        self._stop_event = threading.Event()

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_forever(self) -> None:
        self._ensure_group()
        while not self._stop_event.is_set():
            entries = self._redis.xreadgroup(
                self.group, self.consumer_name,
                {self.stream: ">"}, count=10, block=self.block_ms,
            )
            for _stream, messages in entries or []:
                for msg_id, fields in messages:
                    self._handle(msg_id, fields)

    def stop(self) -> None:
        self._stop_event.set()

    def _handle(self, msg_id: str, fields: dict) -> None:
        try:
            event = EventEnvelope.model_validate_json(fields["data"])
            handler = self.handlers.get(event.type)
            if handler is None:
                logger.info("no handler for %s, acking", event.type)
                self._redis.xack(self.stream, self.group, msg_id)
                return
            handler(event)
            self._redis.xack(self.stream, self.group, msg_id)
            self._redis.hdel(self.deliveries_key, msg_id)
        except Exception:
            logger.exception("error handling message %s", msg_id)
            deliveries = self._redis.hincrby(self.deliveries_key, msg_id, 1)
            if deliveries >= self.max_deliveries:
                logger.error("message %s to DLQ after %s deliveries", msg_id, deliveries)
                self._redis.xadd(self.dlq_stream, fields)
                self._redis.xack(self.stream, self.group, msg_id)
                self._redis.hdel(self.deliveries_key, msg_id)
```

Nota de diseño: los reintentos los recoge `xautoclaim` en producción vía worker periódico… **simplificación deliberada (YAGNI)**: el redrive de pendientes se hace al reiniciar el consumer (los pendientes del group se reclaman con `xreadgroup` desde `"0"` al arrancar). Para cubrir eso, `run_forever` procesa PRIMERO los pendientes propios antes de leer nuevos: añadir al inicio del loop una pasada con `{self.stream: "0"}` — si devuelve mensajes, se procesan; la siguiente pasada usa `">"`. Ajustar `run_forever`:

```python
    def run_forever(self) -> None:
        self._ensure_group()
        start_id = "0"
        while not self._stop_event.is_set():
            entries = self._redis.xreadgroup(
                self.group, self.consumer_name,
                {self.stream: start_id}, count=10, block=self.block_ms if start_id == ">" else None,
            )
            messages = (entries or [("", [])])[0][1]
            if not messages:
                start_id = ">"
                continue
            for msg_id, fields in messages:
                self._handle(msg_id, fields)
```

- [ ] **Step 4: Verificar verde (ajustar implementación hasta que los 5 tests pasen) y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/events/consumer.py shared/tests/test_events_consumer.py
git commit -m "feat(shared): Consumer con consumer groups, reintentos y DLQ"
```

### Task 13: api-gateway — esqueleto, config, jwt_keys, schemas, serializers

**Files:**
- Create: `services/api-gateway/pyproject.toml`, `services/api-gateway/app/__init__.py`, `services/api-gateway/app/config.py`, `services/api-gateway/app/utils/__init__.py`, `services/api-gateway/app/utils/jwt_keys.py`, `services/api-gateway/app/schemas/__init__.py`, `services/api-gateway/app/schemas/health.py`, `services/api-gateway/app/serializers/__init__.py`, `services/api-gateway/app/serializers/identity.py`
- Create dirs vacíos (se llenan en Task 14-15): `services/api-gateway/app/services/__init__.py`, `services/api-gateway/tests/__init__.py`
- Test: `services/api-gateway/tests/test_jwt_keys.py`, `services/api-gateway/tests/test_serializers.py`

**Interfaces:**
- Consumes: `BaseServiceSettings` (Task 3), `pyjwt`.
- Produces: `Settings(BaseServiceSettings)` con campos extra exactos: `AUTH_SERVICE_URL: str = "http://localhost:8001"`, `TENANT_SERVICE_URL: str = "http://localhost:8002"`, `USERS_SERVICE_URL: str = "http://localhost:8003"`, `FILES_SERVICE_URL: str = "http://localhost:8004"`, `SECRET_KEY: str`, `DESK_SECRET_KEY: str = ""`, `HUB_SECRET_KEY: str = ""`, `NEST_SECRET_KEY: str = ""`, `MEDIA_ROOT: str = "./media"`, `RATE_LIMIT_PER_MINUTE: int = 100`, `FRONTEND_URL: str = "http://localhost:3000"`, y override `DATABASE_URL: str = ""` (gateway sin DB) + property `service_routes: dict[str, str]`; `decode_user_token(token: str, settings: Settings) -> dict`; `IDENTITY_HEADERS: tuple[str, ...]`; `identity_headers_from_claims(claims: dict) -> dict[str, str]`; schemas `HealthResponse(status: str, service: str)`, `ServiceHealth(name: str, url: str, healthy: bool, detail: str | None)`, `ServicesHealthResponse(services: list[ServiceHealth])`.

- [ ] **Step 1: Investigar claims reales del JWT de usuarios (fuente de verdad)**

Leer `services/auth-service/app/security.py`: funciones `create_access_token`/`decode_token`. Anotar: (a) nombres EXACTOS de los claims de identidad (¿`user_id` o `sub`? ¿`tenant_id`? ¿`role_id`? ¿`is_superuser`?), (b) claim `platform` y selección de clave desk/hub/nest/fallback, (c) algoritmo(s). El código de `jwt_keys.py` y `identity.py` de ESTA task debe reflejar lo encontrado; los tests usan esos nombres de claim reales. Si un claim esperado no existe (p.ej. `tenant_id` no se emite), ajustar `identity_headers_from_claims` para omitir ese header y anotarlo en el commit message.

- [ ] **Step 2: Crear `services/api-gateway/pyproject.toml`**

```toml
[project]
name = "api-gateway"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.104.1",
    "uvicorn[standard]==0.24.0",
    "pydantic==2.9.2",
    "pydantic-settings==2.12.0",
    "httpx==0.27.0",
    "pyjwt==2.9.0",
    "redis==5.0.1",
    "lead-os-shared",
]

[dependency-groups]
dev = [
    "pytest==7.4.3",
    "pytest-asyncio==0.21.1",
    "fakeredis==2.20.0",
]

[tool.uv.sources]
lead-os-shared = { path = "../../shared", editable = true }
```

Crear también `services/api-gateway/app/__init__.py` y los `__init__.py` de subpaquetes; luego `cd services/api-gateway && uv sync`.

- [ ] **Step 3: Escribir los tests que fallan**

`tests/test_jwt_keys.py`:

```python
import jwt
import pytest

from app.config import Settings
from app.utils.jwt_keys import decode_user_token


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET="iss",
        SECRET_KEY="fallback-secret",
        DESK_SECRET_KEY="desk-secret",
        HUB_SECRET_KEY="hub-secret",
        NEST_SECRET_KEY="nest-secret",
    )


def _token(claims: dict, key: str) -> str:
    return jwt.encode({**claims, "exp": 9999999999}, key, algorithm="HS256")


def test_decode_selects_platform_key():
    s = _settings()
    token = _token({"platform": "desk", "user_id": 1}, "desk-secret")
    assert decode_user_token(token, s)["user_id"] == 1
    with pytest.raises(jwt.InvalidTokenError):
        decode_user_token(_token({"platform": "desk"}, "wrong-key"), s)


def test_decode_falls_back_to_secret_key():
    s = _settings()
    token = _token({"user_id": 2}, "fallback-secret")
    assert decode_user_token(token, s)["user_id"] == 2


def test_decode_rejects_expired():
    s = _settings()
    token = jwt.encode({"exp": 1}, "fallback-secret", algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_user_token(token, s)
```

`tests/test_serializers.py`:

```python
from app.serializers.identity import IDENTITY_HEADERS, identity_headers_from_claims


def test_identity_headers_from_full_claims():
    headers = identity_headers_from_claims(
        {"user_id": 7, "tenant_id": 42, "role_id": 1, "is_superuser": True}
    )
    assert headers == {
        "X-User-Id": "7",
        "X-Tenant-Id": "42",
        "X-Is-Superuser": "true",
        "X-Role-Id": "1",
    }


def test_identity_headers_minimal_claims():
    headers = identity_headers_from_claims({"user_id": 3, "tenant_id": 5})
    assert headers["X-Is-Superuser"] == "false"
    assert "X-Role-Id" not in headers


def test_identity_headers_tuple_covers_service_token():
    assert "X-Service-Token" in IDENTITY_HEADERS
```

(Ajustar `user_id`/`tenant_id` a los nombres de claim reales encontrados en Step 1.)

- [ ] **Step 4: Verificar fallo**

Run: `cd services/api-gateway && uv run pytest -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.config'`).

- [ ] **Step 5: Implementar `app/config.py`**

```python
from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "api-gateway"
    PORT: int = 8000
    DATABASE_URL: str = ""  # el gateway no tiene DB

    AUTH_SERVICE_URL: str = "http://localhost:8001"
    TENANT_SERVICE_URL: str = "http://localhost:8002"
    USERS_SERVICE_URL: str = "http://localhost:8003"
    FILES_SERVICE_URL: str = "http://localhost:8004"

    SECRET_KEY: str
    DESK_SECRET_KEY: str = ""
    HUB_SECRET_KEY: str = ""
    NEST_SECRET_KEY: str = ""

    MEDIA_ROOT: str = "./media"
    RATE_LIMIT_PER_MINUTE: int = 100
    FRONTEND_URL: str = "http://localhost:3000"

    @property
    def service_routes(self) -> dict[str, str]:
        return {
            "/api/auth": self.AUTH_SERVICE_URL,
            "/api/users": self.USERS_SERVICE_URL,
            "/api/tenants": self.TENANT_SERVICE_URL,
            "/api/files": self.FILES_SERVICE_URL,
            "/api/saas/webhooks": self.USERS_SERVICE_URL,
        }

    @property
    def upstreams(self) -> dict[str, str]:
        return {
            "auth-service": self.AUTH_SERVICE_URL,
            "tenant-service": self.TENANT_SERVICE_URL,
            "users-service": self.USERS_SERVICE_URL,
            "files-service": self.FILES_SERVICE_URL,
        }
```

- [ ] **Step 6: Implementar `app/utils/jwt_keys.py`**

```python
import jwt

from app.config import Settings


def decode_user_token(token: str, settings: Settings) -> dict:
    """Replica la selección de clave por claim `platform` de auth-service/app/security.py."""
    unverified = jwt.decode(token, options={"verify_signature": False})
    platform = unverified.get("platform")
    key = {
        "desk": settings.DESK_SECRET_KEY,
        "hub": settings.HUB_SECRET_KEY,
        "nest": settings.NEST_SECRET_KEY,
    }.get(platform) or settings.SECRET_KEY
    return jwt.decode(token, key, algorithms=["HS256"])
```

(Verificar contra lo encontrado en Step 1: si auth-service usa otros claims/algoritmos, replicar exactamente.)

- [ ] **Step 7: Implementar `app/serializers/identity.py`**

```python
IDENTITY_HEADERS = ("X-User-Id", "X-Tenant-Id", "X-Role-Id", "X-Is-Superuser", "X-Service-Token")


def identity_headers_from_claims(claims: dict) -> dict[str, str]:
    headers = {
        "X-User-Id": str(claims["user_id"]),
        "X-Tenant-Id": str(claims["tenant_id"]),
        "X-Is-Superuser": "true" if claims.get("is_superuser") else "false",
    }
    if claims.get("role_id") is not None:
        headers["X-Role-Id"] = str(claims["role_id"])
    return headers
```

- [ ] **Step 8: Implementar `app/schemas/health.py`**

```python
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ServiceHealth(BaseModel):
    name: str
    url: str
    healthy: bool
    detail: str | None = None


class ServicesHealthResponse(BaseModel):
    services: list[ServiceHealth]
```

- [ ] **Step 9: Verificar verde y commit**

```bash
cd services/api-gateway && uv run pytest -q
git add services/api-gateway/
git commit -m "feat(gateway): esqueleto + config + jwt por plataforma + serializers de identidad"
```

### Task 14: api-gateway — services: proxy, ratelimit, media

**Files:**
- Create: `services/api-gateway/app/services/proxy.py`, `services/api-gateway/app/services/ratelimit.py`, `services/api-gateway/app/services/media.py`
- Test: `services/api-gateway/tests/test_proxy.py`, `services/api-gateway/tests/test_ratelimit.py`, `services/api-gateway/tests/test_media.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient`, `redis.asyncio` (de `redis==5.0.1`).
- Produces: `forward_request(client, request, upstream_base) -> httpx.Response`; `forward_with_retry(client, request, upstream_base, *, attempts=3, backoff=0.25) -> httpx.Response` (retry solo GET/HEAD ante 502/503/504/ConnectError/ConnectTimeout); `is_rate_limited(redis, key: str, limit: int) -> bool` (fixed window por minuto); `file_response_with_range(root: Path, relative: str, request) -> Response` (200 sin Range, 206 con Range `bytes=a-b`, 416 inválido, 404 traversal/inexistente).

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_proxy.py`:

```python
import httpx
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport

from app.services.proxy import forward_request, forward_with_retry


def _scope_request(method: str, path: str, headers: dict, body: bytes = b"") -> Request:
    return Request({
        "type": "http", "method": method, "path": path, "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    })


@pytest.mark.asyncio
async def test_forward_request_strips_hop_by_hop_headers():
    seen = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("GET", "/api/users", {"Host": "gateway", "X-Other": "keep",
                                               "Connection": "close"})
    resp = await forward_request(client, req, "http://users-service:8003")
    assert resp.status_code == 200
    assert seen.get("x-other") == "keep"
    assert "connection" not in {k.lower() for k in seen}


@pytest.mark.asyncio
async def test_retry_on_503_then_success():
    calls = {"n": 0}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("GET", "/api/users", {})
    resp = await forward_with_retry(client, req, "http://users-service:8003", backoff=0)
    assert resp.status_code == 200 and calls["n"] == 3


@pytest.mark.asyncio
async def test_no_retry_on_post():
    calls = {"n": 0}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("POST", "/api/users", {})
    resp = await forward_with_retry(client, req, "http://users-service:8003", backoff=0)
    assert resp.status_code == 503 and calls["n"] == 1
```

`tests/test_ratelimit.py`:

```python
import fakeredis.aioredis
import pytest

from app.services.ratelimit import is_rate_limited


@pytest.mark.asyncio
async def test_allows_up_to_limit_then_blocks():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for _ in range(3):
        assert await is_rate_limited(redis, "1.2.3.4", limit=3) is False
    assert await is_rate_limited(redis, "1.2.3.4", limit=3) is True


@pytest.mark.asyncio
async def test_different_keys_are_independent():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await is_rate_limited(redis, "1.1.1.1", limit=1)
    assert await is_rate_limited(redis, "2.2.2.2", limit=1) is False
```

`tests/test_media.py`:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.services.media import file_response_with_range


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    root.mkdir()
    (root / "hello.txt").write_bytes(b"0123456789")
    return root


@pytest.fixture
def client(media_root: Path) -> TestClient:
    app = FastAPI()

    @app.get("/media/{p:path}")
    def media(p: str, request: Request):
        return file_response_with_range(media_root, p, request)

    return TestClient(app)


def test_full_file_without_range(client):
    resp = client.get("/media/hello.txt")
    assert resp.status_code == 200 and resp.content == b"0123456789"


def test_range_request_returns_206(client):
    resp = client.get("/media/hello.txt", headers={"Range": "bytes=2-5"})
    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["Content-Range"] == "bytes 2-5/10"


def test_suffix_range(client):
    resp = client.get("/media/hello.txt", headers={"Range": "bytes=-3"})
    assert resp.status_code == 206 and resp.content == b"789"


def test_invalid_range_is_416(client):
    assert client.get("/media/hello.txt", headers={"Range": "bytes=50-60"}).status_code == 416


def test_path_traversal_is_404(client):
    assert client.get("/media/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_missing_file_is_404(client):
    assert client.get("/media/nope.txt").status_code == 404
```

- [ ] **Step 2: Verificar fallo**

Run: `cd services/api-gateway && uv run pytest -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.services.proxy'`).

- [ ] **Step 3: Implementar `app/services/proxy.py`**

```python
import asyncio

import httpx
from fastapi import Request

HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
})
_RETRYABLE_STATUS = {502, 503, 504}
_IDEMPOTENT = {"GET", "HEAD"}


async def forward_request(client: httpx.AsyncClient, request: Request,
                          upstream_base: str) -> httpx.Response:
    url = f"{upstream_base}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    body = await request.body()
    return await client.request(request.method, url, headers=headers, content=body)


async def forward_with_retry(client: httpx.AsyncClient, request: Request,
                             upstream_base: str, *, attempts: int = 3,
                             backoff: float = 0.25) -> httpx.Response:
    can_retry = request.method in _IDEMPOTENT
    max_attempts = attempts if can_retry else 1
    for i in range(max_attempts):
        try:
            resp = await forward_request(client, request, upstream_base)
            if resp.status_code not in _RETRYABLE_STATUS or i == max_attempts - 1:
                return resp
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if i == max_attempts - 1:
                raise
        await asyncio.sleep(backoff * (2**i))
    raise RuntimeError("unreachable")  # pragma: no cover
```

- [ ] **Step 4: Implementar `app/services/ratelimit.py`**

```python
import time

import redis.asyncio as aioredis


async def is_rate_limited(redis: aioredis.Redis, key: str, limit: int) -> bool:
    window = int(time.time() // 60)
    redis_key = f"ratelimit:{key}:{window}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, 70)
    return count > limit
```

- [ ] **Step 5: Implementar `app/services/media.py`**

```python
import re
from pathlib import Path
from typing import Iterator

from fastapi import Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

CHUNK_SIZE = 64 * 1024
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def file_response_with_range(root: Path, relative: str, request: Request) -> Response:
    base = root.resolve()
    path = (base / relative).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        return PlainTextResponse("not found", status_code=404)

    range_header = request.headers.get("range")
    match = _RANGE_RE.fullmatch(range_header.strip()) if range_header else None
    if not match:
        return FileResponse(path)

    size = path.stat().st_size
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return PlainTextResponse("invalid range", status_code=416)
    if start_s == "":
        start, end = max(0, size - int(end_s)), size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return PlainTextResponse("range not satisfiable", status_code=416)

    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type="application/octet-stream",
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )
```

- [ ] **Step 6: Verificar verde y commit**

```bash
cd services/api-gateway && uv run pytest -q
git add services/api-gateway/app/services services/api-gateway/tests
git commit -m "feat(gateway): proxy con retry, rate limit (fixed window), media con HTTP Range"
```

### Task 15: api-gateway — middlewares, controller, router, main

**Files:**
- Create: `services/api-gateway/app/utils/middleware.py`, `services/api-gateway/app/controller.py`, `services/api-gateway/app/router.py`, `services/api-gateway/app/main.py`
- Test: `services/api-gateway/tests/test_gateway_app.py`

**Interfaces:**
- Consumes: todo lo de Tasks 13-14 + `mint_service_token` (Task 8), `register_exception_handlers` (Task 2), `setup_logging` (Task 2).
- Produces: `create_app(settings: Settings | None = None, *, http_client=None, redis_client=None) -> FastAPI` (app factory testeable con inyección); middlewares `SecurityHeadersMiddleware`, `RateLimitMiddleware`, `GatewayAuthMiddleware`; controller `proxy_request(request) -> Response`, `health(request) -> HealthResponse`, `services_health(request) -> ServicesHealthResponse`, `media_file(relative, request) -> Response`; `PUBLIC_PATH_PREFIXES: tuple[str, ...]`.

**Reglas del middleware de auth:** rutas públicas = prefijos `("/health", "/api/auth/login", "/api/auth/token", "/api/auth/register", "/api/auth/google", "/api/auth/password", "/api/saas/webhooks", "/media", "/tutorials")`. En rutas NO públicas: extraer `Authorization: Bearer`, decodificar con `decode_user_token`, strip de `IDENTITY_HEADERS` del cliente, inyectar headers de identidad + `X-Service-Token` fresco. En rutas públicas: igualmente strip de `IDENTITY_HEADERS` (el cliente nunca puede inyectarlos) y NO inyectar nada — **excepto** que las rutas públicas proxificadas a servicios (p.ej. `/api/auth/login`) SÍ necesitan `X-Service-Token` (el middleware del servicio lo exige siempre salvo `/health`). Por tanto: en TODA request proxificada se inyecta `X-Service-Token`; los headers de identidad solo cuando hay JWT válido. `/media` y `/tutorials` NO se proxifican (los sirve el gateway localmente) → sin service-token.

- [ ] **Step 1: Escribir el test que falla — `tests/test_gateway_app.py`**

```python
import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from shared.auth.service_token import decode_service_token

SECRET = "user-secret"
ISS = "test-inter-service-secret"


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway", INTER_SERVICE_SECRET=ISS, SECRET_KEY=SECRET,
        REDIS_URL="redis://fake:6379/0", RATE_LIMIT_PER_MINUTE=3,
    )


def _upstream(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "path": request.url.path,
        "service_token": request.headers.get("x-service-token"),
        "user_id": request.headers.get("x-user-id"),
        "tenant_id": request.headers.get("x-tenant-id"),
    })


@pytest.fixture
def client():
    import fakeredis.aioredis
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(_upstream))
    app = create_app(_settings(), http_client=http_client,
                     redis_client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    with TestClient(app) as c:
        yield c


def _user_token() -> str:
    return jwt.encode({"user_id": 7, "tenant_id": 42, "exp": 9999999999},
                      SECRET, algorithm="HS256")


def test_health_is_public_and_has_security_headers(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_private_route_without_jwt_is_401(client):
    assert client.get("/api/users/me").status_code == 401


def test_client_cannot_forge_identity_headers(client):
    resp = client.get("/api/users/me", headers={
        "Authorization": f"Bearer {_user_token()}",
        "X-User-Id": "999", "X-Tenant-Id": "999",
    })
    body = resp.json()
    assert resp.status_code == 200
    assert body["user_id"] == "7" and body["tenant_id"] == "42"


def test_gateway_injects_service_token_and_identity(client):
    resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {_user_token()}"})
    body = resp.json()
    claims = decode_service_token(body["service_token"], secret=ISS)
    assert claims["iss"] == "api-gateway"
    assert body["user_id"] == "7"


def test_public_auth_route_proxied_with_service_token_but_no_identity(client):
    resp = client.post("/api/auth/login")
    body = resp.json()
    assert resp.status_code == 200
    decode_service_token(body["service_token"], secret=ISS)
    assert body["user_id"] is None


def test_rate_limit_returns_429_after_limit(client):
    # fixture por función = fakeredis limpio; límite = 3 (settings de test)
    for _ in range(3):
        assert client.post("/api/auth/login").status_code == 200
    assert client.post("/api/auth/login").status_code == 429


def test_unknown_prefix_returns_502(client):
    resp = client.get("/api/unknown/thing",
                      headers={"Authorization": f"Bearer {_user_token()}"})
    assert resp.status_code == 502
```

Nota para el implementador: si el test de rate limit interfiere con otros tests (mismo fakeredis compartido por fixture de función, está aislado), mantener el límite en 3 vía settings. Ajustar el test `test_rate_limit_returns_429_after_limit` para que NO dependa del conteo de otros tests (fixture por función = redis limpio en cada test).

- [ ] **Step 2: Verificar fallo**

Run: `cd services/api-gateway && uv run pytest -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.main'`).

- [ ] **Step 3: Implementar `app/utils/middleware.py`**

```python
import jwt
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.serializers.identity import IDENTITY_HEADERS, identity_headers_from_claims
from app.services.ratelimit import is_rate_limited
from app.utils.jwt_keys import decode_user_token
from shared.auth.service_token import mint_service_token

SECURITY_HEADERS = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/api/auth/login",
    "/api/auth/token",
    "/api/auth/register",
    "/api/auth/google",
    "/api/auth/password",
    "/api/saas/webhooks",
    "/media",
    "/tutorials",
)

_STRIP = tuple(h.lower() for h in IDENTITY_HEADERS)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Lee el redis de scope["app"].state.redis en runtime (los middlewares se
    configuran ANTES de que el lifespan pueble app.state)."""

    def __init__(self, app: ASGIApp, *, limit: int,
                 exempt_prefixes: tuple[str, ...] = ("/health",)):
        self.app = app
        self.limit = limit
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(self.exempt_prefixes):
            await self.app(scope, receive, send)
            return
        redis_client = scope["app"].state.redis
        client_host = scope.get("client", ("unknown", 0))[0]
        if await is_rate_limited(redis_client, client_host, self.limit):
            response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class GatewayAuthMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        for name in _STRIP:
            if name in headers:
                del headers[name]

        path = scope["path"]
        served_locally = path.startswith(("/media", "/tutorials", "/health"))
        if not served_locally:
            headers["X-Service-Token"] = mint_service_token(
                secret=self.settings.INTER_SERVICE_SECRET, issuer="api-gateway"
            )

        if path.startswith(PUBLIC_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            await JSONResponse({"detail": "missing bearer token"}, status_code=401)(scope, receive, send)
            return
        try:
            claims = decode_user_token(auth.removeprefix("Bearer ").strip(), self.settings)
        except jwt.InvalidTokenError:
            await JSONResponse({"detail": "invalid token"}, status_code=401)(scope, receive, send)
            return

        for key, value in identity_headers_from_claims(claims).items():
            headers[key] = value
        await self.app(scope, receive, send)
```

- [ ] **Step 4: Implementar `app/controller.py`**

```python
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import Response

from app.config import Settings
from app.schemas.health import HealthResponse, ServiceHealth, ServicesHealthResponse
from app.services.media import file_response_with_range
from app.services.proxy import forward_with_retry
from shared.utils.exceptions import AppError

_HOP_BY_HOP_RESP = {"content-encoding", "transfer-encoding", "connection"}


def _resolve_upstream(settings: Settings, path: str) -> str | None:
    routes = settings.service_routes
    matches = [p for p in routes if path == p or path.startswith(p + "/")]
    if not matches:
        return None
    return routes[max(matches, key=len)]


async def proxy_request(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    upstream = _resolve_upstream(settings, request.url.path)
    if upstream is None:
        raise AppError(502, f"no upstream configured for {request.url.path}")
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        upstream_resp = await forward_with_retry(client, request, upstream)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise AppError(502, "upstream unavailable")
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers={k: v for k, v in upstream_resp.headers.items()
                 if k.lower() not in _HOP_BY_HOP_RESP},
    )


async def health(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", service=request.app.state.settings.SERVICE_NAME)


async def services_health(request: Request) -> ServicesHealthResponse:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    results: list[ServiceHealth] = []
    for name, url in settings.upstreams.items():
        try:
            resp = await client.get(f"{url}/health", timeout=3.0)
            results.append(ServiceHealth(name=name, url=url,
                                         healthy=resp.status_code == 200,
                                         detail=None if resp.status_code == 200 else f"status {resp.status_code}"))
        except httpx.HTTPError as exc:
            results.append(ServiceHealth(name=name, url=url, healthy=False, detail=str(exc)))
    return ServicesHealthResponse(services=results)


def media_file(relative: str, request: Request) -> Response:
    root = Path(request.app.state.settings.MEDIA_ROOT)
    return file_response_with_range(root, relative, request)
```

- [ ] **Step 5: Implementar `app/router.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import controller
from app.schemas.health import HealthResponse, ServicesHealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return await controller.health(request)


@router.get("/health/services", response_model=ServicesHealthResponse)
async def services_health(request: Request) -> ServicesHealthResponse:
    return await controller.services_health(request)


@router.get("/media/{file_path:path}")
async def media(file_path: str, request: Request) -> Response:
    return controller.media_file(file_path, request)


@router.get("/tutorials/{file_path:path}")
async def tutorials(file_path: str, request: Request) -> Response:
    return controller.media_file(f"tutorials/{file_path}", request)


@router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(request: Request) -> Response:
    return await controller.proxy_request(request)
```

- [ ] **Step 6: Implementar `app/main.py`**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.router import router
from app.utils.middleware import (
    GatewayAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware,
)
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None, *,
               http_client: httpx.AsyncClient | None = None,
               redis_client=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.http_client = http_client or httpx.AsyncClient(
            limits=httpx.Limits(max_connections=150), timeout=httpx.Timeout(45.0)
        )
        app.state.redis = redis_client or aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        yield
        await app.state.http_client.aclose()
        await app.state.redis.aclose()

    app = FastAPI(title="lead-os api-gateway", lifespan=lifespan)
    register_exception_handlers(app)

    app.add_middleware(GatewayAuthMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, limit=settings.RATE_LIMIT_PER_MINUTE)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
        allow_origin_regex=r"https://.*\.airedesk\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 7: Verificar verde (toda la suite del gateway) y commit**

```bash
cd services/api-gateway && uv run pytest -q
git add services/api-gateway/
git commit -m "feat(gateway): middlewares, controller facade, router y app factory"
```

### Task 16: api-gateway — Dockerfile (prod) + Dockerfile.dev + .dockerignore

**Files:**
- Create: `services/api-gateway/Dockerfile`, `services/api-gateway/Dockerfile.dev`, `.dockerignore` (raíz)

**Interfaces:**
- Consumes: `uv.lock` del gateway (Task 13), paquete `shared/`.
- Produces: imágenes `lead-os/api-gateway` (prod) y dev con hot reload. **Build context = raíz del repo** (necesita `shared/`).

- [ ] **Step 1: Crear `.dockerignore` raíz**

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

- [ ] **Step 2: Crear `services/api-gateway/Dockerfile` (producción, multi-stage)**

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build
COPY shared/ ./shared/
COPY services/api-gateway/ ./services/api-gateway/
WORKDIR /build/services/api-gateway
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /build/services/api-gateway/.venv /app/.venv
COPY services/api-gateway/app /app/app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Nota: con `--no-editable`, `lead-os-shared` se instala como wheel dentro del `.venv` → no hace falta copiar `shared/` en runtime.

- [ ] **Step 3: Crear `services/api-gateway/Dockerfile.dev` (hot reload)**

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/api-gateway/ ./services/api-gateway/
WORKDIR /app/services/api-gateway
RUN uv sync --frozen
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/app/services/api-gateway/app", "--reload-dir", "/app/shared/src"]
```

Los paths `/app/shared` y `/app/services/api-gateway` son los que compose montará como volúmenes (Task 33), manteniendo válido el `.pth` editable del venv.

- [ ] **Step 4: Verificar build de producción**

```bash
docker build -f services/api-gateway/Dockerfile -t lead-os-gateway:test .
docker run --rm -d --name gw-test \
  -e INTER_SERVICE_SECRET=test -e SECRET_KEY=test-secret \
  -p 18000:8000 lead-os-gateway:test
sleep 3 && curl -sf http://localhost:18000/health
docker rm -f gw-test
```
Expected: build OK y `{"status":"ok","service":"api-gateway"}`.

- [ ] **Step 5: Commit**

```bash
git add services/api-gateway/Dockerfile services/api-gateway/Dockerfile.dev .dockerignore
git commit -m "feat(gateway): Dockerfile prod (multi-stage uv) + Dockerfile.dev (hot reload)"
```

---

# FASE 3 — Restructure MVC + FACADE por servicio

**Estado tras Fase 2:** `shared/` completo (config, db, alembic, auth, events, cache NO aún), gateway funcional con Dockerfiles. Los 4 servicios siguen con estructura plana vieja.

**Orden estricto:** auth (T18–T21) → tenant (T22–T25) → users (T26–T29) → files (T30–T33). Cada servicio sigue 4 tasks: **S1** tests de contrato (rojos) + conftest, **S2** config/main/models (infra), **S3** extracción services + controller facade + router único, **S4** eventos + Dockerfiles + verde completo.

**Patrón uniforme de tests de servicio (S1):** los contract tests usan `TestClient` contra `app.main.create_app()` con: (a) env de test vía `os.environ.setdefault` ANTES de importar `app.*`; (b) `dependency_overrides` para `get_db` (sesión `MagicMock`) y `get_current_identity` (Identity fake); (c) header `X-Service-Token` minteado con el `INTER_SERVICE_SECRET` de test (el middleware global lo exige); (d) monkeypatch de funciones de `app.services.*` según el endpoint. Tests de `services/`: lógica pura con sesiones mock. NO se testea contra Postgres real (el smoke de integración es Fase 4).

**Reglas de extracción (S3, todos los servicios):**
1. `router.py` único: declara rutas con `response_model=`, inyecta deps, UNA llamada a `controller.<metodo>()` por endpoint. Sin lógica.
2. `controller.py`: orquesta `services/`, usa `serializers/`, maneja commit/rollback, traduce excepciones a `AppError`. Recibe `Identity`, `Session`, `Settings`, `EventBus` como parámetros (no lee `Request`).
3. `services/`: toda la lógica y queries. **Todo query sobre tabla con `tenant_id` filtra explícitamente** `Model.tenant_id == identity.tenant_id` (RLS eliminado — antes filtraba Postgres). No importan FastAPI.
4. `schemas/`: todo request/response es Pydantic. `serializers/`: conversiones puras model↔schema.
5. Se eliminan: `app/routes.py`, `app/services.py`, `app/schemas.py`, `app/database.py`, `app/redis_client.py`, `app/redis_cache.py` (suplantados), y los deps inline `verify_token`/`get_tenant_id`/`get_tenant_db`/`_decode_bearer` (suplantados por `get_current_identity`). Se eliminan los `SET LOCAL app.tenant_id` y cualquier `create_all`.
6. CORS sale del servicio (lo maneja el gateway; el servicio nunca recibe tráfico directo de browser).
7. Auditoría cross-DB: `grep -rn "import\|from" app/models/ app/services/ | grep -i "user\|tenant\|file"` buscando referencias a tablas de OTRO servicio. Si existen, se resuelven con `readonly_dependency("<target>")` + `<TARGET>_DATABASE_URL_RO` en Settings, o vía evento. Documentar cada caso en el commit.

### Task 17: shared/cache + require_admin (centralizar redis client + @cached)

**Files:**
- Create: `shared/src/shared/cache/__init__.py`, `shared/src/shared/cache/client.py`, `shared/src/shared/cache/decorator.py`
- Modify: `shared/src/shared/auth/dependencies.py` (añadir `require_admin`)
- Test: `shared/tests/test_cache.py`, `shared/tests/test_require_admin.py`

**Interfaces:**
- Consumes: `redis==5.0.1`, `Identity` (Task 9), `ForbiddenError` (Task 2).
- Produces: `create_redis(url: str) -> redis.Redis` (decode_responses=True); `cached(*, prefix: str, ttl: int = 300, key_parts: tuple[str, ...] = ())` (decorador que cachea el retorno JSON-serializable de la función en `ariadesk:shared:{prefix}:{key_parts...}` usando un cliente redis que recibe como primer argumento keyword `redis_client`); `invalidate_pattern(redis_client, pattern: str) -> int` (SCAN+DELETE, retorna cuántas claves borró); `require_admin(identity: Identity) -> Identity` (lanza `ForbiddenError` si no `is_superuser` y `role_id != 1`; si ok retorna el identity).

- [ ] **Step 1: Investigar las copias actuales**

Run: `cat services/auth-service/app/redis_client.py services/auth-service/app/redis_cache.py services/users-service/app/redis_cache.py`
Anotar la API actual del decorador `@cached` (nombre de args, prefijos como `ariadesk:shared:u:{uid}:*`) y de `_invalidate_shared_cache_safe()`. La implementación nueva debe ser compatible con los call sites que queden en users/tenant (se migran en sus tasks S3). Si la API actual difiere de la diseñada arriba, prevalece la diseñada y los call sites se adaptan en S3.

- [ ] **Step 2: Escribir los tests que fallan**

`shared/tests/test_cache.py`:

```python
import fakeredis

from shared.cache.decorator import cached, invalidate_pattern


def _redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_cached_stores_and_reuses_result():
    calls = {"n": 0}

    @cached(prefix="widgets", ttl=60)
    def expensive(*, redis_client, tenant_id: int):
        calls["n"] += 1
        return {"value": calls["n"]}

    r = _redis()
    assert expensive(redis_client=r, tenant_id=1) == {"value": 1}
    assert expensive(redis_client=r, tenant_id=1) == {"value": 1}
    assert calls["n"] == 1
    assert expensive(redis_client=r, tenant_id=2) == {"value": 2}


def test_invalidate_pattern_deletes_matching_keys():
    r = _redis()
    r.set("ariadesk:shared:widgets:1", "x")
    r.set("ariadesk:shared:widgets:2", "y")
    r.set("ariadesk:shared:other:1", "z")
    deleted = invalidate_pattern(r, "ariadesk:shared:widgets:*")
    assert deleted == 2
    assert r.get("ariadesk:shared:other:1") == "z"
```

`shared/tests/test_require_admin.py`:

```python
import pytest

from shared.auth.dependencies import Identity, require_admin
from shared.utils.exceptions import ForbiddenError


def test_superuser_passes():
    assert require_admin(Identity(1, 1, None, True)).is_superuser


def test_role_id_1_passes():
    assert require_admin(Identity(2, 1, 1, False)).role_id == 1


def test_regular_user_rejected():
    with pytest.raises(ForbiddenError):
        require_admin(Identity(3, 1, 2, False))
```

- [ ] **Step 3: Verificar fallo**

Run: `cd shared && uv run pytest tests/test_cache.py tests/test_require_admin.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'shared.cache'`, `ImportError: cannot import name 'require_admin'`).

- [ ] **Step 4: Implementar `shared/src/shared/cache/client.py`**

```python
import redis


def create_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)
```

- [ ] **Step 5: Implementar `shared/src/shared/cache/decorator.py`**

```python
import functools
import json

import redis


def _build_key(prefix: str, key_parts: tuple[str, ...], kwargs: dict) -> str:
    parts = [str(kwargs[p]) for p in key_parts]
    suffix = ":".join(parts)
    return f"ariadesk:shared:{prefix}:{suffix}" if suffix else f"ariadesk:shared:{prefix}"


def cached(*, prefix: str, ttl: int = 300, key_parts: tuple[str, ...] = ()):
    """Cachea el retorno (JSON-serializable) en redis. La función decorada debe
    aceptar kwarg `redis_client` y los kwargs nombrados en key_parts."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            redis_client = kwargs.get("redis_client")
            if redis_client is None:
                return func(*args, **kwargs)
            key = _build_key(prefix, key_parts, kwargs)
            hit = redis_client.get(key)
            if hit is not None:
                return json.loads(hit)
            result = func(*args, **kwargs)
            redis_client.setex(key, ttl, json.dumps(result, default=str))
            return result

        return wrapper

    return decorator


def invalidate_pattern(redis_client: redis.Redis, pattern: str) -> int:
    deleted = 0
    for key in redis_client.scan_iter(match=pattern, count=500):
        redis_client.delete(key)
        deleted += 1
    return deleted
```

- [ ] **Step 6: Añadir `require_admin` a `shared/src/shared/auth/dependencies.py`**

```python
def require_admin(identity: Identity) -> Identity:
    if not identity.is_superuser and identity.role_id != 1:
        raise ForbiddenError("admin required")
    return identity
```

(añadir el import de `ForbiddenError` desde `shared.utils.exceptions`).

- [ ] **Step 7: Verificar verde y commit**

```bash
cd shared && uv run pytest -q
git add shared/src/shared/cache shared/src/shared/auth/dependencies.py shared/tests
git commit -m "feat(shared): cache centralizada (cached/invalidate_pattern) + require_admin"
```

### Task 18 (auth S1): tests de contrato + conftest

**Files:**
- Create: `services/auth-service/tests/__init__.py`, `services/auth-service/tests/conftest.py`, `services/auth-service/tests/test_router_contract.py`
- Modify: ninguno (la app vieja sigue intacta; los tests fallan porque `app.main:create_app` no existe aún)

**Interfaces:**
- Consumes: estructura actual de `services/auth-service/app/` (routes.py, google_routes.py).
- Produces: suite de contrato que define el comportamiento esperado del router nuevo; fixtures `client`, `svc_headers`, `identity`, `mock_db` reusables en todo el servicio.

- [ ] **Step 1: Inventario de endpoints (fuente de verdad del contrato)**

Run: `grep -n "@router\.\|@google_router\." services/auth-service/app/routes.py services/auth-service/app/google_routes.py`
Listar método+path de cada endpoint (hoy bajo prefijos `/api/auth` y `/api/auth/google`). Para cada uno, anotar: ¿requiere auth? ¿schema de respuesta? Los tests de Step 3 cubren TODOS los endpoints listados (al menos: status esperado + shape de respuesta con servicios mockeados).

- [ ] **Step 2: Escribir `services/auth-service/tests/conftest.py`**

```python
import os
from unittest.mock import MagicMock

os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://x:x@localhost:5432/x")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from fastapi.testclient import TestClient

from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.db.engine import get_db

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def identity() -> Identity:
    return Identity(user_id=1, tenant_id=1, role_id=1, is_superuser=True)


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


@pytest.fixture
def client(identity, mock_db, monkeypatch):
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: fakeredis.FakeRedis(decode_responses=True))
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_identity] = lambda: identity
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 3: Escribir `tests/test_router_contract.py` (rojo) — patrón + endpoints críticos**

Patrón por endpoint (ejemplo con login y register; replicar para CADA endpoint del inventario de Step 1):

```python
from unittest.mock import MagicMock


def test_login_returns_tokens(client, svc_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.login_user",
        lambda **kwargs: {"access_token": "a", "refresh_token": "r", "token_type": "bearer"},
    )
    resp = client.post("/api/auth/login",
                       data={"username": "u@x.com", "password": "pw"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"


def test_login_wrong_credentials_is_401(client, svc_headers, monkeypatch):
    from shared.utils.exceptions import AppError

    def boom(**kwargs):
        raise AppError(401, "invalid credentials")

    monkeypatch.setattr("app.services.auth.login_user", boom)
    resp = client.post("/api/auth/login",
                       data={"username": "u@x.com", "password": "bad"}, headers=svc_headers)
    assert resp.status_code == 401


def test_register_returns_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.register_user",
        lambda **kwargs: MagicMock(id=1, email="u@x.com", tenant_id=1),
    )
    resp = client.post("/api/auth/register",
                       json={"email": "u@x.com", "password": "Pw123456", "full_name": "U"},
                       headers=svc_headers)
    assert resp.status_code == 201
    assert resp.json()["email"] == "u@x.com"


def test_refresh_requires_body(client, svc_headers):
    resp = client.post("/api/auth/refresh", json={}, headers=svc_headers)
    assert resp.status_code == 422


def test_missing_service_token_is_401(client):
    assert client.post("/api/auth/login", data={"username": "a", "password": "b"}).status_code == 401


def test_health_ok(client):
    assert client.get("/health").status_code == 200
```

Ajustar paths/payloads/schemas a lo encontrado en Step 1 (p.ej. si login es `/token` con OAuth2 form, testear ambos `/token` y `/login` si existen). Los nombres `app.services.auth.login_user`/`register_user` son los que Task 20 creará — son CONTRATO de esta task.

- [ ] **Step 4: Verificar que la suite está en ROJO**

Run: `cd services/auth-service && uv run pytest tests/ -q`
Expected: FAIL en collection (`ModuleNotFoundError: No module named 'app.main'` o `create_app`). NO commit (los tests entran al repo en Task 19-20 junto con el código que los pone en verde… **corrección TDD**: commitear tests rojos junto con S2/S3 en sus commits; está bien que queden rojos entre Task 18 y 20 en working tree).

### Task 19 (auth S2): config, models package, main.py nuevo

**Files:**
- Modify: `services/auth-service/app/config.py` (reescritura)
- Create: `services/auth-service/app/models/__init__.py`, `services/auth-service/app/models/user.py`, `services/auth-service/app/models/tokens.py`, `services/auth-service/app/models/google.py`
- Delete: `services/auth-service/app/models.py`, `services/auth-service/app/database.py`
- Modify: `services/auth-service/main.py` → movido a `services/auth-service/app/main.py` (create_app)
- Delete: `services/auth-service/main.py` (raíz del servicio)

**Interfaces:**
- Consumes: `BaseServiceSettings`, `create_service_engine`, `get_session_factory`, `ServiceTokenMiddleware`, `EventBus`, `create_redis`, `register_exception_handlers`, `setup_logging`.
- Produces: `app.config.Settings(BaseServiceSettings)` con TODOS los campos/validators del config viejo (SECRET_KEY con validator anti-placeholder, FERNET_KEY, BCRYPT_PEPPER, GOOGLE_*, etc.); `app.main.create_app(settings: Settings | None = None) -> FastAPI`; entrypoint `app.main:app`; modelos registrados bajo `app.models` (metadata idéntica — `uv run alembic check`/`revision --autogenerate` vacío lo confirma).

- [ ] **Step 1: Reescribir `app/config.py`**

Cambiar la base de `Settings` a `BaseServiceSettings` y ELIMINAR los campos que ya hereda (`SERVICE_NAME`, `DATABASE_URL`, `REDIS_URL`, `PORT` con default 8001, `HOST`, `ENVIRONMENT`, `DEBUG`). Conservar TODOS los demás campos y validators exactamente como están (leer `app/config.py` viejo). Añadir `PORT: int = 8001`. Mantener `model_config` (heredado). Resultado esperado (ajustar a los campos reales del archivo viejo):

```python
from pydantic import field_validator

from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "auth-service"
    PORT: int = 8001

    SECRET_KEY: str
    DESK_SECRET_KEY: str = ""
    HUB_SECRET_KEY: str = ""
    NEST_SECRET_KEY: str = ""
    FERNET_KEY: str = ""
    BCRYPT_PEPPER: str = ""
    # ... (resto de campos del config viejo: GOOGLE_*, FRONTEND_URL, etc.)

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_placeholder(cls, v: str) -> str:
        if "change" in v.lower() or "placeholder" in v.lower() or len(v) < 16:
            raise ValueError("SECRET_KEY insegura")
        return v


settings = Settings()
```

(Conservar el validator original si difiere — el de arriba es ilustrativo del comportamiento ya existente: rechaza placeholders.)

- [ ] **Step 2: Mover modelos a package**

`git mv app/models.py app/models_old.py` temporal; crear `app/models/` con split por dominio: `user.py` (User), `tokens.py` (RefreshToken, LoginAttempt), `google.py` (GoogleOAuthToken); `__init__.py` re-exporta todo (`from app.models.user import User` etc. + `__all__`). Verificar metadata intacta:

```bash
cd services/auth-service && uv run python -c "
from app.models import *
from sqlmodel import SQLModel
print(sorted(SQLModel.metadata.tables.keys()))"
```
Expected: las mismas 4 tablas de antes (`users`, `auth_refresh_tokens`, `auth_login_attempts`, `google_oauth_tokens`). Borrar `app/models_old.py`. Verificar que las migraciones no detectan cambios (alembic no tiene dry-run para autogenerate: generar una revisión, inspeccionarla, borrarla):

```bash
# levantar el postgres desechable de Task 7 Step 5 si no está corriendo
cd services/auth-service
DATABASE_URL="postgresql+psycopg2://lead_os:lead_os_dev@localhost:55432/auth_db" \
SECRET_KEY="dev-secret-key-for-migrations-0123456789" INTER_SERVICE_SECRET="x" \
uv run alembic revision --autogenerate -m "check-noop"
cat migrations/versions/*check_noop.py
```
Expected: `upgrade()` y `downgrade()` vacíos (solo `pass`). Si contienen operaciones, el split de modelos cambió la metadata — corregir antes de seguir. En ambos casos, **borrar el archivo** `migrations/versions/*check_noop.py` al terminar la inspección.

- [ ] **Step 3: Crear `app/main.py` y borrar el viejo entrypoint**

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.router import router
from shared.cache.client import create_redis
from shared.auth.middleware import ServiceTokenMiddleware
from shared.db.engine import create_service_engine, get_session_factory
from shared.events.bus import EventBus
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        app.state.session_factory = get_session_factory(engine)
        app.state.redis = create_redis(settings.REDIS_URL)
        app.state.event_bus = EventBus(settings.REDIS_URL)
        app.state.settings = settings
        yield
        engine.dispose()

    app = FastAPI(title="auth-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)
    app.include_router(router, prefix="/api/auth")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
```

Borrar `services/auth-service/main.py` viejo y `app/database.py`. El lifespan viejo (init redis/db, CORS, exception handler 500 global) queda reemplazado por lo de arriba (sin CORS, sin create_all).

**Bloqueo temporal:** `app/router.py` no existe hasta Task 20 → `create_app` no importa aún. Para que ESTA task sea verificable, crear `app/router.py` mínimo temporal:

```python
from fastapi import APIRouter

router = APIRouter()
```

(Task 20 lo reemplaza con las rutas reales.) Los contract tests seguirán rojos (404/405) — esperado.

- [ ] **Step 4: Verificar arranque + commit**

```bash
cd services/auth-service && uv run python -c "from app.main import create_app; create_app(); print('app OK')"
git add services/auth-service/
git commit -m "refactor(auth): config sobre shared, models como package, create_app con shared (S2)"
```

### Task 20 (auth S3): services/, serializers/, schemas/, controller facade, router único

**Files:**
- Create: `services/auth-service/app/services/__init__.py`, `services/auth-service/app/services/security.py` (movido de `app/security.py`), `services/auth-service/app/services/google_oauth.py` (movido de `app/google_oauth.py`), `services/auth-service/app/services/auth.py` (lógica de `app/services.py`)
- Create: `services/auth-service/app/schemas/__init__.py` + `services/auth-service/app/schemas/{auth.py,user.py,google.py}` (de `app/schemas.py`)
- Create: `services/auth-service/app/serializers/__init__.py`, `services/auth-service/app/serializers/user.py`
- Create: `services/auth-service/app/controller.py`
- Modify: `services/auth-service/app/router.py` (reemplaza el temporal)
- Delete: `services/auth-service/app/security.py`, `services/auth-service/app/google_oauth.py`, `services/auth-service/app/services.py`, `services/auth-service/app/schemas.py`, `services/auth-service/app/routes.py`, `services/auth-service/app/google_routes.py`, `services/auth-service/app/redis_client.py`, `services/auth-service/app/redis_cache.py`
- Test: `services/auth-service/tests/test_services.py` (serializers + lógica pura de services/security: hash/verify password, mint/decode tokens multi-plataforma)

**Interfaces:**
- Consumes: todo Task 17-19; fixtures de Task 18.
- Produces (contrato que Task 18 ya testea): `app.services.auth.login_user(*, db, settings, email, password) -> dict`; `app.services.auth.register_user(*, db, settings, data, event_bus) -> User`; controller functions `login`, `register`, `refresh`, `logout`, `password_reset_*`, `service_token`, `admin_check`, `google_*`; router con todas las rutas `/api/auth/*` + `/api/auth/google/*`.

- [ ] **Step 1: Mover código heredado a services/ (git mv + fix imports)**

```bash
cd services/auth-service
mkdir -p app/services app/serializers
git mv app/security.py app/services/security.py
git mv app/google_oauth.py app/services/google_oauth.py
git mv app/services.py app/services/auth.py
```
Corregir imports internos (`from app.security import` → `from app.services.security import`, etc.) en los archivos movidos. `app/services/auth.py` debe importar seguridad desde `app.services.security`. `touch app/services/__init__.py app/serializers/__init__.py`.

- [ ] **Step 2: Extraer schemas a package y crear serializers**

`git mv app/schemas.py app/schemas_old.py`; crear `app/schemas/` (auth.py: LoginRequest/TokenResponse/RefreshRequest/PasswordReset*/ServiceTokenRequest; user.py: UserRegister/UserResponse; google.py: los de google) moviendo cada modelo pydantic a su archivo; `__init__.py` re-exporta. Crear `app/serializers/user.py`:

```python
from app.models import User
from app.schemas.user import UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)
```

- [ ] **Step 3: Escribir tests de lógica pura — `tests/test_services.py`**

```python
from app.services import security


def test_password_hash_roundtrip():
    hashed = security.get_password_hash("Secret123")
    assert security.verify_password("Secret123", hashed)
    assert not security.verify_password("wrong", hashed)


def test_access_token_roundtrip_desk_platform():
    token = security.create_access_token({"sub": "1", "platform": "desk"})
    claims = security.decode_token(token)
    assert claims["sub"] == "1"
```

(Ajustar a los nombres REALES de funciones en `app/services/security.py` tras el move — leer el archivo. Cubrir: hash/verify, create/decode token por plataforma, Fernet encrypt/decrypt.)

- [ ] **Step 4: Escribir `app/controller.py` (FACADE)**

Un método por endpoint, firmas orientadas a deps (ejemplos representativos; completar con TODOS los endpoints del inventario de Task 18 Step 1):

```python
from fastapi.security import OAuth2PasswordRequestForm

from app.config import Settings
from app.schemas.auth import RefreshRequest, TokenResponse
from app.schemas.user import UserRegister, UserResponse
from app.serializers.user import user_to_response
from app.services import auth as auth_service
from shared.auth.dependencies import Identity
from shared.events.bus import EventBus
from sqlmodel import Session


def login(*, form: OAuth2PasswordRequestForm, db: Session, settings: Settings) -> TokenResponse:
    tokens = auth_service.login_user(db=db, settings=settings,
                                     email=form.username, password=form.password)
    return TokenResponse(**tokens)


def register(*, data: UserRegister, db: Session, settings: Settings,
             event_bus: EventBus) -> UserResponse:
    user = auth_service.register_user(db=db, settings=settings, data=data, event_bus=event_bus)
    db.commit()
    db.refresh(user)
    return user_to_response(user)


def refresh(*, data: RefreshRequest, db: Session, settings: Settings) -> TokenResponse: ...
def logout(*, identity: Identity, db: Session, settings: Settings) -> dict: ...
# ... password reset request/confirm, service-token, admin-check, google login/callback/status/disconnect
```

- [ ] **Step 5: Reescribir `app/router.py` con TODAS las rutas**

Patrón por endpoint (replicar para todo el inventario, incl. el sub-router google fusionado con prefix `/google`):

```python
from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.auth import RefreshRequest, TokenResponse
from app.schemas.user import UserRegister, UserResponse
from shared.auth.dependencies import Identity, get_current_identity
from shared.db.engine import get_db
from shared.events.bus import EventBus

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings)) -> TokenResponse:
    return controller.login(form=form, db=db, settings=settings)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings),
             event_bus: EventBus = Depends(get_event_bus)) -> UserResponse:
    return controller.register(data=data, db=db, settings=settings, event_bus=event_bus)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings)) -> TokenResponse:
    return controller.refresh(data=data, db=db, settings=settings)


@router.post("/logout")
def logout(identity: Identity = Depends(get_current_identity),
           db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    return controller.logout(identity=identity, db=db, settings=settings)

# ... resto del inventario + rutas google (/google/login, /google/callback, ...)
```

Nota: endpoints públicos (login/register/refresh/password-reset/google) NO llevan `get_current_identity`; los privados sí. El `X-Service-Token` ya es global por middleware.

- [ ] **Step 6: Borrar archivos viejos y verificar suite VERDE**

```bash
cd services/auth-service
git rm app/routes.py app/google_routes.py app/schemas_old.py app/redis_client.py app/redis_cache.py
uv run pytest tests/ -q
```
Expected: toda la suite (contract + services) en VERDE. Si un contract test falla por shape distinta, corregir controller/router (el test es la fuente de verdad del contrato heredado — salvo que el test esté mal escrito respecto al comportamiento viejo; entonces corregir el test citando el código viejo).

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/
git commit -m "refactor(auth): MVC + facade (services/schemas/serializers/controller/router únicos) (S3)"
```

### Task 21 (auth S4): evento user.registered + Dockerfiles + verificación

**Files:**
- Modify: `services/auth-service/app/services/auth.py` (publicar evento tras register)
- Test: `services/auth-service/tests/test_events.py`
- Create: `services/auth-service/Dockerfile`, `services/auth-service/Dockerfile.dev`
- Delete: ninguno (Dockerfile viejo se reemplaza: `git rm services/auth-service/Dockerfile` antes de crear el nuevo)

**Interfaces:**
- Consumes: `EventBus.publish` (Task 11), `EventEnvelope`.
- Produces: tras `register_user` exitoso (post-commit, en controller o service — decidir: en `register_user` tras flush+commit interno del service), publicar en domain `auth`: `EventEnvelope(type="user.registered", aggregate_id=str(user.id), tenant_id=user.tenant_id, payload={"email": user.email, "full_name": user.full_name})`. Dockerfiles listos para compose (Task 33).

- [ ] **Step 1: Escribir el test que falla — `tests/test_events.py`**

```python
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from shared.events.envelope import EventEnvelope


class _FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, domain, event):
        self.published.append((domain, event))
        return "1-0"


def test_register_publishes_user_registered(svc_headers, monkeypatch):
    class U:
        id = 99
        email = "n@x.com"
        full_name = "N"
        tenant_id = 1

    monkeypatch.setattr("app.controller.auth_service.register_user",
                        lambda **kwargs: U())

    bus = _FakeBus()
    from app.main import create_app
    from app.router import get_event_bus
    from shared.db.engine import get_db

    app = create_app()
    app.dependency_overrides[get_event_bus] = lambda: bus
    app.dependency_overrides[get_db] = lambda: MagicMock()
    with TestClient(app) as c:
        resp = c.post("/api/auth/register",
                      json={"email": "n@x.com", "password": "Pw123456", "full_name": "N"},
                      headers=svc_headers)
    assert resp.status_code == 201
    assert len(bus.published) == 1
    domain, event = bus.published[0]
    assert domain == "auth"
    assert isinstance(event, EventEnvelope)
    assert event.type == "user.registered" and event.aggregate_id == "99"
    assert event.payload["email"] == "n@x.com"
```

(Ajustar el monkeypatch a la forma real del controller — el mockeo asume que `app/controller.py` hace `from app.services import auth as auth_service` (Task 20 Step 4). El punto del contrato: registrar un usuario publica `user.registered` en domain `auth` con aggregate_id = id del usuario.)

- [ ] **Step 2: Implementar publicación en `app/services/auth.py`**

En `register_user`, tras crear el usuario y hacer commit:

```python
    db.commit()
    db.refresh(user)
    event_bus.publish("auth", EventEnvelope(
        type="user.registered",
        aggregate_id=str(user.id),
        tenant_id=user.tenant_id,
        payload={"email": user.email, "full_name": user.full_name},
    ))
    return user
```

(añadir imports de `EventEnvelope` y el parámetro `event_bus: EventBus` a la firma; el controller ya lo pasa desde Task 20.)

- [ ] **Step 3: Reemplazar Dockerfile viejo y crear Dockerfile.dev**

```bash
git rm services/auth-service/Dockerfile
```

`services/auth-service/Dockerfile` (producción):

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build
COPY shared/ ./shared/
COPY services/auth-service/ ./services/auth-service/
WORKDIR /build/services/auth-service
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /build/services/auth-service/.venv /app/.venv
COPY services/auth-service/app /app/app
COPY services/auth-service/alembic.ini /app/alembic.ini
COPY services/auth-service/migrations /app/migrations
USER app
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/health')" || exit 1
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

`services/auth-service/Dockerfile.dev` (hot reload):

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY shared/ ./shared/
COPY services/auth-service/ ./services/auth-service/
WORKDIR /app/services/auth-service
RUN uv sync --frozen
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--reload", "--reload-dir", "/app/services/auth-service/app", "--reload-dir", "/app/shared/src"]
```

- [ ] **Step 4: Verificación final del servicio + commit**

```bash
cd services/auth-service && uv run pytest -q
docker build -f services/auth-service/Dockerfile -t lead-os-auth:test . && echo BUILD OK
git add services/auth-service/
git commit -m "feat(auth): publica user.registered + Dockerfiles prod/dev (S4)"
```

### Task 22 (tenant S1): tests de contrato + conftest

**Files:**
- Create: `services/tenant-service/tests/__init__.py`, `services/tenant-service/tests/conftest.py`, `services/tenant-service/tests/test_router_contract.py`

**Interfaces:**
- Consumes: patrón de fixtures de `services/auth-service/tests/conftest.py` (Task 18 — ya existe en el repo).
- Produces: fixtures `client`, `svc_headers`, `identity`, `mock_db` + suite de contrato roja para tenant-service.

- [ ] **Step 1: Inventario de endpoints + paths públicos exactos**

Run: `grep -n "@router\." services/tenant-service/app/routes.py`
Listar método+path de cada endpoint y con qué prefijo se monta el router en `main.py` viejo (`include_router(router, prefix="/api")`). **Importante (compat):** anotar los paths que NO cuelgan de `/api/tenants` (p.ej. `/api/resolve/{slug}` si existe): el gateway necesitará una entrada extra en `service_routes` por cada prefijo público distinto — se añade en Task 24 Step 5 al gateway (`app/config.py` `service_routes`). Los endpoints `/api/internal/tenants/*` NO se añaden al gateway (solo red interna).

- [ ] **Step 2: `tests/conftest.py` — copiar el de auth-service (Task 18 Step 2) cambiando:**

```python
os.environ.setdefault("SERVICE_NAME", "tenant-service")
os.environ.setdefault("PORT", "8002")
# + env propios que exija app/config.py viejo (leer el archivo: CLOUDFLARE_* si son required, BASE_DOMAIN, CNAME_TARGET, etc. con valores dummy)
```

- [ ] **Step 3: `tests/test_router_contract.py` (rojo)**

Cubrir TODOS los endpoints del inventario con el patrón de Task 18 Step 3. Mínimo obligatorio: CRUD de tenants (list/create/get/update), resolve por slug, endpoints internos (`db-credentials`, `active-ids`) verificando que responden con service-token válido y 401 sin él, endpoint admin (403 con identity no-admin vía `require_admin`, 200 con `Identity(is_superuser=True)`), health. Los nombres de funciones de servicio mockeadas (`app.services.tenants.*`, `app.services.cloudflare.*`) son el contrato de Task 24.

- [ ] **Step 4: Verificar ROJO**

Run: `cd services/tenant-service && uv run pytest tests/ -q`
Expected: FAIL en collection (`No module named 'app.main'`).

### Task 23 (tenant S2): config, models package, main.py nuevo

**Files:**
- Modify: `services/tenant-service/app/config.py`
- Create: `services/tenant-service/app/models/{__init__.py,...}` (split del models.py viejo por dominio)
- Delete: `services/tenant-service/app/models.py`, `services/tenant-service/app/database.py`, `services/tenant-service/main.py`
- Create: `services/tenant-service/app/main.py`, `services/tenant-service/app/router.py` (temporal vacío)

**Interfaces:**
- Produce: `Settings(BaseServiceSettings)` con `SERVICE_NAME="tenant-service"`, `PORT=8002` + campos propios del config viejo (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, CLOUDFLARE_ACCOUNT_ID, BASE_DOMAIN, CNAME_TARGET — conservar nombres/defaults exactos); `create_app(settings=None)`; metadata de modelos intacta (verificación con el mismo comando de Task 19 Step 2 contra tenant_db).

- [ ] **Step 1: Reescribir config sobre BaseServiceSettings (mismo procedimiento que Task 19 Step 1: heredar base, borrar campos heredados, conservar el resto).**

- [ ] **Step 2: Mover modelos a `app/models/` package + verificar metadata intacta y alembic sin cambios (mismo procedimiento que Task 19 Step 2, DB=tenant_db).**

- [ ] **Step 3: Crear `app/main.py` — mismo contenido que Task 19 Step 3 cambiando `title="tenant-service"` y `app.include_router(router, prefix="/api")` (las rutas internas `/api/internal/*` cuelgan del mismo router; ver Task 24 para el layout exacto de paths). Crear `app/router.py` temporal vacío. Borrar `main.py` raíz y `app/database.py`.**

- [ ] **Step 4: Verificar arranque + commit**

```bash
cd services/tenant-service && uv run python -c "from app.main import create_app; create_app(); print('app OK')"
git add services/tenant-service/ && git commit -m "refactor(tenant): config sobre shared, models package, create_app (S2)"
```

### Task 24 (tenant S3): services/, controller, router único

**Files:**
- Create: `services/tenant-service/app/services/{__init__.py,tenants.py}`, `app/services/cloudflare.py` (movido de `app/cloudflare.py`), `app/schemas/{__init__.py,tenant.py}`, `app/serializers/{__init__.py,tenant.py}`, `app/controller.py`
- Modify: `services/tenant-service/app/router.py` (reemplaza temporal)
- Modify: `services/api-gateway/app/config.py` (añadir prefijos públicos extra detectados en Task 22 Step 1 a `service_routes`) + test `services/api-gateway/tests/test_config_routes.py`
- Delete: `services/tenant-service/app/routes.py`, `services/tenant-service/app/services.py`, `services/tenant-service/app/schemas.py`, `services/tenant-service/app/cloudflare.py`, `services/tenant-service/app/redis_client.py`, `services/tenant-service/app/redis_cache.py`
- Test: `services/tenant-service/tests/test_services.py`

**Interfaces:**
- Consumes: `require_admin` (Task 17), cache de shared (Task 17) si el viejo routes.py usa `@cached`.
- Produces: `app.services.tenants.*` (CRUD + resolve + internals), `app.services.cloudflare.*`; controller methods por endpoint; router único.

- [ ] **Step 1: git mv + fix imports**

```bash
cd services/tenant-service
mkdir -p app/services app/serializers
git mv app/cloudflare.py app/services/cloudflare.py
git mv app/services.py app/services/tenants.py
touch app/services/__init__.py app/serializers/__init__.py
```
Mover la lógica que viva en `app/routes.py` (los handlers grandes) dentro de `app/services/tenants.py` como funciones `def create_tenant(*, db, settings, data) -> Tenant`, etc. Reemplazar `_decode_bearer`/`require_service_token`/`require_admin_token` por `get_current_identity` + `require_admin`. Si usa `@cached`/`_invalidate_shared_cache_safe`, cambiar a `shared.cache.decorator.cached`/`invalidate_pattern` (firma: la función decorada recibe `redis_client` kwarg; inyectar desde `app.state.redis` vía el controller).

- [ ] **Step 2: schemas package + serializers (mismo procedimiento que Task 20 Step 2, dominio tenant).**

- [ ] **Step 3: `app/controller.py` + `app/router.py` con todo el inventario (patrón Task 20 Steps 4-5). Paths: montar el router con `prefix="/api"`; rutas públicas bajo `/tenants...`, internas bajo `/internal/tenants/...` (quedan `/api/internal/tenants/*` — solo red interna, el gateway NO las proxifica).**

- [ ] **Step 4: Añadir prefijos extra al gateway**

`services/api-gateway/app/config.py` → en `service_routes`, añadir cada prefijo público de tenant no cubierto (p.ej. `"/api/resolve": self.TENANT_SERVICE_URL`) según el inventario de Task 22 Step 1. Test nuevo `services/api-gateway/tests/test_config_routes.py`:

```python
from app.config import Settings


def test_service_routes_cover_all_public_prefixes():
    s = Settings(SERVICE_NAME="api-gateway", INTER_SERVICE_SECRET="x", SECRET_KEY="y")
    routes = s.service_routes
    assert routes["/api/auth"] == s.AUTH_SERVICE_URL
    assert routes["/api/tenants"] == s.TENANT_SERVICE_URL
    assert routes["/api/users"] == s.USERS_SERVICE_URL
    assert routes["/api/files"] == s.FILES_SERVICE_URL
    assert routes["/api/saas/webhooks"] == s.USERS_SERVICE_URL
    assert "/api/internal" not in routes
```

(Añadir asserts por cada prefijo extra añadido.) Verificar suite del gateway en verde: `cd services/api-gateway && uv run pytest -q`.

- [ ] **Step 5: Suite tenant VERDE + commit**

```bash
cd services/tenant-service && uv run pytest tests/ -q
git add services/tenant-service/ services/api-gateway/
git commit -m "refactor(tenant): MVC + facade; gateway: prefijos públicos de tenant (S3)"
```

### Task 25 (tenant S4): Dockerfiles + verificación

**Files:**
- Delete+Create: `services/tenant-service/Dockerfile`; Create: `services/tenant-service/Dockerfile.dev`

- [ ] **Step 1: `git rm services/tenant-service/Dockerfile` y crear los Dockerfiles (idénticos a Task 21 Step 3 cambiando `auth-service`→`tenant-service` y puerto `8001`→`8002` en los 4 lugares).**

- [ ] **Step 2: Verificación + commit**

```bash
cd services/tenant-service && uv run pytest -q
docker build -f services/tenant-service/Dockerfile -t lead-os-tenant:test . && echo BUILD OK
git add services/tenant-service/ && git commit -m "feat(tenant): Dockerfiles prod/dev (S4)"
```

### Task 26 (users S1): tests de contrato + conftest

**Files:**
- Create: `services/users-service/tests/__init__.py`, `services/users-service/tests/conftest.py`, `services/users-service/tests/test_router_contract.py`, `services/users-service/tests/test_events.py`

**Interfaces:**
- Consumes: fixtures patrón auth (Task 18); `EventEnvelope` (Task 11).
- Produces: contrato para users-service incl. webhooks Aria y consumer de `user.registered`.

- [ ] **Step 1: Inventario de endpoints**

Run: `grep -n "@router\.\|@webhook_router\.\|@calendar_router\.\|@google_calendar" services/users-service/app/routes.py services/users-service/app/webhooks.py services/users-service/app/calendar_routes.py services/users-service/app/google_calendar_routes.py`
Ajustar el grep a los nombres reales de los routers. Listar todos los endpoints (paths completos `/api/users/*`, `/api/saas/webhooks/aria`).

- [ ] **Step 2: `tests/conftest.py` — patrón Task 18 con env de users-service:** `SERVICE_NAME=users-service`, `PORT=8003`, `WEBHOOK_API_KEY=test-webhook-key`, `GOOGLE_CREDENTIALS_JSON={}` (o lo que exija el config viejo).

- [ ] **Step 3: `tests/test_router_contract.py` (rojo)** — todos los endpoints del inventario con el patrón Task 18. Mínimo: CRUD users, perfil me, endpoints admin (403 no-admin), webhook Aria: 401/403 sin `WEBHOOK_API_KEY` correcto, 200 con él (es ruta PÚBLICA — sin service-token... **decisión:** el middleware global exime `/health` solamente; el webhook llega VÍA gateway que inyecta service-token en rutas públicas, así que el endpoint webhook NO se exime en el middleware — el test debe pasar `svc_headers` + el api key). Calendar endpoints con servicios mockeados.

- [ ] **Step 4: `tests/test_events.py` (rojo) — contrato del consumer:**

```python
from shared.events.envelope import EventEnvelope


class _FakeSession:
    """Simula una sesión SQLModel: exec(...).first() devuelve lo que tenga self.existing."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commits = 0

    def exec(self, *args, **kwargs):
        return type("Result", (), {"first": lambda _self: self.existing})()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def test_handle_user_registered_creates_profile():
    from app.events import handle_user_registered

    db = _FakeSession(existing=None)
    event = EventEnvelope(type="user.registered", aggregate_id="77",
                          tenant_id=1, payload={"email": "n@x.com", "full_name": "N"})
    handle_user_registered(event, db=db)
    assert len(db.added) == 1 and db.commits == 1


def test_handle_user_registered_is_idempotent():
    from app.events import handle_user_registered

    db = _FakeSession(existing=object())  # ya existe perfil para aggregate_id
    event = EventEnvelope(type="user.registered", aggregate_id="77",
                          tenant_id=1, payload={"email": "n@x.com", "full_name": "N"})
    handle_user_registered(event, db=db)  # no lanza, no duplica
    assert db.added == [] and db.commits == 0
```

- [ ] **Step 5: Verificar ROJO**

Run: `cd services/users-service && uv run pytest tests/ -q`
Expected: FAIL (`No module named 'app.main'` / `app.events`).

### Task 27 (users S2): config, models package, main.py nuevo

**Files:**
- Modify: `services/users-service/app/config.py`
- Create: `services/users-service/app/models/{__init__.py,...}`, `services/users-service/app/main.py`, `services/users-service/app/router.py` (temporal), `services/users-service/app/events.py` (temporal: handlers vacíos registrados en dict)
- Delete: `services/users-service/app/models.py`, `services/users-service/app/database.py`, `services/users-service/main.py`

**Interfaces:**
- Produce: `Settings(BaseServiceSettings)` (`SERVICE_NAME="users-service"`, `PORT=8003`, + WEBHOOK_API_KEY, GOOGLE_CREDENTIALS_JSON, ARIA_* y demás campos del config viejo); `create_app(settings=None)` que además arranca el `Consumer` de eventos en un thread daemon dentro del lifespan (`stop()` al shutdown); `app.events.HANDLERS: dict[str, EventHandler]`.

- [ ] **Step 1-3: Mismo procedimiento que Task 23 (config → BaseServiceSettings; models package con metadata intacta verificada contra users_db — **ojo:** el viejo lifespan hace `SQLModel.metadata.create_all(engine)`: ELIMINARLO, las tablas las crea la migración de Task 7; main.py nuevo).**

En `app/main.py`, además del lifespan estándar de Task 19 Step 3, arrancar el consumer:

```python
import threading

from app.events import HANDLERS
from shared.events.consumer import Consumer

# dentro del lifespan, tras inicializar app.state:
        consumer = Consumer(
            settings.REDIS_URL,
            domain="auth",
            group="users-service",
            consumer_name=f"users-service-{settings.SERVICE_NAME}",
            handlers=HANDLERS,
        )
        thread = threading.Thread(target=consumer.run_forever, daemon=True)
        thread.start()
        yield
        consumer.stop()
        thread.join(timeout=5)
```

(Y quitar el segundo `yield`/cierre que ponga el patrón base — un solo `yield`.) `app/events.py` temporal:

```python
from shared.events.consumer import EventHandler

HANDLERS: dict[str, EventHandler] = {}
```

- [ ] **Step 4: Verificar arranque + commit**

```bash
cd services/users-service && uv run python -c "from app.main import create_app; create_app(); print('app OK')"
git add services/users-service/ && git commit -m "refactor(users): config sobre shared, models package, create_app + consumer lifespan (S2)"
```

### Task 28 (users S3): services/, controller, router único, events.py real

**Files:**
- Create: `services/users-service/app/services/{__init__.py,users.py,webhooks.py,calendar.py}`, `app/schemas/{__init__.py,user.py,webhook.py,calendar.py}`, `app/serializers/{__init__.py,user.py}`, `app/controller.py`
- Modify: `services/users-service/app/router.py`, `services/users-service/app/events.py`
- Delete: `services/users-service/app/routes.py`, `services/users-service/app/webhooks.py`, `services/users-service/app/calendar_routes.py`, `services/users-service/app/google_calendar_routes.py`, `services/users-service/app/services.py`, `services/users-service/app/schemas.py`, `services/users-service/app/redis_client.py`, `services/users-service/app/redis_cache.py`
- Test: `services/users-service/tests/test_services.py`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: `app.services.users.*`, `app.services.webhooks.*` (verificación `WEBHOOK_API_KEY` viva aquí — el controller la pasa; comparación con `secrets.compare_digest`), `app.services.calendar.*`; `app.events.handle_user_registered(event: EventEnvelope, *, db) -> None` registrado en `HANDLERS = {"user.registered": ...}`; router único con paths completos (`/api/users/*`, `/api/saas/webhooks/aria` — router montado SIN prefix, paths en decoradores, como hoy).

- [ ] **Step 1: git mv + reorganizar**

```bash
cd services/users-service
mkdir -p app/services app/serializers
git mv app/services.py app/services/users.py
git mv app/webhooks.py /tmp/webhooks_old.py   # la lógica se reubica, el archivo se borra
```
Mover la lógica de negocio de `app/routes.py` → `app/services/users.py`; de `/tmp/webhooks_old.py` → `app/services/webhooks.py`; de `calendar_routes.py`/`google_calendar_routes.py` → `app/services/calendar.py` (conservar funciones de Google API tal cual). Reemplazar deps inline (`verify_token`, `_is_admin_token`, `_require_self_or_admin`) por `get_current_identity` + `require_admin` + comparaciones `identity.user_id == target_id` en controller. Eliminar `get_tenant_db`/`SET LOCAL app.tenant_id`: los services reciben `db` normal y filtran por `tenant_id` explícito (regla 3 de Fase 3). Cache viejo → `shared.cache` (Task 17).

- [ ] **Step 2: schemas + serializers (procedimiento Task 20 Step 2, dominios user/webhook/calendar).**

- [ ] **Step 3: controller + router único (patrón Task 20). Router montado sin prefix en main (`app.include_router(router)`) y decoradores con paths completos `/api/users/...` y `/api/saas/webhooks/aria` (compat con el contrato externo de Aria).**

- [ ] **Step 4: Implementar `app/events.py` real**

```python
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope


def handle_user_registered(event: EventEnvelope, *, db) -> None:
    """Idempotente: crea el perfil si no existe para aggregate_id (user_id)."""
    ...  # leer app/models/ para el modelo de perfil real (p.ej. User/UserProfile):
    # existing = db.exec(select(Profile).where(Profile.id == int(event.aggregate_id))).first()
    # if existing: return
    # db.add(Profile(id=int(event.aggregate_id), tenant_id=event.tenant_id,
    #                email=event.payload["email"], full_name=event.payload.get("full_name")))
    # db.commit()


HANDLERS: dict[str, EventHandler] = {
    "user.registered": handle_user_registered,
}
```

**OJO (firma del handler):** `EventHandler = Callable[[EventEnvelope], None]` pero el handler necesita `db`. Resolver con cierre en `app/events.py`: una factoría `build_handlers(session_factory) -> dict[str, EventHandler]` que envuelve `handle_user_registered(event, db=session)` creando sesión por evento. Ajustar `app/main.py` (Task 27) para llamar `HANDLERS = build_handlers(app.state.session_factory)` dentro del lifespan. Los tests de Task 26 Step 4 llaman `handle_user_registered(event, db=fake)` directamente.

- [ ] **Step 5: Suite users VERDE + commit**

```bash
cd services/users-service && uv run pytest tests/ -q
git add services/users-service/ && git commit -m "refactor(users): MVC + facade + consumer user.registered (S3)"
```

### Task 29 (users S4): Dockerfiles + verificación

- [ ] **Step 1: `git rm services/users-service/Dockerfile`; crear Dockerfile y Dockerfile.dev idénticos a Task 21 Step 3 cambiando `auth-service`→`users-service` y puerto `8001`→`8003`.**

- [ ] **Step 2: Verificación + commit**

```bash
cd services/users-service && uv run pytest -q
docker build -f services/users-service/Dockerfile -t lead-os-users:test . && echo BUILD OK
git add services/users-service/ && git commit -m "feat(users): Dockerfiles prod/dev (S4)"
```

### Task 30 (files S1): tests de contrato + conftest

**Files:**
- Create: `services/files-service/tests/__init__.py`, `services/files-service/tests/conftest.py`, `services/files-service/tests/test_router_contract.py`

**Interfaces:**
- Consumes: fixtures patrón auth (Task 18).
- Produces: contrato para files-service (upload/download/streaming/delete/list bajo `/api/files/*`).

- [ ] **Step 1: Inventario de endpoints**

Run: `grep -n "@router\." services/files-service/app/routes.py`
Listar todos los endpoints (paths completos `/api/files/*`, métodos, cuáles usan streaming/Range, límite 500MB).

- [ ] **Step 2: `tests/conftest.py` — patrón Task 18 con env de files-service:** `SERVICE_NAME=files-service`, `PORT=8004`, `STORAGE_PATH=<tmp_path por test vía fixture>` — storage en disco: la fixture usa `tmp_path` de pytest y override de settings (crear app con `create_app(Settings(STORAGE_PATH=str(tmp_path), ...))`).

- [ ] **Step 3: `tests/test_router_contract.py` (rojo)** — todos los endpoints del inventario. Mínimo: upload (multipart, 201 + metadata con id), download (200 bytes correctos), download con `Range` (206), list por tenant (solo archivos del tenant de la identity — test de aislamiento: archivos de otro tenant NO aparecen), delete (204/200), archivo inexistente (404), sin service-token (401), health. Storage real en `tmp_path`, DB mockeada donde aplique (metadata en DB: mockear `get_db` y verificar llamadas, o sqlite si los modelos lo permiten — preferir mock para el contrato).

- [ ] **Step 4: Verificar ROJO**

Run: `cd services/files-service && uv run pytest tests/ -q`
Expected: FAIL (`No module named 'app.main'`).

### Task 31 (files S2): config, models package, main.py nuevo

**Files:**
- Modify: `services/files-service/app/config.py`
- Create: `services/files-service/app/models/{__init__.py,...}`, `services/files-service/app/main.py`, `services/files-service/app/router.py` (temporal)
- Delete: `services/files-service/app/models.py`, `services/files-service/app/database.py`, `services/files-service/main.py`

- [ ] **Step 1-3: Mismo procedimiento que Task 23** (config → BaseServiceSettings con `SERVICE_NAME="files-service"`, `PORT=8004`, `STORAGE_PATH: str = "./storage"` + campos del config viejo; models package con metadata intacta contra files_db; main.py estándar de Task 19 Step 3 con `app.include_router(router)` SIN prefix — los decoradores llevan `/api/files/...`; lifespan crea `Path(settings.STORAGE_PATH).mkdir(parents=True, exist_ok=True)` además de lo estándar; eliminar `create_all` del lifespan viejo si existe).

- [ ] **Step 4: Verificar arranque + commit**

```bash
cd services/files-service && uv run python -c "from app.main import create_app; create_app(); print('app OK')"
git add services/files-service/ && git commit -m "refactor(files): config sobre shared, models package, create_app (S2)"
```

### Task 32 (files S3): services/, controller, router único

**Files:**
- Create: `services/files-service/app/services/{__init__.py,storage.py,files.py}`, `app/schemas/{__init__.py,file.py}`, `app/serializers/{__init__.py,file.py}`, `app/controller.py`
- Modify: `services/files-service/app/router.py` (reemplaza temporal)
- Delete: `services/files-service/app/routes.py`, `services/files-service/app/services.py`, `services/files-service/app/schemas.py`, `services/files-service/app/redis_client.py`, `services/files-service/app/redis_cache.py`
- Test: `services/files-service/tests/test_services.py`

**Interfaces:**
- Produce: `app.services.storage.*` (disco: save_stream, open_range, delete, path traversal seguro, límite 500MB — conservar constante del código viejo), `app.services.files.*` (metadata DB, queries con `tenant_id` explícito); controller methods; router único.

- [ ] **Step 1: Reorganizar:** lógica de disco/streaming de `app/routes.py`+`app/services.py` → `app/services/storage.py`; lógica de metadata/queries → `app/services/files.py`; `git mv app/services.py app/services/files.py` como punto de partida. Reemplazar deps inline por `get_current_identity`. Eliminar RLS/`SET LOCAL`. El streaming con Range se conserva tal cual (portar la función vieja; NO importar la del gateway — cada servicio es independiente).

- [ ] **Step 2: schemas + serializers (procedimiento Task 20 Step 2, dominio file: FileMetadata response, FileList, etc.).**

- [ ] **Step 3: controller + router único (patrón Task 20). Upload: `UploadFile = File(...)`; el controller orquesta `storage.save_stream` + `files.create_metadata` en UNA transacción lógica (si falla el disco, no hay metadata; si falla metadata, borrar el archivo — conservar el orden del código viejo).**

- [ ] **Step 4: tests de services — `tests/test_services.py`:** storage real sobre `tmp_path` (save/open/delete/traversal 404/límite de tamaño con un stream falso que excede), serializers.

- [ ] **Step 5: Suite files VERDE + commit**

```bash
cd services/files-service && uv run pytest tests/ -q
git add services/files-service/ && git commit -m "refactor(files): MVC + facade (S3)"
```

### Task 33 (files S4): Dockerfiles + verificación

- [ ] **Step 1: `git rm services/files-service/Dockerfile`; crear Dockerfile y Dockerfile.dev idénticos a Task 21 Step 3 cambiando `auth-service`→`files-service` y puerto `8001`→`8004`.**

- [ ] **Step 2: Verificación + commit**

```bash
cd services/files-service && uv run pytest -q
docker build -f services/files-service/Dockerfile -t lead-os-files:test . && echo BUILD OK
git add services/files-service/ && git commit -m "feat(files): Dockerfiles prod/dev (S4)"
```

---

# FASE 4 — Orquestación local (compose + Makefile)

### Task 34: docker-compose.yml + .env.example

**Files:**
- Create: `docker-compose.yml` (raíz), `.env.example` (raíz)

**Interfaces:**
- Consumes: `infra/postgres/init.sql` (Task 7), Dockerfiles.dev (Tasks 16, 21, 25, 29, 33).
- Produces: stack de dev completo: postgres (init.sql) + redis + gateway (único puerto publicado 8000) + 4 servicios con profiles = nombre del servicio; `.env.example` documentando TODAS las variables.

- [ ] **Step 1: Crear `docker-compose.yml`**

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
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lead_os"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10

  api-gateway:
    build:
      context: .
      dockerfile: services/api-gateway/Dockerfile.dev
    env_file: .env
    environment:
      AUTH_SERVICE_URL: http://auth-service:8001
      TENANT_SERVICE_URL: http://tenant-service:8002
      USERS_SERVICE_URL: http://users-service:8003
      FILES_SERVICE_URL: http://files-service:8004
      REDIS_URL: redis://redis:6379/0
      PORT: "8000"
    ports:
      - "8000:8000"
    volumes:
      - ./services/api-gateway:/app/services/api-gateway
      - ./shared:/app/shared
      - gateway_venv:/app/services/api-gateway/.venv
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  auth-service:
    build:
      context: .
      dockerfile: services/auth-service/Dockerfile.dev
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
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  tenant-service:
    build:
      context: .
      dockerfile: services/tenant-service/Dockerfile.dev
    profiles: ["tenant-service"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://lead_os:${POSTGRES_PASSWORD:-lead_os_dev}@postgres:5432/tenant_db
      REDIS_URL: redis://redis:6379/0
      PORT: "8002"
    volumes:
      - ./services/tenant-service:/app/services/tenant-service
      - ./shared:/app/shared
      - tenant_venv:/app/services/tenant-service/.venv
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  users-service:
    build:
      context: .
      dockerfile: services/users-service/Dockerfile.dev
    profiles: ["users-service"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://lead_os:${POSTGRES_PASSWORD:-lead_os_dev}@postgres:5432/users_db
      REDIS_URL: redis://redis:6379/0
      PORT: "8003"
    volumes:
      - ./services/users-service:/app/services/users-service
      - ./shared:/app/shared
      - users_venv:/app/services/users-service/.venv
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

  files-service:
    build:
      context: .
      dockerfile: services/files-service/Dockerfile.dev
    profiles: ["files-service"]
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://lead_os:${POSTGRES_PASSWORD:-lead_os_dev}@postgres:5432/files_db
      REDIS_URL: redis://redis:6379/0
      PORT: "8004"
      STORAGE_PATH: /data/storage
    volumes:
      - ./services/files-service:/app/services/files-service
      - ./shared:/app/shared
      - files_venv:/app/services/files-service/.venv
      - files_storage:/data/storage
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }

volumes:
  pgdata:
  gateway_venv:
  auth_venv:
  tenant_venv:
  users_venv:
  files_venv:
  files_storage:
```

- [ ] **Step 2: Crear `.env.example`**

```bash
# Stack
SKIP_SERVICES=
POSTGRES_PASSWORD=lead_os_dev

# Compartidos (obligatorios)
INTER_SERVICE_SECRET=dev-inter-service-secret-change-me
ENVIRONMENT=local

# JWT de usuarios
SECRET_KEY=dev-secret-key-change-me-0123456789
DESK_SECRET_KEY=dev-desk-secret-change-me
HUB_SECRET_KEY=dev-hub-secret-change-me
NEST_SECRET_KEY=dev-nest-secret-change-me

# auth-service
FERNET_KEY=
BCRYPT_PEPPER=

# tenant-service (Cloudflare)
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ZONE_ID=
CLOUDFLARE_ACCOUNT_ID=
BASE_DOMAIN=airedesk.com
CNAME_TARGET=

# users-service
WEBHOOK_API_KEY=dev-webhook-key
GOOGLE_CREDENTIALS_JSON=

# files-service
STORAGE_PATH=./storage

# gateway
MEDIA_ROOT=./media
FRONTEND_URL=http://localhost:3000
RATE_LIMIT_PER_MINUTE=100
```

- [ ] **Step 3: Validar el compose**

```bash
docker compose config -q && echo COMPOSE VALID
```
Expected: sin errores de sintaxis/interpolación.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: docker-compose de desarrollo (postgres+redis+gateway+4 servicios, profiles)"
```

### Task 35: Makefile + smoke de integración

**Files:**
- Create: `Makefile` (raíz)

**Interfaces:**
- Consumes: compose de Task 34.
- Produces: `make up` / `make down` / `make prune` (nada más), exclusión vía `SKIP_SERVICES` del `.env`.

- [ ] **Step 1: Crear `Makefile`**

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

- [ ] **Step 2: Smoke de integración completo (manual, checklist ejecutable)**

```bash
cp .env.example .env
make up
```
Verificar EN ORDEN (cada comando debe cumplir lo esperado):
1. `docker compose ps` — postgres/redis healthy, gateway + 4 servicios up.
2. Migraciones: `for svc in auth-service tenant-service users-service files-service; do docker compose exec $svc uv run alembic upgrade head; done` — cada una aplica `initial schema`.
3. `curl -sf http://localhost:8000/health` → `{"status":"ok","service":"api-gateway"}`.
4. `curl -s http://localhost:8000/health/services` → los 4 servicios `healthy: true`.
5. Enforcement (las imágenes slim no traen curl; usar el httpx del venv del servicio): `docker compose exec auth-service uv run python -c "import httpx; r=httpx.post('http://localhost:8001/api/auth/login'); print(r.status_code)"` → `401` (sin service-token, incluso dentro de la red).
6. `curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/auth/login` → distinto de 000/502 (el gateway proxifica: 4xx esperado por credenciales vacías, NO 502).
7. SKIP: añadir `SKIP_SERVICES=files-service` al `.env`, `make down && make up` → `docker compose ps` NO muestra files-service; `curl -s http://localhost:8000/health/services` lo reporta `healthy: false`.
8. Event-driven e2e: registrar un usuario por el gateway (`POST /api/auth/register` con payload válido) → `docker compose exec redis redis-cli XLEN events:auth` → ≥1; logs de users-service muestran el handler procesándolo (`docker compose logs users-service | grep -i registered` o perfil creado en users_db: `docker compose exec postgres psql -U lead_os -d users_db -c "\dt"`).
9. `make down` — contenedores apagados. `make up` — vuelve sin rebuild innecesario.
10. `make prune` — `docker volume ls | grep lead-os` vacío.

Si algo falla: corregir la causa raíz (NO el checklist) y repetir desde el paso 1 tras `make prune`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: Makefile de desarrollo (up/down/prune con SKIP_SERVICES)"
```

---

# FASE 5 — Documentación

### Task 36: README.md

**Files:**
- Create: `README.md` (raíz)

**Interfaces:**
- Consumes: todo lo construido.
- Produces: documentación de arquitectura + runbooks local/producción + convenciones.

- [ ] **Step 1: Escribir `README.md` con esta estructura exacta**

1. **Título + descripción** (monorepo de microservicios lead_os; stack: FastAPI 3.12, uv, Postgres, Redis Streams, Docker).
2. **Arquitectura**: diagrama ASCII `cliente → api-gateway:8000 (único puerto) → auth/tenant/users/files → DBs propias + Redis (cache+streams)`; párrafos: (a) gateway FastAPI: valida JWT usuario, inyecta service-token + headers de identidad, rate limit, proxy con retry; (b) enforcement: los servicios rechazan (401) todo sin `X-Service-Token` válido + red interna sin puertos publicados; (c) `shared/`: qué contiene (config, db, alembic, auth, events, cache, utils) y cómo se instala (path dep editable); (d) datos: DB por servicio, cross-reads con rol `readonly` + `readonly_dependency`, migraciones por servicio con patrón compartido `shared.alembic`; (e) eventos: Redis Streams `events:<domain>`, consumer groups, DLQ, ejemplo real `user.registered` (auth → users); (f) MVC+Facade: estructura de carpetas y las 7 reglas de la Fase 3 del plan (resumidas).
3. **Requisitos**: Docker + Docker Compose v2, make, uv (solo para correr sin Docker).
4. **Desarrollo local**: `cp .env.example .env` → rellenar → `make up`; tabla de comandos (`make up/down/prune`); `SKIP_SERVICES`; migraciones (`docker compose exec <svc> uv run alembic upgrade head` + cómo generar nuevas con `revision --autogenerate`); tests (`cd services/<svc> && uv run pytest` / `cd shared && uv run pytest`); hot reload (editar código → reload automático); cómo depurar un servicio por dentro (`docker compose exec <svc> bash`).
5. **Producción**: build por servicio `docker build -f services/<svc>/Dockerfile -t registry/lead-os-<svc>:<tag> .` (contexto = raíz); tabla de variables de entorno requeridas por servicio (de los Settings: SERVICE_NAME, DATABASE_URL, REDIS_URL, INTER_SERVICE_SECRET + específicas); paso de migraciones en el deploy (`alembic upgrade head` como job/comando one-off ANTES del rollout); red: solo el gateway expuesto; rotación de secretos (`INTER_SERVICE_SECRET`, claves JWT); NO Supabase — Postgres propio.
6. **Convenciones**: cómo añadir un endpoint (schema → service → controller → router → test); cómo publicar/consumir un evento nuevo (envelope, publish post-commit, handler idempotente, registrar en `app/events.py`); cómo añadir un microservicio nuevo (checklist: pyproject+path dep, alembic.ini+migrations, Dockerfile+Dockerfile.dev, compose con profile, ruta en gateway `service_routes`, tests).

- [ ] **Step 2: Verificar el README contra la realidad** (cada comando mencionado existe: make targets, rutas de archivos, nombres de scripts). Commit:

```bash
git add README.md && git commit -m "docs: README con arquitectura, runbooks local/prod y convenciones"
```

### Task 37: Verificación final transversal

**Files:**
- Modify: lo que haga falta corregir.

- [ ] **Step 1: Todas las suites de tests**

```bash
cd shared && uv run pytest -q && cd ..
for svc in api-gateway auth-service tenant-service users-service files-service; do
  (cd services/$svc && uv run pytest -q) || exit 1
done
```
Expected: 5 suites verdes + shared.

- [ ] **Step 2: Auditoría de restos prohibidos**

```bash
grep -rn "create_all\|SET LOCAL\|rls_policies\|requirements.txt\|celery\|resend\|asyncpg\|traefik" \
  --include="*.py" --include="*.toml" --include="*.yml" services/ shared/ infra/ docker-compose.yml || echo CLEAN
grep -rn "verify_token\|_decode_bearer\|get_tenant_db" --include="*.py" services/ || echo CLEAN
ls services/*/Dockerfile services/*/Dockerfile.dev services/*/pyproject.toml services/*/uv.lock services/*/alembic.ini
```
Expected: CLEAN + CLEAN + todos los archivos presentes (5 servicios × 4 archivos).

- [ ] **Step 3: Smoke compose repetido desde cero**

`make prune && cp .env.example .env && make up` + repetir checklist de Task 35 Step 2 puntos 1-6. `make down`.

- [ ] **Step 4: Commit final**

```bash
git add -A && git commit -m "chore: verificación final del restructure" || echo "nada que commitear"
```









