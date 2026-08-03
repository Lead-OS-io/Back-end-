"""shared.tenant_db

Resolución tenant_id -> DSN/Engine + dependencias FastAPI.

Este módulo implementa el patrón data-plane: cada request autenticada se conecta
exclusivamente a la DB del tenant indicado por `tenant_id` (JWT) y `X-Tenant-ID`.
"""

from .router import TenantDbRouter, TenantDbCredentials  # noqa: F401
from .dependencies import (  # noqa: F401
    init_tenant_db_router,
    get_tenant_db_router,
    require_tenant_header_matches_token,
    get_tenant_db_session,
)

