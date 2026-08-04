from typing import Dict, Any

from app.models.domain import TenantDomain
from app.models.tenant import DomainStatus, Tenant, TenantStatus

DEFAULT_LIMITS: Dict[str, Any] = {
    "users": 0,
    "storage_gb": 0,
    "emails_per_month": 0,
    "api_requests_per_day": 0,
}

DEFAULT_FEATURES: Dict[str, Any] = {}

__all__ = ["Tenant", "TenantDomain", "TenantStatus", "DomainStatus",
           "DEFAULT_LIMITS", "DEFAULT_FEATURES"]
