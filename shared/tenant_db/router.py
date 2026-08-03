"""Tenant DB router (data-plane).

- Cachea tenant_id -> credenciales (vía tenant-service control-plane)
- Cachea tenant_id -> SQLAlchemy Engine

Seguridad:
- Llama a tenant-service con un *service token* firmado con SECRET_KEY compartida.
- El service token va "bound" al tenant_id solicitado.

Nota: la verificación `X-Tenant-ID == tenant_id del JWT` se hace en dependencias.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Any, List
import time

import httpx
from jose import jwt
from sqlmodel import create_engine


class TenantDbRoutingError(RuntimeError):
    """Base error for tenant DB routing failures."""


class TenantDbNotProvisionedError(TenantDbRoutingError):
    """Raised when the tenant DB credentials do not exist yet (tenant not provisioned)."""


@dataclass(frozen=True)
class TenantDbCredentials:
    tenant_id: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_sslmode: str = "require"

    def dsn(self) -> str:
        # psycopg2 is the default driver in most services; keep DSN simple.
        # NOTE: sslmode is important in Supabase.
        return (
            f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/"
            f"{self.db_name}?sslmode={self.db_sslmode}"
        )


class TenantDbRouter:
    def __init__(
        self,
        *,
        tenant_service_url: str,
        control_plane_secret_key: str,
        credentials_ttl_seconds: int = 300,
        engine_ttl_seconds: int = 3600,
        tenant_ids_ttl_seconds: int = 60,
        engine_kwargs: Optional[Dict[str, Any]] = None,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self.tenant_service_url = (tenant_service_url or "").rstrip("/")
        self.control_plane_secret_key = (control_plane_secret_key or "").strip()
        self.credentials_ttl_seconds = int(credentials_ttl_seconds)
        self.engine_ttl_seconds = int(engine_ttl_seconds)
        self.tenant_ids_ttl_seconds = int(tenant_ids_ttl_seconds)
        self.engine_kwargs = engine_kwargs or {}
        self.request_timeout_seconds = float(request_timeout_seconds)

        if not self.tenant_service_url:
            raise ValueError("tenant_service_url is required")
        if not self.control_plane_secret_key:
            raise ValueError("control_plane_secret_key is required")

        # tenant_id -> (expires_at, value)
        self._cred_cache: Dict[str, Tuple[float, TenantDbCredentials]] = {}
        # Avoid importing SQLAlchemy types in runtime (SQLModel-only contract).
        self._engine_cache: Dict[str, Tuple[float, Any]] = {}
        self._tenant_ids_cache: Optional[Tuple[float, List[str]]] = None

    def _now(self) -> float:
        return time.time()

    def _sign_service_token(self, tenant_id: str, expires_seconds: int = 600) -> str:
        now = int(self._now())
        payload = {
            "tenant_id": str(tenant_id),
            "type": "service",
            "iat": now,
            "exp": now + int(expires_seconds),
        }
        return jwt.encode(payload, self.control_plane_secret_key, algorithm="HS256")

    def _get_cached_credentials(self, tenant_id: str) -> Optional[TenantDbCredentials]:
        item = self._cred_cache.get(str(tenant_id))
        if not item:
            return None
        expires_at, value = item
        if expires_at <= self._now():
            self._cred_cache.pop(str(tenant_id), None)
            return None
        return value

    def _set_cached_credentials(self, tenant_id: str, cred: TenantDbCredentials) -> None:
        self._cred_cache[str(tenant_id)] = (self._now() + self.credentials_ttl_seconds, cred)

    def get_credentials(self, tenant_id: str, *, force_refresh: bool = False) -> TenantDbCredentials:
        tid = str(tenant_id)
        if not force_refresh:
            cached = self._get_cached_credentials(tid)
            if cached:
                return cached

        token = self._sign_service_token(tid)
        url = f"{self.tenant_service_url}/api/internal/tenants/{tid}/db-credentials"
        try:
            with httpx.Client(timeout=self.request_timeout_seconds) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError as e:
            raise TenantDbRoutingError(f"tenant-service unreachable at {url}: {e}")

        # Map common errors to explicit exceptions for better HTTP responses upstream.
        if resp.status_code == 404:
            raise TenantDbNotProvisionedError("Tenant DB not provisioned yet")
        if resp.status_code >= 400:
            raise TenantDbRoutingError(f"tenant-service error {resp.status_code}: {resp.text}")

        data = resp.json() if resp.content else {}

        cred = TenantDbCredentials(
            tenant_id=tid,
            db_host=str(data["db_host"]),
            db_port=int(data.get("db_port") or 5432),
            db_name=str(data["db_name"]),
            db_user=str(data["db_user"]),
            db_password=str(data["db_password"]),
            db_sslmode=str(data.get("db_sslmode") or "require"),
        )
        self._set_cached_credentials(tid, cred)
        return cred

    def _get_cached_engine(self, tenant_id: str) -> Optional[Any]:
        item = self._engine_cache.get(str(tenant_id))
        if not item:
            return None
        expires_at, engine = item
        if expires_at <= self._now():
            self._engine_cache.pop(str(tenant_id), None)
            try:
                engine.dispose()
            except Exception:
                pass
            return None
        return engine

    def _set_cached_engine(self, tenant_id: str, engine: Any) -> None:
        self._engine_cache[str(tenant_id)] = (self._now() + self.engine_ttl_seconds, engine)

    def list_active_tenant_ids(self, *, force_refresh: bool = False) -> List[str]:
        """
        Discover active tenants from the control-plane.

        This is required in Railway because env vars cannot be automatically updated
        to include new tenant IDs; background schedulers must query the tenant-service.
        """
        if not force_refresh and self._tenant_ids_cache:
            expires_at, ids = self._tenant_ids_cache
            if expires_at > self._now():
                return list(ids)

        token = self._sign_service_token("__system__", expires_seconds=600)
        url = f"{self.tenant_service_url}/api/internal/tenants/active-ids"
        try:
            with httpx.Client(timeout=self.request_timeout_seconds) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError as e:
            raise TenantDbRoutingError(f"tenant-service unreachable at {url}: {e}")

        if resp.status_code >= 400:
            raise TenantDbRoutingError(f"tenant-service error {resp.status_code}: {resp.text}")

        data = resp.json() if resp.content else {}

        # Robust handling for different response formats from tenant-service
        raw_ids = []
        if isinstance(data, list):
            raw_ids = data
        elif isinstance(data, dict):
            raw_ids = data.get("tenant_ids") or []
        
        if not isinstance(raw_ids, list):
            raw_ids = []
        ids = [str(t).strip() for t in raw_ids if str(t).strip()]
        self._tenant_ids_cache = (self._now() + self.tenant_ids_ttl_seconds, ids)
        return list(ids)

    def get_engine(self, tenant_id: str, *, force_refresh: bool = False) -> Any:
        tid = str(tenant_id)
        if not force_refresh:
            cached = self._get_cached_engine(tid)
            if cached:
                return cached

        cred = self.get_credentials(tid, force_refresh=force_refresh)
        dsn = cred.dsn()

        from sqlalchemy.pool import NullPool
        # Switched to NullPool for Production Stability and Supavisor Transaction Mode (port 6543)
        defaults = {
            "pool_pre_ping": True,
            "poolclass": NullPool,
            "future": True,
            "connect_args": {
                "prepare_threshold": None  # Disable prepared statements for Transaction Mode (port 6543)
            }
        }
        
        # Merge custom engine_kwargs
        if self.engine_kwargs:
            # If engine_kwargs has connect_args, merge them
            if "connect_args" in self.engine_kwargs:
                defaults["connect_args"].update(self.engine_kwargs["connect_args"])
                # Ensure we don't overwrite the kwarg itself if we merge manually
                curr_kwargs = self.engine_kwargs.copy()
                curr_kwargs.pop("connect_args")
                defaults.update(curr_kwargs)
            else:
                defaults.update(self.engine_kwargs)

        engine = create_engine(dsn, **defaults)
        self._set_cached_engine(tid, engine)
        return engine

