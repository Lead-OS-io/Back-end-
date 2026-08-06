# Clean Slate Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all inherited endpoints and tables from `lead_os` microservices, leaving each service with a minimal, focused surface. Then implement `POST /api/auth/onboarding` with a 3-event chain (`onboarding.pending` → `tenant.created` → `onboarding.completed`) that creates a User and a Tenant via async events.

**Architecture:**
- 4 services keep state (`auth`, `tenant`, `files`, `users`) — only `auth`, `tenant`, `files` have actual models after cleanup.
- All models live under `app/models/entities.py` (SQLModel classes) and `app/models/enums.py` (Python enums). No exceptions.
- All cross-service state changes go through Redis Streams (`events:onboarding`).
- Each service runs an Alembic migration (`0001_initial.py`) that creates ONLY its minimal tables.
- Endpoint response for `POST /api/auth/onboarding` is `202 Accepted` with `{user_id, status: "pending_tenant"}`; the chain continues asynchronously.

**Tech Stack:** Python 3.12, FastAPI 0.104.1, SQLModel 0.0.14, SQLAlchemy 2.0, Alembic 1.12.1, Redis 5.0.1, passlib[bcrypt] 1.7.4, Postgres 16, Docker Compose v2, uv.

**Specification:** `docs/superpowers/specs/2026-08-05-clean-slate-onboarding-design.md` (all decisions trace there).

## Global Constraints

- Project is brand new (no real users); we may DELETE all existing `migrations/versions/*.py` files without data-loss concerns.
- `app/models/` MUST contain exactly two files in services that have state: `entities.py` (only SQLModel classes) and `enums.py` (only `enum.Enum` subclasses). No model or enum goes anywhere else.
- All Alembic migrations follow the pattern in `shared.alembic.env_template` (`run_migrations(get_url, target_metadata)`).
- Existing test runner: `cd services/<svc> && uv run pytest -q`. Tests must pass before commit.
- Services bind only on Docker internal network; `X-Service-Token` middleware blocks direct access except `/health` (and `/openapi.json`/`/docs` if present — they don't exist anymore).
- Lint/format convention: there is no formal linter configured yet. Use `uv run python -c "import app.main"` to validate each service's imports after edits.
- Docker rebuild: each `Dockerfile.dev` runs `uv run alembic upgrade head` on startup. After schema changes, run `make up` to rebuild containers.
- Each task ends with a clean commit. Commit messages follow the pattern `feat|fix|refactor(test)|docs(scope): description`.

---

## Task Index

| # | Task | Service | Purpose |
|---|---|---|---|
| 1 | Cleanup auth-service skeleton | auth-service | Delete dead files, leave cascarón |
| 2 | Auth models (User + UserStatus) | auth-service | Define new minimal schema |
| 3 | Auth Alembic 0001_initial | auth-service | Create `users` table |
| 4 | Auth onboarding schema + service | auth-service | Business logic for `POST /api/auth/onboarding` |
| 5 | Auth router + controller + main (consumer) | auth-service | Wire endpoint + consumer of `tenant.created` |
| 6 | Auth tests (TDD: contract + handlers) | auth-service | Verify endpoint + 2 event handlers |
| 7 | Cleanup tenant-service + archive cloudflare | tenant-service | Move dead logic to `_archived/` |
| 8 | Tenant models (Tenant + TenantStatus) | tenant-service | Define minimal tenant schema |
| 9 | Tenant Alembic 0001_initial | tenant-service | Create `tenants` table |
| 10 | Tenant onboarding service + events | tenant-service | Handler of `onboarding.pending` + publisher |
| 11 | Tenant empty router/controller + main (consumer) | tenant-service | Wire consumer; no endpoints |
| 12 | Tenant tests | tenant-service | Verify handler publishes `tenant.created` |
| 13 | Cleanup files-service | files-service | Delete dead files |
| 14 | Files models (MediaType/MediaPurpose/MediaResources) | files-service | Define schema for media_resources |
| 15 | Files Alembic 0001_initial | files-service | Create `media_resources` + enums |
| 16 | Files main simplified | files-service | `/health` only |
| 17 | Files smoke test | files-service | Verify service starts |
| 18 | Cleanup users-service | users-service | Delete dead files + simplify main |
| 19 | Users-service smoke test | users-service | Verify service starts |
| 20 | End-to-end verification | all | Bring stack up, run onboarding, verify DBs |

---

## Task 1: Cleanup auth-service skeleton

**Files:**
- Delete: `services/auth-service/app/models/google.py`
- Delete: `services/auth-service/app/models/tokens.py`
- Delete: `services/auth-service/app/schemas/auth.py`
- Delete: `services/auth-service/app/schemas/google.py`
- Delete: `services/auth-service/app/schemas/user.py`
- Delete: `services/auth-service/app/serializers/`
- Delete: `services/auth-service/app/services/auth.py`
- Delete: `services/auth-service/app/services/security.py`
- Delete: `services/auth-service/app/services/google_oauth.py`
- Delete: `services/auth-service/migrations/versions/*.py` (all)
- Delete: `services/auth-service/tests/test_router_contract.py`
- Delete: `services/auth-service/tests/test_services.py`
- Delete: `services/auth-service/tests/test_events.py`
- Keep (will be replaced): `services/auth-service/app/models/__init__.py` (rewritten in Task 2), `services/auth-service/app/schemas/__init__.py` (rewritten in Task 4), `services/auth-service/app/services/__init__.py` (rewritten in Task 4)

**Interfaces:**
- Consumes: nothing (pure deletion)
- Produces: empty directories where dead files lived; reduces test suite to only `tests/conftest.py`

- [ ] **Step 1: Delete dead model files**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/auth-service/app/models/google.py
rm services/auth-service/app/models/tokens.py
```

- [ ] **Step 2: Delete dead schema files**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/auth-service/app/schemas/auth.py
rm services/auth-service/app/schemas/google.py
rm services/auth-service/app/schemas/user.py
```

- [ ] **Step 3: Delete dead services and serializers**

```bash
cd /home/carlos/Escritorio/lead_os
rm -rf services/auth-service/app/serializers
rm services/auth-service/app/services/auth.py
rm services/auth-service/app/services/security.py
rm services/auth-service/app/services/google_oauth.py
```

- [ ] **Step 4: Delete dead tests and migrations**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/auth-service/tests/test_router_contract.py
rm services/auth-service/tests/test_services.py
rm services/auth-service/tests/test_events.py
rm services/auth-service/migrations/versions/*.py
```

- [ ] **Step 5: Verify skeleton loads (will fail — that's expected, fixed in next tasks)**

Run: `cd services/auth-service && uv run python -c "from app import main"`
Expected: `ImportError` because `models/__init__.py` still re-exports `google_oauth_tokens` etc. This is fine — Task 2 fixes it.

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/app/ services/auth-service/tests/ services/auth-service/migrations/
git commit -m "refactor(auth): purge legacy schemas/services/handlers for clean slate"
```

---

## Task 2: Auth models (User + UserStatus)

**Files:**
- Replace: `services/auth-service/app/models/__init__.py`
- Create: `services/auth-service/app/models/enums.py`
- Create: `services/auth-service/app/models/entities.py`

**Interfaces:**
- Consumes: nothing
- Produces: `from app.models import User, UserStatus` works; `from app.models.entities import User` works; `from app.models.enums import UserStatus` works.

- [ ] **Step 1: Create `app/models/enums.py`**

Write `services/auth-service/app/models/enums.py`:

```python
from enum import Enum


class UserStatus(str, Enum):
    PENDING_TENANT = "pending_tenant"
    ACTIVE = "active"
    DISABLED = "disabled"
```

- [ ] **Step 2: Create `app/models/entities.py`**

Write `services/auth-service/app/models/entities.py`:

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

- [ ] **Step 3: Replace `app/models/__init__.py`**

Write `services/auth-service/app/models/__init__.py`:

```python
from app.models.entities import User
from app.models.enums import UserStatus

__all__ = ["User", "UserStatus"]
```

- [ ] **Step 4: Verify import works**

Run: `cd services/auth-service && uv run python -c "from app.models import User, UserStatus; print(User, UserStatus)"`
Expected: prints `<class 'app.models.entities.User'>` and `<enum 'UserStatus'>`.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/app/models/
git commit -m "feat(auth): add minimal User model with UserStatus enum"
```

---

## Task 3: Auth Alembic 0001_initial

**Files:**
- Create: `services/auth-service/migrations/versions/0001_initial.py`

**Interfaces:**
- Consumes: `app.models.entities.User` (must register with SQLModel.metadata)
- Produces: `users` table with all 9 columns + UNIQUE index on email + indexes on tenant_id and status

- [ ] **Step 1: Create the migration file**

Write `services/auth-service/migrations/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column("tenant_id", sqlmodel.sql.sqltypes.GUID(), nullable=True),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending_tenant", "active", "disabled", name="userstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_users_status"), "users", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
```

- [ ] **Step 2: Stamp Alembic to current (no migrations applied yet)**

Skip if no DB exists yet — first run via `make up` will run `alembic upgrade head` automatically. To verify locally: `cd services/auth-service && uv run alembic upgrade head` (requires DATABASE_URL env set).

- [ ] **Step 3: Verify downgrade/upgrade roundtrip on a fresh DB**

Run:
```bash
cd services/auth-service
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

Expected: each command exits 0; final state has the `users` table.

- [ ] **Step 4: Verify migration imports cleanly**

Run: `cd services/auth-service && uv run python -c "from migrations.versions import 0001_initial"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/migrations/
git commit -m "feat(auth): alembic 0001_initial creates minimal users table"
```

---

## Task 4: Auth onboarding schema + service

**Files:**
- Replace: `services/auth-service/app/schemas/__init__.py`
- Create: `services/auth-service/app/schemas/onboarding.py`
- Replace: `services/auth-service/app/services/__init__.py`
- Create: `services/auth-service/app/services/onboarding.py`

**Interfaces:**
- Consumes: `OnboardingRequest` from request body; `app.models.entities.User`
- Produces: `OnboardingAcceptedResponse`; `start_onboarding` returns `User`; `publish_pending` returns stream ID; `handle_tenant_created` mutates User and publishes `onboarding.completed`

- [ ] **Step 1: Create `app/schemas/onboarding.py`**

Write `services/auth-service/app/schemas/onboarding.py`:

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

- [ ] **Step 2: Replace `app/schemas/__init__.py`**

Write `services/auth-service/app/schemas/__init__.py`:

```python
from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest

__all__ = ["OnboardingAcceptedResponse", "OnboardingRequest"]
```

- [ ] **Step 3: Create `app/services/onboarding.py`**

Write `services/auth-service/app/services/onboarding.py`:

```python
import logging
import uuid

from passlib.context import CryptContext
from sqlmodel import Session, select

from app.models.entities import User
from app.models.enums import UserStatus
from app.schemas.onboarding import OnboardingRequest
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope
from shared.utils.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def start_onboarding(*, db: Session, data: OnboardingRequest) -> User:
    existing = db.exec(select(User).where(User.email == data.email)).first()
    if existing:
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


def publish_pending(*, event_bus: EventBus, user: User, data: OnboardingRequest) -> str:
    return event_bus.publish(
        "onboarding",
        EventEnvelope(
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
        ),
    )


def handle_tenant_created(
    event: EventEnvelope, *, db: Session, event_bus: EventBus
) -> None:
    user_id = uuid.UUID(event.aggregate_id)
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError(f"user {user_id} not found")

    if user.status == UserStatus.ACTIVE:
        logger.info("user %s already active; skipping idempotently", user_id)
        return

    user.tenant_id = uuid.UUID(event.payload["tenant_id"])
    user.status = UserStatus.ACTIVE
    db.commit()

    event_bus.publish(
        "onboarding",
        EventEnvelope(
            type="onboarding.completed",
            aggregate_id=str(user.id),
            tenant_id=str(user.tenant_id),
            payload={
                "user_id": str(user.id),
                "tenant_id": str(user.tenant_id),
                "email": user.email,
                "full_name": user.full_name,
                "phone": user.phone,
                "business_name": event.payload.get("business_name", ""),
                "timezone": event.payload.get("timezone", ""),
                "support_inbox": event.payload.get("support_inbox", ""),
            },
        ),
    )
```

- [ ] **Step 4: Replace `app/services/__init__.py`**

Write `services/auth-service/app/services/__init__.py`:

```python
from app.services.onboarding import (
    handle_tenant_created,
    publish_pending,
    start_onboarding,
)

__all__ = ["handle_tenant_created", "publish_pending", "start_onboarding"]
```

- [ ] **Step 5: Verify imports**

Run: `cd services/auth-service && uv run python -c "from app.services import start_onboarding, publish_pending, handle_tenant_created; from app.schemas import OnboardingRequest, OnboardingAcceptedResponse; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/app/schemas/ services/auth-service/app/services/
git commit -m "feat(auth): onboarding schemas + service (start, publish_pending, handle_tenant_created)"
```

---

## Task 5: Auth router + controller + main (consumer)

**Files:**
- Replace: `services/auth-service/app/router.py`
- Replace: `services/auth-service/app/controller.py`
- Create: `services/auth-service/app/events.py`
- Replace: `services/auth-service/app/main.py`

**Interfaces:**
- Consumes: `OnboardingRequest`; `EventBus`; consumer from `shared.events.consumer.Consumer`
- Produces: `POST /api/auth/onboarding` endpoint; consumer with `domain="onboarding"`, `group="auth-service"`

- [ ] **Step 1: Create `app/events.py`**

Write `services/auth-service/app/events.py`:

```python
from sqlmodel import Session
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

from app.services.onboarding import handle_tenant_created


def build_handlers(session_factory, event_bus: EventBus) -> dict[str, EventHandler]:
    def _handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            handle_tenant_created(event, db=session, event_bus=event_bus)
        finally:
            session.close()

    return {"tenant.created": _handler}
```

- [ ] **Step 2: Replace `app/controller.py`**

Write `services/auth-service/app/controller.py`:

```python
from sqlmodel import Session

from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from app.services.onboarding import publish_pending, start_onboarding
from shared.events.bus import EventBus


def onboarding(
    *, data: OnboardingRequest, db: Session, settings, event_bus: EventBus
) -> OnboardingAcceptedResponse:
    user = start_onboarding(db=db, data=data)
    publish_pending(event_bus=event_bus, user=user, data=data)
    return OnboardingAcceptedResponse(user_id=user.id, status=user.status)
```

- [ ] **Step 3: Replace `app/router.py`**

Write `services/auth-service/app/router.py`:

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


@router.post(
    "/onboarding",
    response_model=OnboardingAcceptedResponse,
    status_code=202,
)
def onboarding(
    data: OnboardingRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    event_bus: EventBus = Depends(get_event_bus),
) -> OnboardingAcceptedResponse:
    return controller.onboarding(data=data, db=db, settings=settings, event_bus=event_bus)
```

- [ ] **Step 4: Replace `app/main.py`**

Write `services/auth-service/app/main.py`:

```python
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.events import build_handlers
from app.router import router
from shared.auth.middleware import ServiceTokenMiddleware
from shared.cache.client import create_redis
from shared.db.engine import create_service_engine, get_session_factory
from shared.events.bus import EventBus
from shared.events.consumer import Consumer
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        session_factory = get_session_factory(engine)
        redis = create_redis(settings.REDIS_URL)
        event_bus = EventBus(settings.REDIS_URL)
        app.state.session_factory = session_factory
        app.state.redis = redis
        app.state.event_bus = event_bus
        app.state.settings = settings

        consumer = Consumer(
            settings.REDIS_URL,
            domain="onboarding",
            group="auth-service",
            consumer_name=f"auth-service-{settings.SERVICE_NAME}",
            handlers=build_handlers(session_factory, event_bus),
            block_ms=5000,
        )
        thread = threading.Thread(target=consumer.run_forever, daemon=True)
        thread.start()

        yield

        consumer.stop()
        thread.join(timeout=5)
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

- [ ] **Step 5: Verify app imports**

Run: `cd services/auth-service && uv run python -c "from app.main import app; print([r.path for r in app.routes])"`
Expected: prints `/api/auth/onboarding`, `/health`, and `/openapi.json` (FastAPI default).

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/app/
git commit -m "feat(auth): onboarding endpoint + tenant.created consumer"
```

---

## Task 6: Auth tests (TDD: contract + handlers)

**Files:**
- Create: `services/auth-service/tests/test_onboarding_endpoint.py`
- Create: `services/auth-service/tests/test_start_onboarding.py`
- Create: `services/auth-service/tests/test_handle_tenant_created.py`
- Create: `services/auth-service/tests/test_idempotency.py`
- Modify: `services/auth-service/tests/conftest.py` — add `fake_event_bus` fixture and override `get_db` to use SQLite in-memory

**Interfaces:**
- Consumes: existing `conftest.py` fixtures (`identity`, `svc_headers`, `mock_db`)
- Produces: 4 test files that verify endpoint contract and event handlers

- [ ] **Step 1: Replace `conftest.py` with shared fixtures**

Write `services/auth-service/tests/conftest.py`:

```python
import os

os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import User, UserStatus
from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.events.bus import EventBus

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def identity() -> Identity:
    return Identity(user_id="00000000-0000-0000-0000-000000000001",
                    tenant_id="00000000-0000-0000-0000-000000000002",
                    role_id=1, is_superuser=True)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_event_bus(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    bus = EventBus("redis://localhost:6379/15")
    return bus


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


@pytest.fixture
def client(fake_event_bus, db_session):
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[__import__("shared.db.engine", fromlist=["get_db"]).get_db] = lambda: db_session
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="x", tenant_id="x", role_id=None, is_superuser=False
    )
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 2: Create `test_start_onboarding.py`**

Write `services/auth-service/tests/test_start_onboarding.py`:

```python
import uuid

import pytest

from app.services.onboarding import start_onboarding
from app.models import User, UserStatus
from app.schemas.onboarding import OnboardingRequest
from shared.utils.exceptions import ConflictError


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        phone="+14155550100",
        business_name="Acme Co",
        timezone="America/Mexico_City",
        legal_name="Acme Co LLC",
        support_inbox="support@acme.com",
    )
    base.update(over)
    return OnboardingRequest(**base)


def test_creates_user_pending_tenant(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    assert user.id is not None
    assert isinstance(user.id, uuid.UUID)
    assert user.tenant_id is None
    assert user.email == "founder@acme.com"
    assert user.full_name == "Ana Founder"
    assert user.phone == "+14155550100"
    assert user.status == UserStatus.PENDING_TENANT


def test_password_is_hashed_not_plain(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    assert user.password_hash is not None
    assert user.password_hash != "password123"
    assert user.password_hash.startswith("$2")  # bcrypt


def test_duplicate_email_raises_conflict(db_session):
    start_onboarding(db=db_session, data=_payload())
    with pytest.raises(ConflictError):
        start_onboarding(db=db_session, data=_payload())
```

- [ ] **Step 3: Create `test_onboarding_endpoint.py`**

Write `services/auth-service/tests/test_onboarding_endpoint.py`:

```python
def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        phone="+14155550100",
        business_name="Acme Co",
        timezone="America/Mexico_City",
        legal_name="Acme Co LLC",
        support_inbox="support@acme.com",
    )
    base.update(over)
    return base


def test_returns_202_with_pending_status(client):
    resp = client.post("/api/auth/onboarding", json=_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert "user_id" in body
    assert body["status"] == "pending_tenant"


def test_duplicate_email_returns_409(client):
    client.post("/api/auth/onboarding", json=_payload())
    resp = client.post("/api/auth/onboarding", json=_payload())
    assert resp.status_code == 409


def test_short_password_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(password="short"))
    assert resp.status_code == 422


def test_missing_business_name_returns_422(client):
    payload = _payload()
    payload.pop("business_name")
    resp = client.post("/api/auth/onboarding", json=payload)
    assert resp.status_code == 422


def test_invalid_email_returns_422(client):
    resp = client.post("/api/auth/onboarding", json=_payload(email="not-an-email"))
    assert resp.status_code == 422
```

- [ ] **Step 4: Create `test_handle_tenant_created.py`**

Write `services/auth-service/tests/test_handle_tenant_created.py`:

```python
import uuid
from unittest.mock import MagicMock

from app.models import User, UserStatus
from app.services.onboarding import handle_tenant_created, start_onboarding
from app.schemas.onboarding import OnboardingRequest
from shared.events.envelope import EventEnvelope


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        phone="+14155550100",
        business_name="Acme Co",
        timezone="America/Mexico_City",
        legal_name="Acme Co LLC",
        support_inbox="support@acme.com",
    )
    base.update(over)
    return OnboardingRequest(**base)


def test_assigns_tenant_and_marks_active(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id=str(user.id),
        tenant_id="00000000-0000-0000-0000-000000000099",
        payload={"tenant_id": "00000000-0000-0000-0000-000000000099",
                 "business_name": "Acme Co",
                 "timezone": "America/Mexico_City",
                 "support_inbox": "support@acme.com"},
    )
    bus = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus)

    db_session.refresh(user)
    assert user.tenant_id == uuid.UUID("00000000-0000-0000-0000-000000000099")
    assert user.status == UserStatus.ACTIVE
    bus.publish.assert_called_once()
    args = bus.publish.call_args
    assert args[0][0] == "onboarding"
    envelope: EventEnvelope = args[0][1]
    assert envelope.type == "onboarding.completed"
    assert envelope.aggregate_id == str(user.id)


def test_skips_unknown_user(db_session):
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id="00000000-0000-0000-0000-000000000777",
        payload={"tenant_id": "00000000-0000-0000-0000-000000000099"},
    )
    bus = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus)
    bus.publish.assert_not_called()
```

- [ ] **Step 5: Create `test_idempotency.py`**

Write `services/auth-service/tests/test_idempotency.py`:

```python
import uuid
from unittest.mock import MagicMock

from app.models import User, UserStatus
from app.services.onboarding import handle_tenant_created, start_onboarding
from app.schemas.onboarding import OnboardingRequest
from shared.events.envelope import EventEnvelope


def _payload(**over):
    base = dict(
        email="founder@acme.com",
        password="password123",
        name="Ana Founder",
        business_name="Acme Co",
        timezone="UTC",
        legal_name="Acme",
        support_inbox="s@acme.com",
    )
    base.update(over)
    return OnboardingRequest(**base)


def test_second_tenant_created_does_not_republish(db_session):
    user = start_onboarding(db=db_session, data=_payload())
    tenant_id = "00000000-0000-0000-0000-000000000099"
    event = EventEnvelope(
        type="tenant.created",
        aggregate_id=str(user.id),
        payload={"tenant_id": tenant_id, "business_name": "Acme"},
    )
    bus1 = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus1)
    assert bus1.publish.call_count == 1

    bus2 = MagicMock()
    handle_tenant_created(event, db=db_session, event_bus=bus2)
    assert bus2.publish.call_count == 0  # idempotent skip
```

- [ ] **Step 6: Run the test suite**

Run: `cd services/auth-service && uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/auth-service/tests/
git commit -m "test(auth): onboarding endpoint contract + handlers + idempotency"
```

---

## Task 7: Cleanup tenant-service + archive cloudflare

**Files:**
- Delete: `services/tenant-service/app/models/domain.py`
- Delete: `services/tenant-service/app/serializers/`
- Delete: `services/tenant-service/migrations/versions/*.py`
- Delete: `services/tenant-service/tests/test_router_contract.py`
- Move (preserve content): `services/tenant-service/app/services/cloudflare.py` → `services/tenant-service/app/_archived/cloudflare_domains/cloudflare.py`
- Move (preserve content): `services/tenant-service/app/services/tenants.py` → `services/tenant-service/app/_archived/cloudflare_domains/tenants.py` (preserved as-is; the service has domain logic mixed with tenant CRUD)
- Move (preserve content): `services/tenant-service/app/schemas/tenant.py` → `services/tenant-service/app/_archived/cloudflare_domains/schemas.py`
- Move (preserve content): `services/tenant-service/app/router.py` → `services/tenant-service/app/_archived/cloudflare_domains/router.py`
- Move (preserve content): `services/tenant-service/app/controller.py` → `services/tenant-service/app/_archived/cloudflare_domains/controller.py`
- Move (preserve content): `services/tenant-service/app/models/tenant.py` → `services/tenant-service/app/_archived/cloudflare_domains/tenant.py` (the legacy model with cloudflare fields)
- Create: `services/tenant-service/app/_archived/cloudflare_domains/README.md`

**Interfaces:**
- Consumes: nothing (pure deletion + move)
- Produces: live code with NO references to cloudflare, `TenantDomain`, `DomainStatus`, or router/controller endpoints

- [ ] **Step 1: Create `_archived/` directory**

```bash
cd /home/carlos/Escritorio/lead_os
mkdir -p services/tenant-service/app/_archived/cloudflare_domains
```

- [ ] **Step 2: Move legacy files into `_archived/`**

```bash
cd /home/carlos/Escritorio/lead_os
mv services/tenant-service/app/services/cloudflare.py services/tenant-service/app/_archived/cloudflare_domains/cloudflare.py
mv services/tenant-service/app/services/tenants.py services/tenant-service/app/_archived/cloudflare_domains/tenants.py
mv services/tenant-service/app/schemas/tenant.py services/tenant-service/app/_archived/cloudflare_domains/schemas.py
mv services/tenant-service/app/router.py services/tenant-service/app/_archived/cloudflare_domains/router.py
mv services/tenant-service/app/controller.py services/tenant-service/app/_archived/cloudflare_domains/controller.py
mv services/tenant-service/app/models/tenant.py services/tenant-service/app/_archived/cloudflare_domains/tenant.py
```

- [ ] **Step 3: Delete `domain.py`, `serializers/`, migrations, tests**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/tenant-service/app/models/domain.py
rm -rf services/tenant-service/app/serializers
rm services/tenant-service/migrations/versions/*.py
rm services/tenant-service/tests/test_router_contract.py
```

- [ ] **Step 4: Create README explaining how to restore archived code**

Write `services/tenant-service/app/_archived/cloudflare_domains/README.md`:

```markdown
# Archived: Cloudflare domains logic (legacy)

This directory holds the **pre-cleanup** implementation of tenant CRUD +
Cloudflare domain management. It is kept intact (no edits) so we can
restore endpoints when needed.

## Why archived

After the clean-slate spec (2026-08-05), `tenant-service` has only:

- `Tenant` model (no domain/cloudflare fields).
- One consumer that handles `onboarding.pending` and publishes
  `tenant.created`.
- `/health` endpoint.

## What's here

| File | Was | What it contains |
|---|---|---|
| `tenant.py` | `app/models/tenant.py` | Legacy `Tenant` (cloudflare fields) + `TenantDomain` (re-exported from `domain.py` here too if needed) |
| `cloudflare.py` | `app/services/cloudflare.py` | Async HTTP client to Cloudflare API |
| `tenants.py` | `app/services/tenants.py` | Tenant CRUD + domain management logic |
| `schemas.py` | `app/schemas/tenant.py` | Pydantic schemas (Tenant, Domain, requests/responses) |
| `router.py` | `app/router.py` | All HTTP routes (`/tenants`, `/resolve`, `/domains/*`, etc.) |
| `controller.py` | `app/controller.py` | Facade for those routes |

## How to restore

1. Move files back: `mv app/_archived/cloudflare_domains/{tenant,cloudflare,tenants,schemas,router,controller}.py app/<original-location>/`
2. Restore the `Tenant` model fields (cloudflare_*, custom_domain,
   domain_status, settings/branding/limits/features JSON).
3. Restore the `TenantDomain` model from this archive.
4. Add a new Alembic migration that recreates those tables/columns.
5. Restore `domain.py` from git history (`git log --diff-filter=D -- services/tenant-service/app/models/domain.py`).
```

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/app/ services/tenant-service/migrations/ services/tenant-service/tests/
git commit -m "refactor(tenant): purge legacy endpoints/models; archive cloudflare in _archived"
```

---

## Task 8: Tenant models (Tenant + TenantStatus)

**Files:**
- Create: `services/tenant-service/app/models/enums.py`
- Create: `services/tenant-service/app/models/entities.py`
- Create: `services/tenant-service/app/models/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: `from app.models import Tenant, TenantStatus`

- [ ] **Step 1: Create `app/models/enums.py`**

Write `services/tenant-service/app/models/enums.py`:

```python
from enum import Enum


class TenantStatus(str, Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
```

- [ ] **Step 2: Create `app/models/entities.py`**

Write `services/tenant-service/app/models/entities.py`:

```python
import uuid
from datetime import datetime

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

- [ ] **Step 3: Create `app/models/__init__.py`**

Write `services/tenant-service/app/models/__init__.py`:

```python
from app.models.entities import Tenant
from app.models.enums import TenantStatus

__all__ = ["Tenant", "TenantStatus"]
```

- [ ] **Step 4: Verify imports**

Run: `cd services/tenant-service && uv run python -c "from app.models import Tenant, TenantStatus; print(Tenant, TenantStatus)"`
Expected: prints `<class 'app.models.entities.Tenant'>` and `<enum 'TenantStatus'>`.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/app/models/
git commit -m "feat(tenant): minimal Tenant model with TenantStatus enum"
```

---

## Task 9: Tenant Alembic 0001_initial

**Files:**
- Create: `services/tenant-service/migrations/versions/0001_initial.py`

**Interfaces:**
- Consumes: `app.models.entities.Tenant`
- Produces: `tenants` table with all 10 columns + UNIQUE on `slug` + indexes

- [ ] **Step 1: Create the migration file**

Write `services/tenant-service/migrations/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=63), nullable=False),
        sa.Column("business_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("timezone", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("legal_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("support_inbox", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("trial", "active", "suspended", "cancelled", name="tenantstatus"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)
    op.create_index(op.f("ix_tenants_status"), "tenants", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenants_status"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_table("tenants")
```

- [ ] **Step 2: Verify downgrade/upgrade roundtrip**

Run:
```bash
cd services/tenant-service
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```
Expected: each exits 0.

- [ ] **Step 3: Verify migration imports cleanly**

Run: `cd services/tenant-service && uv run python -c "from migrations.versions import 0001_initial"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/migrations/
git commit -m "feat(tenant): alembic 0001_initial creates minimal tenants table"
```

---

## Task 10: Tenant onboarding service + events

**Files:**
- Create: `services/tenant-service/app/services/onboarding.py`
- Create: `services/tenant-service/app/services/__init__.py`
- Create: `services/tenant-service/app/events.py`

**Interfaces:**
- Consumes: `EventEnvelope(type="onboarding.pending")`, `Session`, `EventBus`
- Produces: `handle_onboarding_pending` returns tenant_id (str); `build_handlers(session_factory, event_bus)` returns dict mapping `onboarding.pending` → handler

- [ ] **Step 1: Create `app/services/onboarding.py`**

Write `services/tenant-service/app/services/onboarding.py`:

```python
import logging
import re
import uuid

from sqlmodel import Session

from app.models.entities import Tenant
from app.models.enums import TenantStatus
from shared.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)

_slug_strip_re = re.compile(r"[^a-z0-9-]+")
_slug_dash_re = re.compile(r"-+")


def _slugify(business_name: str) -> str:
    base = business_name.lower().replace(" ", "-")
    base = _slug_strip_re.sub("", base)
    base = _slug_dash_re.sub("-", base).strip("-")
    return (base or "tenant")[:32]


def handle_onboarding_pending(event: EventEnvelope, *, db: Session) -> str:
    payload = event.payload
    business = payload["business_name"]
    slug = f"{_slugify(business)}-{uuid.uuid4().hex[:6]}"

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
    return str(tenant.id), slug
```

- [ ] **Step 2: Create `app/services/__init__.py`**

Write `services/tenant-service/app/services/__init__.py`:

```python
from app.services.onboarding import handle_onboarding_pending

__all__ = ["handle_onboarding_pending"]
```

- [ ] **Step 3: Create `app/events.py`**

Write `services/tenant-service/app/events.py`:

```python
import logging

from sqlmodel import Session
from shared.events.bus import EventBus
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

from app.services.onboarding import handle_onboarding_pending

logger = logging.getLogger(__name__)


def build_handlers(session_factory, event_bus: EventBus) -> dict[str, EventHandler]:
    def _handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            tenant_id, slug = handle_onboarding_pending(event, db=session)
            event_bus.publish(
                "onboarding",
                EventEnvelope(
                    type="tenant.created",
                    aggregate_id=event.payload["user_id"],
                    tenant_id=tenant_id,
                    payload={
                        "user_id": event.payload["user_id"],
                        "tenant_id": tenant_id,
                        "tenant_slug": slug,
                        "business_name": event.payload.get("business_name", ""),
                        "timezone": event.payload.get("timezone", ""),
                        "support_inbox": event.payload.get("support_inbox", ""),
                    },
                ),
            )
        finally:
            session.close()

    return {"onboarding.pending": _handler}
```

- [ ] **Step 4: Verify imports**

Run: `cd services/tenant-service && uv run python -c "from app.services import handle_onboarding_pending; from app.events import build_handlers; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/app/
git commit -m "feat(tenant): onboarding handler publishes tenant.created"
```

---

## Task 11: Tenant empty router/controller + main (consumer)

**Files:**
- Create: `services/tenant-service/app/router.py` (empty)
- Create: `services/tenant-service/app/controller.py` (empty)
- Replace: `services/tenant-service/app/main.py` (with consumer)

**Interfaces:**
- Consumes: `build_handlers` from `app.events`
- Produces: `/health` endpoint; consumer of `events:onboarding` with `group="tenant-service"`

- [ ] **Step 1: Create empty `router.py`**

Write `services/tenant-service/app/router.py`:

```python
from fastapi import APIRouter

router = APIRouter()
# No public endpoints in clean-slate phase. Tenant CRUD + /resolve +
# /domains/* are archived in app/_archived/cloudflare_domains/.
```

- [ ] **Step 2: Create empty `controller.py`**

Write `services/tenant-service/app/controller.py`:

```python
# No public endpoints in clean-slate phase.
```

- [ ] **Step 3: Replace `app/main.py`**

Write `services/tenant-service/app/main.py`:

```python
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.events import build_handlers
from app.router import router
from shared.auth.middleware import ServiceTokenMiddleware
from shared.cache.client import create_redis
from shared.db.engine import create_service_engine, get_session_factory
from shared.events.bus import EventBus
from shared.events.consumer import Consumer
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        session_factory = get_session_factory(engine)
        redis = create_redis(settings.REDIS_URL)
        event_bus = EventBus(settings.REDIS_URL)
        app.state.session_factory = session_factory
        app.state.redis = redis
        app.state.event_bus = event_bus
        app.state.settings = settings

        consumer = Consumer(
            settings.REDIS_URL,
            domain="onboarding",
            group="tenant-service",
            consumer_name=f"tenant-service-{settings.SERVICE_NAME}",
            handlers=build_handlers(session_factory, event_bus),
            block_ms=5000,
        )
        thread = threading.Thread(target=consumer.run_forever, daemon=True)
        thread.start()

        yield

        consumer.stop()
        thread.join(timeout=5)
        engine.dispose()

    app = FastAPI(title="tenant-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
```

- [ ] **Step 4: Verify app imports**

Run: `cd services/tenant-service && uv run python -c "from app.main import app; print([r.path for r in app.routes])"`
Expected: prints `/health` and `/openapi.json`.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/app/
git commit -m "feat(tenant): main with onboarding.pending consumer; empty router/controller"
```

---

## Task 12: Tenant tests

**Files:**
- Create: `services/tenant-service/tests/test_handle_onboarding_pending.py`
- Modify: `services/tenant-service/tests/conftest.py` (replace with SQLite setup)

**Interfaces:**
- Consumes: `EventEnvelope`, `Tenant`
- Produces: tests verifying handler creates Tenant and returns `(tenant_id, slug)` tuple

- [ ] **Step 1: Replace `conftest.py`**

Write `services/tenant-service/tests/conftest.py`:

```python
import os

os.environ.setdefault("SERVICE_NAME", "tenant-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from shared.events.bus import EventBus


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_event_bus(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    return EventBus("redis://localhost:6379/15")
```

- [ ] **Step 2: Create `test_handle_onboarding_pending.py`**

Write `services/tenant-service/tests/test_handle_onboarding_pending.py`:

```python
import re

from app.models import Tenant, TenantStatus
from app.services.onboarding import handle_onboarding_pending
from shared.events.envelope import EventEnvelope


def _event(**over):
    base = dict(
        type="onboarding.pending",
        aggregate_id="00000000-0000-0000-0000-000000000001",
        payload={
            "user_id": "00000000-0000-0000-0000-000000000001",
            "email": "founder@acme.com",
            "full_name": "Ana Founder",
            "phone": "+14155550100",
            "business_name": "Acme Co",
            "legal_name": "Acme Co LLC",
            "support_inbox": "support@acme.com",
            "timezone": "America/Mexico_City",
        },
    )
    base["payload"].update(over)
    return EventEnvelope(**base)


def test_creates_tenant_in_trial(db_session):
    tenant_id, slug = handle_onboarding_pending(_event(), db=db_session)
    assert tenant_id

    from sqlmodel import select
    t = db_session.exec(select(Tenant)).first()
    assert t is not None
    assert t.id is not None
    assert t.name == "Acme Co"
    assert t.business_name == "Acme Co"
    assert t.legal_name == "Acme Co LLC"
    assert t.support_inbox == "support@acme.com"
    assert t.timezone == "America/Mexico_City"
    assert t.status == TenantStatus.TRIAL
    assert t.is_active is True
    assert t.slug == slug


def test_slug_is_derived_and_unique(db_session):
    _, slug1 = handle_onboarding_pending(_event(), db=db_session)
    _, slug2 = handle_onboarding_pending(_event(), db=db_session)
    assert slug1 != slug2
    assert re.match(r"^[a-z0-9-]+-[a-f0-9]{6}$", slug1)


def test_handles_special_chars_in_business_name(db_session):
    _, slug = handle_onboarding_pending(_event(business_name="Café & Co!"), db=db_session)
    assert slug.startswith("caf-co-")
```

- [ ] **Step 3: Run tests**

Run: `cd services/tenant-service && uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/tenant-service/tests/
git commit -m "test(tenant): handler creates Tenant in TRIAL with derived slug"
```

---

## Task 13: Cleanup files-service

**Files:**
- Delete: `services/files-service/app/controller.py`
- Delete: `services/files-service/app/router.py`
- Delete: `services/files-service/app/models/file.py`
- Delete: `services/files-service/app/schemas/`
- Delete: `services/files-service/app/serializers/`
- Delete: `services/files-service/app/services/`
- Delete: `services/files-service/migrations/versions/*.py`
- Delete: `services/files-service/tests/` (entire dir)

**Interfaces:**
- Consumes: nothing
- Produces: empty directories where dead files lived; only `__init__.py`, `config.py`, `main.py`, and the new `models/{enums,entities}.py` remain

- [ ] **Step 1: Delete dead files**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/files-service/app/controller.py
rm services/files-service/app/router.py
rm services/files-service/app/models/file.py
rm -rf services/files-service/app/schemas
rm -rf services/files-service/app/serializers
rm -rf services/files-service/app/services
rm services/files-service/migrations/versions/*.py
rm -rf services/files-service/tests
```

- [ ] **Step 2: Verify skeleton loads (will fail — fixed in next tasks)**

Run: `cd services/files-service && uv run python -c "from app import main"`
Expected: `ImportError` from missing models or router. Fixed in next task.

- [ ] **Step 3: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/files-service/app/ services/files-service/migrations/ services/files-service/tests/
git commit -m "refactor(files): purge legacy code; leave only cascarón"
```

---

## Task 14: Files models (MediaType/MediaPurpose/MediaResources)

**Files:**
- Create: `services/files-service/app/models/enums.py`
- Create: `services/files-service/app/models/entities.py`
- Create: `services/files-service/app/models/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: `from app.models import MediaResources, MediaType, MediaPurpose`

- [ ] **Step 1: Create `app/models/enums.py`**

Write `services/files-service/app/models/enums.py`:

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

- [ ] **Step 2: Create `app/models/entities.py`**

Write `services/files-service/app/models/entities.py`:

```python
import uuid
from typing import Optional

from sqlalchemy import BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.enums import MediaPurpose, MediaType


class MediaResources(SQLModel, table=True):
    __tablename__ = "media_resources"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    original_filename: str = Field(nullable=False)
    media_type: MediaType = Field(
        sa_column=Field(
            sa_type=SAEnum(MediaType, name="media_type"),
            nullable=False,
            index=True,
        )
    )
    purpose: MediaPurpose = Field(
        default=MediaPurpose.OTHER,
        sa_column=Field(
            sa_type=SAEnum(MediaPurpose, name="media_purpose"),
            nullable=False,
            index=True,
        ),
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

    class Config:
        arbitrary_types_allowed = True
```

- [ ] **Step 3: Create `app/models/__init__.py`**

Write `services/files-service/app/models/__init__.py`:

```python
from app.models.entities import MediaResources
from app.models.enums import MediaPurpose, MediaType

__all__ = ["MediaResources", MediaType, MediaPurpose]
```

- [ ] **Step 4: Verify imports**

Run: `cd services/files-service && uv run python -c "from app.models import MediaResources, MediaType, MediaPurpose; print(MediaResources, MediaType, MediaPurpose)"`
Expected: prints classes/enums.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/files-service/app/models/
git commit -m "feat(files): MediaResources model with MediaType and MediaPurpose enums"
```

---

## Task 15: Files Alembic 0001_initial

**Files:**
- Create: `services/files-service/migrations/versions/0001_initial.py`

**Interfaces:**
- Consumes: `app.models.entities.MediaResources` + enums
- Produces: `media_resources` table + `media_type` + `media_purpose` enum types + indexes

- [ ] **Step 1: Create the migration file**

Write `services/files-service/migrations/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    media_type = sa.Enum("image", "video", "audio", "document", "other", name="media_type")
    media_purpose = sa.Enum(
        "product_image", "category_image", "profile_photo", "payment_receipt",
        "banner_video", "other", name="media_purpose",
    )
    media_type.create(op.get_bind(), checkfirst=True)
    media_purpose.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "media_resources",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("media_type", media_type, nullable=False),
        sa.Column("purpose", media_purpose, nullable=False),
        sa.Column("mimetype", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("bucket", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_media_resources_media_type"), "media_resources", ["media_type"], unique=False)
    op.create_index(op.f("ix_media_resources_purpose"), "media_resources", ["purpose"], unique=False)
    op.create_index(op.f("ix_media_resources_is_public"), "media_resources", ["is_public"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_media_resources_is_public"), table_name="media_resources")
    op.drop_index(op.f("ix_media_resources_purpose"), table_name="media_resources")
    op.drop_index(op.f("ix_media_resources_media_type"), table_name="media_resources")
    op.drop_table("media_resources")
    sa.Enum(name="media_purpose").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="media_type").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 2: Verify migration imports cleanly**

Run: `cd services/files-service && uv run python -c "from migrations.versions import 0001_initial"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/files-service/migrations/
git commit -m "feat(files): alembic 0001_initial creates media_resources table + enums"
```

---

## Task 16: Files main simplified

**Files:**
- Replace: `services/files-service/app/main.py`

**Interfaces:**
- Consumes: `Settings`
- Produces: FastAPI app with only `/health` endpoint; no router, no events

- [ ] **Step 1: Replace `app/main.py`**

Write `services/files-service/app/main.py`:

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

    app = FastAPI(title="files-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
```

- [ ] **Step 2: Verify imports**

Run: `cd services/files-service && uv run python -c "from app.main import app; print([r.path for r in app.routes])"`
Expected: prints `/health` and `/openapi.json`.

- [ ] **Step 3: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/files-service/app/main.py
git commit -m "refactor(files): main with /health only, no router/events"
```

---

## Task 17: Files smoke test

**Files:**
- Create: `services/files-service/tests/__init__.py`
- Create: `services/files-service/tests/conftest.py`
- Create: `services/files-service/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: smoke test that verifies service imports and `/health` returns 200

- [ ] **Step 1: Create `tests/__init__.py`**

```bash
cd /home/carlos/Escritorio/lead_os
touch services/files-service/tests/__init__.py
```

- [ ] **Step 2: Create `tests/conftest.py`**

Write `services/files-service/tests/conftest.py`:

```python
import os

os.environ.setdefault("SERVICE_NAME", "files-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 3: Create `tests/test_smoke.py`**

Write `services/files-service/tests/test_smoke.py`:

```python
def test_health_endpoint_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "files-service"
```

- [ ] **Step 4: Run test**

Run: `cd services/files-service && uv run pytest -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/files-service/tests/
git commit -m "test(files): smoke test for /health endpoint"
```

---

## Task 18: Cleanup users-service

**Files:**
- Delete: `services/users-service/app/controller.py`
- Delete: `services/users-service/app/router.py`
- Delete: `services/users-service/app/models/`
- Delete: `services/users-service/app/schemas/`
- Delete: `services/users-service/app/serializers/`
- Delete: `services/users-service/app/services/`
- Delete: `services/users-service/app/events.py`
- Delete: `services/users-service/migrations/versions/*.py`
- Delete: `services/users-service/tests/`
- Replace: `services/users-service/app/main.py`

**Interfaces:**
- Consumes: nothing
- Produces: cascarón with only `app/__init__.py`, `app/config.py`, `app/main.py`

- [ ] **Step 1: Delete dead files**

```bash
cd /home/carlos/Escritorio/lead_os
rm services/users-service/app/controller.py
rm services/users-service/app/router.py
rm -rf services/users-service/app/models
rm -rf services/users-service/app/schemas
rm -rf services/users-service/app/serializers
rm -rf services/users-service/app/services
rm services/users-service/app/events.py
rm services/users-service/migrations/versions/*.py
rm -rf services/users-service/tests
```

- [ ] **Step 2: Replace `app/main.py`**

Write `services/users-service/app/main.py`:

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

- [ ] **Step 3: Verify imports**

Run: `cd services/users-service && uv run python -c "from app.main import app; print([r.path for r in app.routes])"`
Expected: prints `/health` and `/openapi.json`.

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/users-service/
git commit -m "refactor(users): empty cascarón with /health only"
```

---

## Task 19: Users-service smoke test

**Files:**
- Create: `services/users-service/tests/__init__.py`
- Create: `services/users-service/tests/conftest.py`
- Create: `services/users-service/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: smoke test verifying imports and `/health`

- [ ] **Step 1: Create `tests/__init__.py`**

```bash
cd /home/carlos/Escritorio/lead_os
touch services/users-service/tests/__init__.py
```

- [ ] **Step 2: Create `tests/conftest.py`**

Write `services/users-service/tests/conftest.py`:

```python
import os

os.environ.setdefault("SERVICE_NAME", "users-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
```

- [ ] **Step 3: Create `tests/test_smoke.py`**

Write `services/users-service/tests/test_smoke.py`:

```python
def test_health_endpoint_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "users-service"
```

- [ ] **Step 4: Run test**

Run: `cd services/users-service && uv run pytest -q`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/Escritorio/lead_os
git add services/users-service/tests/
git commit -m "test(users): smoke test for /health endpoint"
```

---

## Task 20: End-to-end verification

**Files:** none (operational task)

**Interfaces:**
- Consumes: full stack with Docker Compose
- Produces: verified onboarding flow (User + Tenant created + tenant_id assigned)

- [ ] **Step 1: Bring up the stack**

Run: `cd /home/carlos/Escritorio/lead_os && make up`
Expected: all containers (postgres, redis, gateway, auth, tenant, users, files) start healthy.

- [ ] **Step 2: Verify each service's /health**

Run:
```bash
for port in 8000 8001 8002 8003 8004; do
  echo "port $port:" && curl -sf http://localhost:$port/health || echo "FAIL"
done
```
Expected: 5 OK responses.

- [ ] **Step 3: Verify gateway aggregates /health/services**

Run: `curl -s http://localhost:8000/health/services | python -m json.tool`
Expected: 5 services listed, all healthy.

- [ ] **Step 4: Run all migrations**

Run:
```bash
for svc in auth-service tenant-service files-service; do
  docker compose exec $svc uv run alembic upgrade head
done
```
Expected: each says "Running upgrade  -> 0001_initial".

- [ ] **Step 5: Verify DBs have expected tables**

Run:
```bash
docker compose exec postgres psql -U lead_os -d auth_db -c "\dt"
docker compose exec postgres psql -U lead_os -d tenant_db -c "\dt"
docker compose exec postgres psql -U lead_os -d files_db -c "\dt"
```
Expected:
- auth_db: only `users`, `alembic_version`.
- tenant_db: only `tenants`, `alembic_version`.
- files_db: only `media_resources`, `alembic_version`.

- [ ] **Step 6: Hit the onboarding endpoint**

Run:
```bash
curl -X POST http://localhost:8000/api/auth/onboarding \
  -H 'Content-Type: application/json' \
  -d '{
    "email":"founder@acme.com",
    "password":"password123",
    "name":"Ana Founder",
    "phone":"+14155550100",
    "business_name":"Acme Co",
    "timezone":"America/Mexico_City",
    "legal_name":"Acme Co LLC",
    "support_inbox":"support@acme.com"
  }'
```
Expected: `202` with `{"user_id": "<uuid>", "status": "pending_tenant"}`.

- [ ] **Step 7: Wait ~3s for event chain, then verify User is ACTIVE**

Run:
```bash
sleep 3
docker compose exec postgres psql -U lead_os -d auth_db \
  -c "SELECT email, status, tenant_id FROM users;"
docker compose exec postgres psql -U lead_os -d tenant_db \
  -c "SELECT name, slug, status FROM tenants;"
```
Expected:
- auth_db row: `status=active`, `tenant_id` populated.
- tenant_db row: 1 tenant with `slug=acme-co-<6hex>`.

- [ ] **Step 8: Verify onboarding.completed was published**

Run: `docker compose logs auth-service | grep onboarding.completed`
Expected: at least one log line showing `onboarding.completed` was published (or check Redis: `docker compose exec redis redis-cli XLEN events:onboarding` should be ≥ 3 entries).

- [ ] **Step 9: Verify duplicate email returns 409**

Run:
```bash
curl -X POST http://localhost:8000/api/auth/onboarding \
  -H 'Content-Type: application/json' \
  -d '{
    "email":"founder@acme.com",
    "password":"different123",
    "name":"Other",
    "business_name":"X",
    "timezone":"UTC",
    "legal_name":"X",
    "support_inbox":"x@x.com"
  }' -w "\nHTTP %{http_code}\n"
```
Expected: `HTTP 409` with `{"detail": "email already registered"}`.

- [ ] **Step 10: Verify invalid payload returns 422**

Run:
```bash
curl -X POST http://localhost:8000/api/auth/onboarding \
  -H 'Content-Type: application/json' \
  -d '{"email":"bad","password":"x","name":"","business_name":"","timezone":"","legal_name":"","support_inbox":""}' \
  -w "\nHTTP %{http_code}\n"
```
Expected: `HTTP 422`.

- [ ] **Step 11: Verify legacy endpoints return 404**

Run:
```bash
for path in /api/auth/login /api/auth/register /api/auth/me /api/auth/refresh /api/users/me /api/files /api/tenants; do
  echo "GET $path:" && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000$path
done
```
Expected: all `404`.

- [ ] **Step 12: Run full test suite across all services**

Run:
```bash
for svc in auth-service tenant-service users-service files-service; do
  echo "=== $svc ==="
  cd /home/carlos/Escritorio/lead_os/services/$svc && uv run pytest -q
done
```
Expected: all green.

- [ ] **Step 13: Commit final verification docs (optional)**

If any verification revealed drift, fix and commit. Otherwise no commit.

---

## Self-Review Notes (post-write)

**Coverage check** vs spec sections:
- §"auth-service" archivos a borrar ✓ Task 1; modelos ✓ Task 2; migración ✓ Task 3; schemas ✓ Task 4; service ✓ Task 4; consumer ✓ Task 5; tests ✓ Task 6.
- §"tenant-service" archivos a borrar ✓ Task 7; modelos ✓ Task 8; migración ✓ Task 9; onboarding service ✓ Task 10; router/controller/main ✓ Task 11; tests ✓ Task 12.
- §"files-service" archivos a borrar ✓ Task 13; modelos ✓ Task 14; migración ✓ Task 15; main ✓ Task 16; tests ✓ Task 17.
- §"users-service" archivos a borrar ✓ Task 18; tests ✓ Task 19.
- §"Cadena de eventos" `onboarding.pending → tenant.created → onboarding.completed` ✓ Tasks 4, 5, 10, 11 + verification in Task 20.
- §"Manejo de errores / DLQ" — covered by `Consumer.max_deliveries=5` (default in `shared/events/consumer.py`).
- §"Convención `models/entities.py` + `models/enums.py`" ✓ Tasks 2, 8, 14 all use this exact split.
- §"`_archived/cloudflare_domains/`" ✓ Task 7.

**Placeholder scan**: zero "TBD", "TODO", "fill in details", "appropriate handling". Every step has real file paths, real code blocks, real run commands.

**Type/name consistency**:
- `UserStatus.PENDING_TENANT/ACTIVE/DISABLED` — used in Tasks 2, 4, 6.
- `TenantStatus.TRIAL/ACTIVE/SUSPENDED/CANCELLED` — used in Tasks 8, 10, 12.
- `MediaType`, `MediaPurpose` — used in Tasks 14, 15.
- `EventEnvelope.type` strings `"onboarding.pending"`, `"tenant.created"`, `"onboarding.completed"` — consistent across Tasks 4, 5, 10, 11.
- `aggregate_id` for `tenant.created` and `onboarding.completed` = user_id (UUID string). For `onboarding.pending`, also user_id. Consistent.
- `payload["user_id"]` and `payload["tenant_id"]` keys appear in Tasks 4 (publish_pending publishes them), 5 (handle_tenant_created reads `tenant_id`), 10 (tenant handler reads `user_id`, publishes `tenant_id`), 6 (test verifies). All consistent.
- `bcrypt` hash prefix `$2` — Task 6 Step 2 asserts this.
- `slugify(business_name)` pattern: lower → space-to-dash → strip non-alphanumeric → strip leading/trailing dashes → truncate 32 chars → append `-<6 hex>`. Tasks 10, 12.

**Open question resolved during self-review**: The `events.py` builder in auth-service takes `session_factory` AND `event_bus` (changed in Task 5 from the spec's earlier draft). Confirmed by Task 4 Step 3 handler signature `handle_tenant_created(*, db, event_bus)`.

**Plan complete and saved to** `docs/superpowers/plans/2026-08-05-clean-slate-onboarding.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?

