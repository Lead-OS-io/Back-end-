# lead_os — Clean Slate: Eliminación de endpoints, reestructura y nuevo `POST /api/auth/onboarding`

**Fecha:** 2026-08-05
**Estado:** Borrador para revisión
**Sustituye / complementa:** `docs/superpowers/specs/2026-08-03-lead-os-restructure-design.md`

---

## Contexto

`lead_os` es un clon temprano de otro proyecto (Aria). El primer spec (`2026-08-03-lead-os-restructure-design.md`) logró sentar las bases correctas: monorepo con `pyproject.toml` por servicio, `shared/` como paquete instalable, API gateway FastAPI, MVC + Facade, eventos con Redis Streams, tests con TDD.

Sin embargo, persisten dos problemas:

1. **Sopa de endpoints heredados.** Los servicios aún exponen el grueso del contrato original (auth: 19 endpoints, users: 22 endpoints, files: 6 endpoints, tenant: 14 endpoints). Casi todo eso es "spaghetti" del proyecto Aria: entidades de calendario, requests genéricos tipo workflow, login attempts, Google OAuth, gestión de dominios en Cloudflare, etc.
2. **El proyecto es nuevo y las migraciones iniciales ya no aplican.** Las migraciones `0001_initial_*` de cada servicio reflejan el schema heredado completo. Como todavía no hay datos reales, las borramos y las reemplazamos por una migración mínima que refleje el nuevo dominio.

La **única superficie pública nueva que entra en producción** es `POST /api/auth/onboarding`, que crea un `User` + un `Tenant` automáticamente vía una cadena de 3 eventos. No hay segunda oleada de endpoints aún.

---

## Objetivo

Dejar cada microservicio con una superficie mínima, eliminando el legado y dejando únicamente:

- `/health` por servicio.
- `/api/openapi.json` y `/api/docs` agregados en el gateway (los servicios NO exponen docs propios).
- `POST /api/auth/onboarding` (auth) — único endpoint nuevo.
- Una cadena de eventos cross-service para crear `Tenant` a partir del onboarding.

Tras la limpieza, los 3 servicios con estado quedan así:

| Servicio | Modelos | Endpoints | Eventos |
|---|---|---|---|
| auth-service | `User` (mínimo) | `POST /api/auth/onboarding` (+ `/health`) | PUB `onboarding.pending`, `onboarding.completed`; CONSUME `tenant.created` |
| tenant-service | `Tenant` (mínimo) | `/health` + `/api/tenants/resolve` (interno, usado por auth en chain) | CONSUME `onboarding.pending`; PUB `tenant.created` |
| files-service | `MediaResources` + 2 enums | `/health` | — |

(`api-gateway` y `users-service` quedan como cascarones: gateway expone `/health`, `/health/services`, `/api/openapi.json`, `/api/docs`, `/media`, `/tutorials`, `/{full_path:path}`; users-service queda **completamente vacío de modelo y router**, pero su cascarón (`main.py` con `/health` + `config.py`) se mantiene para integración futura.)

---

## Decisiones de diseño

| # | Decisión | Elección |
|---|----------|----------|
| 1 | Estrategia de borrado | **Drop Everything & Rebuild Small (Opción A)**. Borrar migraciones iniciales + archivos de modelos/schemas/services heredados, reemplazarlos por una migración `0001_initial.py` por servicio. |
| 2 | Forma de organización de modelos | **`app/models/entities.py`** (clases SQLModel con columnas, FKs, índices) + **`app/models/enums.py`** (enums de Pydantic/SQLAlchemy). Garantiza centralización pero separación clara entre lógica de columnas y valores discretos. |
| 3 | Sobrevivencia de archivos con lógica muerta | **Borrar cuando sea seguro; archivar lo reutilizable.** `tenant-service`: `services/cloudflare.py`, partes de dominios en `services/tenants.py`, schemas relacionados, controllers y router de dominios → `app/_archived/cloudflare_domains/` con `README.md` explicando cómo restaurar. **No** se importan desde el código vivo. |
| 4 | Forma de la transacción cross-service | **Cadena de 3 eventos** vía Redis Streams: `onboarding.pending` → tenant-service crea tenant → `tenant.created` → auth-service asigna `tenant_id` al User → `onboarding.completed`. Esto es asíncrono y desacoplado. (El usuario explícitamente pidió esta forma para soportar un futuro notifications-service que consuma `onboarding.completed`.) |
| 5 | Reparto de campos en el payload del onboarding | **Solo lo personal va a `User`** (id, email, password_hash, full_name, phone, tenant_id). **Lo de negocio va a `Tenant`** (business_name, timezone, legal_name, support_inbox, name, slug, status). |
| 6 | Convención del endpoint onboarding | Body: `OnboardingRequest`. Respuesta 202 (Accepted) con `{"user_id": "...", "status": "pending"}` — **no espera al tenant**. El cliente recibirá la confirmación cuando el flujo termine, vía el futuro notifications-service. Idempotencia por `email` (constraint UNIQUE en `users.email`). |
| 7 | Convención de modelos en Tenant | Borrar campos `custom_domain`, `domain_status`, `cloudflare_*`, `settings/branding/limits/features` (JSON). Mantener `status` (TRIAL/ACTIVE/SUSPENDED/CANCELLED), `is_active`, `slug`, `business_name`, `timezone`, `legal_name`, `support_inbox`. Eliminar la tabla `tenant_domains` y los enums `tenantstatus`/`domainstatus`. |
| 8 | Convención de modelos en User | Borrar todos los campos excepto `id`, `tenant_id`, `email`, `password_hash`, `full_name`, `phone`, `created_at`, `modified_at`. Borrar las tablas `google_oauth_tokens`, `auth_refresh_tokens`, `auth_login_attempts`. |
| 9 | Convención de modelos en File | Borrar todo (tabla `files`, `File`, `FileInfo`, `FileUpload`, etc.). Crear tabla nueva `media_resources` con `MediaResources` (entidad) y `MediaType` + `MediaPurpose` (enums). |
| 10 | Convención de modelos en users-service | Borrar `users`, `calendar`, `user_requests`, sus modelos, schemas, serializers, services, controller, router, events.py, tests. Servicio queda como cascarón (sin ningún `app/models/`). |
| 11 | Manejo de errores en el flujo de eventos | Si `tenant-service` falla al crear Tenant tras recibir `onboarding.pending`, el evento va a DLQ (`events:onboarding:dlq`). auth-service NO asigna tenant_id, el user queda huérfano. Se documenta en `app/_archived/_runbook.md` cómo recuperar. (No hay retry automático desde auth-service; el operador decide.) |
| 12 | Tests | TDD en shared (ya existente). Para auth/tenant: test de contrato del endpoint + test unitario de cada uno de los 3 handlers de eventos (con `session_factory` mockeada). Para files: no hay tests aún (no hay lógica). |

---

## Cambios por servicio

### 1. auth-service

**Archivos a borrar:**
- `app/models/google.py`
- `app/models/tokens.py`
- `app/schemas/auth.py`
- `app/schemas/google.py`
- `app/schemas/user.py`
- `app/serializers/user.py`
- `app/services/auth.py`
- `app/services/security.py`
- `app/services/google_oauth.py`
- `migrations/versions/*.py` (todas las migraciones existentes)
- `tests/test_router_contract.py`, `tests/test_services.py`, `tests/test_events.py`

**Archivos a crear:**

`app/models/enums.py`:
```python
from enum import Enum

class UserStatus(str, Enum):
    PENDING_TENANT = "pending_tenant"
    ACTIVE = "active"
    DISABLED = "disabled"
```

`app/models/entities.py`:
```python
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import UserStatus


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(default=None, index=True, nullable=True)
    email: str = Field(unique=True, index=True, max_length=255, nullable=False)
    password_hash: Optional[str] = Field(default=None, max_length=255, nullable=True)
    full_name: Optional[str] = Field(default=None, max_length=255, nullable=True)
    phone: Optional[str] = Field(default=None, max_length=32, nullable=True)
    status: UserStatus = Field(default=UserStatus.PENDING_TENANT, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
```

`app/schemas/onboarding.py`:
```python
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserStatus


class OnboardingRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    business_name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(min_length=1, max_length=64)
    legal_name: str = Field(min_length=1, max_length=255)
    support_inbox: str = Field(min_length=1, max_length=255)


class OnboardingAcceptedResponse(BaseModel):
    user_id: UUID
    status: UserStatus = UserStatus.PENDING_TENANT
```

`app/services/onboarding.py`:
```python
"""
Onboarding service: crea User (sin tenant), publica onboarding.pending.
"""
import json
import logging
import uuid

from passlib.context import CryptContext
from sqlmodel import Session, select

from app.models.entities import User
from app.models.enums import UserStatus
from app.schemas.onboarding import OnboardingRequest
from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def start_onboarding(*, db: Session, data: OnboardingRequest) -> User:
    existing = db.exec(select(User).where(User.email == data.email)).first()
    if existing:
        from shared.utils.exceptions import ConflictError
        raise ConflictError("email already registered")

    user = User(
        id=uuid.uuid4(),
        tenant_id=None,
        email=data.email,
        password_hash=_pwd.hash(data.password),
        full_name=data.name,
        phone=data.phone,
        status=UserStatus.PENDING_TENANT,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def publish_pending(event_bus, user: User, data: OnboardingRequest) -> str:
    return event_bus.publish("onboarding", EventEnvelope(
        type="onboarding.pending",
        aggregate_id=str(user.id),
        tenant_id=None,
        payload={
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "business_name": data.business_name,
            "legal_name": data.legal_name,
            "support_inbox": data.support_inbox,
            "timezone": data.timezone,
        },
    ))


def handle_tenant_created(event: EventEnvelope, *, db: Session) -> None:
    """
    auth-service consume tenant.created y asigna tenant_id al User.
    Después publica onboarding.completed.
    """
    user_id = uuid.UUID(event.aggregate_id)
    user = db.get(User, user_id)
    if not user:
        logger.warning("user %s not found, skipping", user_id)
        return
    if user.tenant_id is not None:
        logger.info("user %s already has tenant, skipping", user_id)
        return
    user.tenant_id = uuid.UUID(event.payload["tenant_id"])
    user.status = UserStatus.ACTIVE
    db.commit()
```

`app/events.py`:
```python
from typing import Callable
from uuid import UUID

from sqlmodel import Session
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

from app.services.onboarding import handle_tenant_created as _handle_tenant_created


def build_handlers(session_factory) -> dict[str, EventHandler]:
    def _factory(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            _handle_tenant_created(event, db=session)
        finally:
            session.close()

    return {
        "tenant.created": _factory,
    }
```

`app/router.py` (replace):
```python
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from shared.db.engine import get_db
from shared.events.bus import EventBus

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


@router.post("/onboarding", response_model=OnboardingAcceptedResponse, status_code=202)
def onboarding(data: OnboardingRequest, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings),
               event_bus: EventBus = Depends(get_event_bus)) -> OnboardingAcceptedResponse:
    return controller.onboarding(data=data, db=db, settings=settings, event_bus=event_bus)
```

`app/controller.py` (replace):
```python
from sqlmodel import Session

from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from app.services.onboarding import publish_pending, start_onboarding
from shared.events.bus import EventBus


def onboarding(*, data: OnboardingRequest, db: Session, settings, event_bus: EventBus) -> OnboardingAcceptedResponse:
    user = start_onboarding(db=db, data=data)
    publish_pending(event_bus=event_bus, user=user, data=data)
    return OnboardingAcceptedResponse(user_id=user.id, status=user.status)
```

`app/models/__init__.py`:
```python
from app.models.entities import User
from app.models.enums import UserStatus

__all__ = ["User", "UserStatus"]
```

`migrations/versions/0001_initial.py`: crea la tabla `users` con todas sus columnas + índices.

`app/main.py`: añade el `Consumer` con `domain="onboarding"`, `group="auth-service"`, `handlers=build_handlers(session_factory)`. Mismo patrón que users-service usa hoy para consumir `auth:user.registered`.

### 2. tenant-service

**Archivos a borrar:**
- `app/models/domain.py`
- `app/serializers/`
- `migrations/versions/*.py`
- `tests/test_router_contract.py`

**Archivos a mover a `app/_archived/cloudflare_domains/`:**
- `app/services/cloudflare.py` (completo) → `_archived/cloudflare_domains/cloudflare.py`
- Sección de dominios de `app/services/tenants.py` → `_archived/cloudflare_domains/tenants_domain.py`
- Schemas de dominio en `app/schemas/tenant.py` → `_archived/cloudflare_domains/schemas.py`
- Endpoints `domains/*` del router → `_archived/cloudflare_domains/router_excerpt.md`
- Endpoints `domains/*` del controller → `_archived/cloudflare_domains/controller_excerpt.md`
- `_archived/cloudflare_domains/README.md` explicando cómo restaurar.

**Archivos a crear / reemplazar:**

`app/models/enums.py`:
```python
from enum import Enum


class TenantStatus(str, Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
```

`app/models/entities.py`:
```python
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.enums import TenantStatus


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    slug: str = Field(max_length=63, unique=True, index=True, nullable=False)

    business_name: str = Field(max_length=255, nullable=False)
    timezone: str = Field(max_length=64, nullable=False)
    legal_name: str = Field(max_length=255, nullable=False)
    support_inbox: str = Field(max_length=255, nullable=False)

    status: TenantStatus = Field(default=TenantStatus.TRIAL, index=True)
    is_active: bool = Field(default=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
```

`app/services/onboarding.py`:
```python
"""
Tenant-side handler de onboarding.pending. Crea Tenant + publica tenant.created.
"""
import uuid

from sqlmodel import Session, select

from app.models.entities import Tenant
from app.models.enums import TenantStatus
from shared.events.envelope import EventEnvelope


def handle_onboarding_pending(event: EventEnvelope, *, db: Session) -> str:
    """
    Genera slug estable desde business_name + uuid corto para unicidad.
    Crea Tenant en TRIAL y publica tenant.created con aggregate_id = tenant.id
    y payload con user_id y tenant_id.
    """
    payload = event.payload
    business = payload["business_name"]
    base_slug = business.lower().replace(" ", "-").replace("--", "-")[:32].strip("-")
    suffix = uuid.uuid4().hex[:6]
    slug = f"{base_slug}-{suffix}"

    tenant = Tenant(
        id=uuid.uuid4(),
        name=business,
        slug=slug,
        business_name=business,
        timezone=payload["timezone"],
        legal_name=payload["legal_name"],
        support_inbox=payload["support_inbox"],
        status=TenantStatus.TRIAL,
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return str(tenant.id)
```

`app/events.py`:
```python
import logging

from sqlmodel import Session
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

from app.services.onboarding import handle_onboarding_pending

logger = logging.getLogger(__name__)


def build_handlers(session_factory, event_bus: EventBus) -> dict[str, EventHandler]:
    def _factory(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            tenant_id = handle_onboarding_pending(event, db=session)
            event_bus.publish("onboarding", EventEnvelope(
                type="tenant.created",
                aggregate_id=event.payload["user_id"],
                tenant_id=tenant_id,
                payload={
                    "user_id": event.payload["user_id"],
                    "tenant_id": tenant_id,
                    "tenant_slug": None,
                },
            ))
        finally:
            session.close()

    return {
        "onboarding.pending": _factory,
    }
```

`app/schemas/__init__.py`: se reemplaza por un `__init__.py` vacío (no hay schemas públicos vivos — todos los consumers son eventos). Si más adelante se necesita, se crea.

`app/router.py` (replace): solo deja:
```python
from fastapi import APIRouter

router = APIRouter()

# (vacío por ahora — los endpoints /resolve, /tenants, etc. se restauran desde _archived cuando se necesiten)
```

`app/controller.py` (replace): vacío (no hay endpoints vivos).

`app/main.py`: añade el `Consumer` con `domain="onboarding"`, `group="tenant-service"`, `block_ms=5000`. Mismo patrón.

`migrations/versions/0001_initial.py`: crea la tabla `tenants` con todas sus columnas + índices (incluyendo UNIQUE en `slug`).

### 3. files-service

**Archivos a borrar:**
- `app/controller.py`
- `app/router.py`
- `app/models/file.py`
- `app/schemas/`
- `app/serializers/`
- `app/services/`
- `migrations/versions/*.py`
- `tests/`

**Archivos a crear:**

`app/models/enums.py`:
```python
import enum


class MediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class MediaPurpose(str, enum.Enum):
    PRODUCT_IMAGE = "product_image"
    CATEGORY_IMAGE = "category_image"
    PROFILE_PHOTO = "profile_photo"
    PAYMENT_RECEIPT = "payment_receipt"
    BANNER_VIDEO = "banner_video"
    OTHER = "other"
```

`app/models/entities.py`:
```python
import uuid
from typing import Optional

from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.enums import MediaPurpose, MediaType


class MediaResources(SQLModel, table=True):
    __tablename__ = "media_resources"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    original_filename: str = Field(nullable=False)
    media_type: MediaType = Field(
        sa_column=Field(sa_type=SAEnum(MediaType, name="media_type"), nullable=False, index=True)
    )
    purpose: MediaPurpose = Field(
        default=MediaPurpose.OTHER,
        sa_column=Field(sa_type=SAEnum(MediaPurpose, name="media_purpose"), nullable=False, index=True),
    )
    mimetype: str = Field(nullable=False)
    format: str = Field(nullable=False)
    size_bytes: int = Field(sa_type=BigInteger, nullable=False)

    bucket: str = Field(nullable=False)
    path: str = Field(nullable=False)
    is_public: bool = Field(default=False, nullable=False, index=True)

    duration: Optional[int] = Field(default=None, nullable=True)
    meta: dict = Field(
        default_factory=dict,
        sa_type=JSONB,
        sa_column_kwargs={"name": "metadata"},
        nullable=False,
    )
    sort_order: Optional[int] = Field(default=None, nullable=True, sa_column_kwargs={"server_default": "0"})
```

`migrations/versions/0001_initial.py`: crea tabla `media_resources` + los enums `media_type` y `media_purpose`.

`app/router.py` y `app/controller.py`: **borrados**. El servicio expone solo `/health` desde `main.py`.

`app/main.py`: deja solo `/health` (sin router, sin eventos).

### 4. users-service

**Archivos a borrar:**
- `app/controller.py`
- `app/router.py`
- `app/models/` (entero)
- `app/schemas/` (entero)
- `app/serializers/` (entero)
- `app/services/` (entero)
- `app/events.py`
- `migrations/versions/*.py`
- `tests/`

**Archivos a dejar:**
- `app/__init__.py`
- `app/config.py` (existente, se mantiene tal cual; configuración del servicio)
- `app/main.py` (modificado: solo `/health` + `create_app` mínimo)

**`app/main.py` (replace):**
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from shared.auth.middleware import ServiceTokenMiddleware
from shared.db.engine import create_service_engine, get_session_factory
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        app.state.session_factory = get_session_factory(engine)
        app.state.settings = settings
        yield
        engine.dispose()

    app = FastAPI(title="users-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
```

### 5. api-gateway

**Sin cambios estructurales.** Solo se ajusta el route prefix en `app/config.py` para que `/api/auth` apunte al nuevo endpoint único `onboarding` (quitando `/login`, `/register`, `/token`, `/refresh`, etc. que ya no existen). El gateway reenvía `/api/auth/*` completo, así que ningún cambio de routing es necesario — al dejar de existir los endpoints viejos, el reenvío devolverá `404` desde auth-service y el gateway lo propaga. Mantiene `/health`, `/health/services`, `/api/openapi.json`, `/api/docs`, `/media`, `/tutorials`, `/{full_path:path}`.

---

## Flujo end-to-end de `POST /api/auth/onboarding`

```
cliente
  │ POST /api/auth/onboarding { email, password, name, phone,
  │                                business_name, timezone,
  │                                legal_name, support_inbox }
  ▼
api-gateway ──► auth-service.controller.onboarding
                  ├─ start_onboarding:  crea User (status=PENDING_TENANT, tenant_id=None)
                  ├─ event_bus.publish("onboarding", EventEnvelope(
                  │     type="onboarding.pending",
                  │     aggregate_id=user.id, payload={user_id, email, full_name,
                  │       phone, business_name, legal_name, support_inbox, timezone}))
                  └─ return 202 { user_id, status: "pending_tenant" }

(redis stream "events:onboarding")

                 ▼ consumer tenant-service (group="tenant-service")

tenant-service.handle_onboarding_pending
  ├─ genera slug desde business_name
  ├─ crea Tenant (status=TRIAL) ─► commit
  └─ event_bus.publish("onboarding", EventEnvelope(
        type="tenant.created",
        aggregate_id=user_id, payload={ user_id, tenant_id, tenant_slug }))

                 ▼ consumer auth-service (group="auth-service")

auth-service.handle_tenant_created
  ├─ carga User(aggregate_id)
  ├─ asigna tenant_id, status=ACTIVE ─► commit
  └─ (NO publica otro evento aquí; será el último.)

(Final del flujo. El user está ACTIVO con tenant asignado.)

(futuro) consumer notifications-service consume "onboarding.completed"
   — pero ese evento todavía NO se publica al final de este spec.
   Para que la cadena termine con `onboarding.completed` (no `tenant.created`),
   se publicará desde auth-service.handle_tenant_created al final del flujo.
```

**Decisión**: auth-service, al final de `handle_tenant_created`, **publica `onboarding.completed`** además de actualizar el User. Esto da un evento terminal que el futuro notifications-service podrá escuchar. Payload: `{ user_id, tenant_id, email, full_name, business_name, timezone, support_inbox }`. NO se publica si la actualización del User falla (idempotencia: re-entrega del mismo `tenant.created` no republica).

### Forma final de los handlers

`auth-service/handle_tenant_created` actualizado:
```python
def handle_tenant_created(event: EventEnvelope, *, db: Session, event_bus: EventBus) -> None:
    user_id = uuid.UUID(event.aggregate_id)
    user = db.get(User, user_id)
    if not user:
        logger.warning("user %s not found", user_id)
        return
    if user.status == UserStatus.ACTIVE:
        logger.info("user %s already active, skipping (idempotent)", user_id)
        return
    user.tenant_id = uuid.UUID(event.payload["tenant_id"])
    user.status = UserStatus.ACTIVE
    db.commit()
    event_bus.publish("onboarding", EventEnvelope(
        type="onboarding.completed",
        aggregate_id=str(user.id),
        tenant_id=str(user.tenant_id),
        payload={
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "full_name": user.full_name,
            "business_name": event.payload.get("business_name", ""),
            "timezone": event.payload.get("timezone", ""),
            "support_inbox": event.payload.get("support_inbox", ""),
        },
    ))
```

Nota: el handler ahora necesita `event_bus`. La factory de handlers en `auth-service/app/events.py` lo resuelve inyectándolo desde `app.state.event_bus` en `main.py`:
```python
consumer = Consumer(
    settings.REDIS_URL,
    domain="onboarding",
    group="auth-service",
    consumer_name=f"auth-service-{settings.SERVICE_NAME}",
    handlers=build_handlers(session_factory, app.state.event_bus),
    block_ms=5000,
)
```

---

## Manejo de errores y DLQ

- Si `tenant-service` falla en `handle_onboarding_pending` (DB error, etc.), el `Consumer` ya incrementa deliveries y al llegar a 5 lo manda a `events:onboarding:dlq`. **NO** se reintenta automáticamente desde auth-service.
- Si `auth-service` falla en `handle_tenant_created`, mismo flujo DLQ.
- El User queda en `status=PENDING_TENANT` si el flujo se interrumpe. Un operador puede revisar la DLQ y reprocesar manualmente (script de reapunteo se documenta en `_archived/_runbook.md`).
- `409 ConflictError`: email duplicado en `POST /api/auth/onboarding` retorna 409 (mapeo ya existe en `shared.utils.exceptions.ConflictError`).

---

## Convención actualizada: modelos y enums centralizados pero separados

Aplica a **los 3 servicios que tienen estado** (auth, tenant, files):

- `app/models/__init__.py`: reexporta `entities` y `enums` para que el resto del código haga `from app.models import X`.
- `app/models/entities.py`: SOLO clases `SQLModel, table=True`. Cada `User`/`Tenant`/`MediaResources` con sus columnas, FKs, índices, defaults, validators. El archivo docstring al inicio indica "todas las entidades del servicio viven aquí".
- `app/models/enums.py`: SOLO `enum.Enum`/`str, enum.Enum`. Cero imports de SQLAlchemy. Cero modelos.

Regla: si en una code review alguien añade un enum dentro de `entities.py` o un modelo dentro de `enums.py`, es un fail de convención.

---

## Plan de tests

### auth-service
- `tests/test_onboarding_endpoint.py` — contrato:
  - `202` con body válido.
  - `409` con email duplicado.
  - `422` con password corto, `name` vacío, timezone/email mal formados, etc.
- `tests/test_start_onboarding.py` — unit: inserta User en DB, status=PENDING_TENANT, password hasheado (no plano).
- `tests/test_handle_tenant_created.py` — unit: marca User como ACTIVE con tenant_id. `event_bus.publish` se llama con `onboarding.completed` y los campos correctos.
- `tests/test_idempotency.py` — segundo `tenant.created` para el mismo user_id no republica ni rompe.

### tenant-service
- `tests/test_handle_onboarding_pending.py` — unit: crea Tenant con slug derivado, status=TRIAL. `event_bus.publish` se llama con `tenant.created` y `tenant_id`.

### shared
- (sin cambios — ya cubierto)

### Verificación manual
```bash
make up
# esperar a que /health y /health/services estén OK
curl -X POST http://localhost:8000/api/auth/onboarding \
  -H 'Content-Type: application/json' \
  -d '{"email":"founder@acme.com","password":"password123","name":"Ana","phone":"+14155550100",
       "business_name":"Acme Co","timezone":"America/Mexico_City",
       "legal_name":"Acme Co LLC","support_inbox":"support@acme.com"}'
# → 202 { user_id, status: "pending_tenant" }

# Esperar ~2 segundos (redundis stream round-trip)
docker compose exec postgres psql -U lead_os -d auth_db -c "SELECT id, email, status, tenant_id FROM users;"
docker compose exec postgres psql -U lead_os -d tenant_db -c "SELECT id, name, slug, status FROM tenants;"
# auth: status=active, tenant_id=<uuid>
# tenant: 1 fila con slug="acme-co-<6hex>"

docker compose logs -f auth-service | grep onboarding
docker compose logs -f tenant-service | grep onboarding
# Verificar en logs: "onboarding.pending → tenant.created → onboarding.completed"
```

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Breaking change con clientes que ya llamaban `/login`, `/register`, `/me`, etc. | No aplica — el proyecto Aria es la fuente, y esta base todavía no se ha desplegado. Documentar en CHANGELOG (no en README por ahora, porque todavía no hay versión). |
| Email duplicado dispara 409 — clientes que esperaban 201 con auto-login ahora reciben 202 y deben esperar el flujo | Documentar el contrato nuevo en el OpenAPI del gateway. `OnboardingAcceptedResponse.status` indica "pending_tenant" explícitamente. |
| `tenant_id` queda NULL mientras el flujo se procesa (visibilidad operacional) | Endpoint `/health/services` no expone esto. Un endpoint admin de "list pending tenants" puede agregarse en una iteración posterior (no es parte de este spec). |
| `slug` generado por `slugify(business_name) + "-" + uuid4.hex[:6]` puede chocar con uno existente si dos tenants eligen el mismo nombre en el mismo segundo | Imposible por probabilidad (uuid4 hex 6 caracteres = ~16 millones de combinaciones, colisión despreciable). El `UNIQUE` índice lo captura; un retry regenera el sufijo. (No implementado en este spec — YAGNI.) |
| Cambio en `shared.events.envelope` (payload typing) | Sin cambios. |
| `passlib` no está en `pyproject.toml` actualmente | Agregar `passlib[bcrypt]==1.7.4` en `services/auth-service/pyproject.toml`. |
| El consumer en `auth-service` ahora necesita `event_bus` además de `session_factory` | Cambiar firma de `build_handlers(session_factory, event_bus)`. Aceptable. |

---

## Out of scope (decidido en brainstorming, no reabrir)

- Login tradicional (`POST /api/auth/login`). Se reintroduce cuando haya un cliente de vuelta (no este sprint).
- Refresh tokens. Mismo motivo.
- Google OAuth. Eliminado de momento.
- Reset de password. Mismo motivo.
- Calendario y user requests (users-service vacío por ahora).
- Upload/download de archivos (files-service solo tiene el modelo, sin endpoints).
- Endpoints `/api/tenants/resolve`, CRUD de tenants. Restaurables desde `_archived/` cuando se necesiten.
- Notifications-service. Solo se deja el evento `onboarding.completed` listo para él.
- Persistencia del password de `MediaResources`. Lo definirá el spec del upload.
- Tests E2E. Solo contract + unit.

---

## Convención nueva: cómo añadir un endpoint nuevo

Una vez que esta limpieza esté en `main`, futuras adiciones siguen las reglas existentes del primer spec (`docs/superpowers/specs/2026-08-03-lead-os-restructure-design.md`):

- Schema Pydantic en `app/schemas/<feature>.py`.
- Función de negocio en `app/services/<feature>.py`.
- Método en `app/controller.py` (facade).
- Ruta en `app/router.py` con `response_model=`.
- Test de contrato en `tests/test_<feature>.py`.

Para un nuevo `enum`:
- Añadir al `app/models/enums.py` existente **sin** renombrar la convención.

Para una nueva `entity`:
- Añadir al `app/models/entities.py` existente.
- Crear migración Alembic nueva con `uv run alembic revision --autogenerate -m "add_<entity>"`.

---

## Tareas de implementación (resumen, NO completas)

El detalle step-by-step va en `docs/superpowers/plans/2026-08-05-clean-slate-onboarding.md`. Resumen de alto nivel:

1. **auth-service**: borrar archivos muertos; crear `app/models/{enums,entities}.py`; `app/schemas/onboarding.py`; `app/services/onboarding.py`; `app/events.py`; reemplazar `router.py` y `controller.py`; borrar migrations y crear `0001_initial`; añadir `passlib` a `pyproject.toml`; añadir Consumer en `main.py` con dominio `onboarding`; tests.
2. **tenant-service**: borrar archivos muertos; archivar cloudflare/dominios a `_archived/`; crear `app/models/{enums,entities}.py`; `app/services/onboarding.py`; `app/events.py`; reemplazar `router.py`/`controller.py`; borrar migrations y crear `0001_initial`; añadir Consumer en `main.py`; tests.
3. **files-service**: borrar archivos muertos; crear `app/models/{enums,entities}.py`; borrar migrations y crear `0001_initial`; simplificar `main.py` (sin router, sin eventos); tests mínimos (que `import app.main` no rompa y `GET /health` responda).
4. **users-service**: borrar archivos muertos; simplificar `main.py` (sin router, sin eventos, sin engine); tests mínimos.
5. **api-gateway**: sin cambios estructurales — verificar en CI que `service_routes` solo apunte a paths vivos y que `/api/openapi.json` agregue correctamente los 3 servicios vivos.

Cada tarea es independiente y verificable.

---

## Apéndice: dependencias añadidas

- `services/auth-service/pyproject.toml`: agregar `passlib[bcrypt]==1.7.4`.

(El resto de deps ya estaba cubierto por el primer spec.)
