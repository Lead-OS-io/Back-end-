from app.models import Tenant, TenantDomain
from app.schemas.tenant import DomainResponse, TenantDetailResponse, TenantResponse


def tenant_to_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse.model_validate(tenant)


def tenant_to_detail(tenant: Tenant) -> TenantDetailResponse:
    return TenantDetailResponse.model_validate(tenant)


def domain_to_response(domain: TenantDomain) -> DomainResponse:
    return DomainResponse.model_validate(domain)
