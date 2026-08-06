"""
Tenant controller (FACADE): orquesta app/services/*, traduce a schemas.
Un método por endpoint; recibe deps como parámetros (no lee Request).
Los métodos que usan Cloudflare son async (el client es httpx async).
"""
from typing import List, Optional

from sqlmodel import Session

from app.schemas.tenant import (
    DomainCreateRequest, DomainResponse, DomainVerificationResponse,
    SubdomainCreateRequest, TenantContextResponse, TenantCreateRequest,
    TenantDetailResponse, TenantResponse, TenantUpdateRequest,
)
from app.serializers.tenant import domain_to_response, tenant_to_detail, tenant_to_response
from app.services import tenants as tenants_service
from app.services import cloudflare as cloudflare_service
from shared.utils.exceptions import AppError


# ---- Resolve (público) ----
def resolve(*, request_host: str, db: Session, settings) -> TenantContextResponse:
    tenant = tenants_service.resolve_tenant(db=db, settings=settings, host=request_host)
    if not tenant:
        raise AppError(404, "Tenant not found")
    if not tenant.is_active:
        raise AppError(403, "Tenant is inactive")
    return TenantContextResponse(id=str(tenant.id), slug=tenant.slug,
                                 features=tenant.features, limits=tenant.limits)


def resolve_email(*, email: str, db: Session, settings) -> TenantContextResponse:
    tenant = tenants_service.resolve_tenant_by_email(db=db, settings=settings, email=email)
    if not tenant:
        raise AppError(404, "Tenant not found for email")
    if not tenant.is_active:
        raise AppError(403, "Tenant is inactive")
    return TenantContextResponse(id=str(tenant.id), slug=tenant.slug,
                                 features=tenant.features, limits=tenant.limits)


def resolve_slug(*, slug: str, db: Session, settings) -> TenantContextResponse:
    tenant = tenants_service.resolve_tenant_by_slug(db=db, settings=settings, slug=slug)
    if not tenant:
        raise AppError(404, "Tenant not found")
    return TenantContextResponse(id=str(tenant.id), slug=tenant.slug,
                                 features=tenant.features, limits=tenant.limits)


# ---- CRUD tenants ----
def create_tenant(*, data: TenantCreateRequest, db: Session, settings) -> TenantDetailResponse:
    try:
        tenant = tenants_service.create_tenant(db=db, settings=settings, data=data)
    except ValueError as e:
        raise AppError(400, str(e))
    return tenant_to_detail(tenant)


def list_tenants(*, page: int, page_size: int, status, db: Session,
                 settings) -> List[TenantResponse]:
    tenants, _ = tenants_service.list_tenants(
        db=db, settings=settings, page=page, page_size=page_size, status=status)
    return [tenant_to_response(t) for t in tenants]


def get_tenant(*, tenant_id: str, db: Session, settings) -> TenantDetailResponse:
    tenant = tenants_service.get_tenant(db=db, settings=settings, tenant_id=tenant_id)
    if not tenant:
        raise AppError(404, "Tenant not found")
    return tenant_to_detail(tenant)


def update_tenant(*, tenant_id: str, data: TenantUpdateRequest, db: Session,
                  settings) -> TenantDetailResponse:
    tenant = tenants_service.update_tenant(
        db=db, settings=settings, tenant_id=tenant_id,
        **data.model_dump(exclude_unset=True))
    if not tenant:
        raise AppError(404, "Tenant not found")
    return tenant_to_detail(tenant)


# ---- Internals (solo red interna) ----
def list_active_ids(*, db: Session, settings) -> List[str]:
    return tenants_service.list_active_tenant_ids(db=db, settings=settings)


def db_credentials(*, tenant_id: str, db: Session, settings) -> dict:
    tenant = tenants_service.get_tenant(db=db, settings=settings, tenant_id=tenant_id)
    if not tenant:
        raise AppError(404, "Tenant not found")
    if not tenant.is_active:
        raise AppError(404, "Tenant is not active")
    try:
        return tenants_service.get_tenant_db_credentials(db=db, settings=settings,
                                                         tenant_id=tenant_id)
    except ValueError as e:
        raise AppError(500, f"Invalid DATABASE_URL: {e}")


# ---- Domains (async: cloudflare) ----
async def create_subdomain(*, tenant_id: str, data: SubdomainCreateRequest, db: Session,
                           settings) -> DomainResponse:
    tenant = tenants_service.get_tenant(db=db, settings=settings, tenant_id=tenant_id)
    if not tenant:
        raise AppError(404, "Tenant not found")
    try:
        domain = await cloudflare_service.create_subdomain(
            db=db, settings=settings, tenant_id=tenant_id, subdomain=data.subdomain)
    except ValueError as e:
        raise AppError(400, str(e))
    return domain_to_response(domain)


async def create_custom_domain(*, tenant_id: str, data: DomainCreateRequest, db: Session,
                               settings) -> DomainVerificationResponse:
    tenant = tenants_service.get_tenant(db=db, settings=settings, tenant_id=tenant_id)
    if not tenant:
        raise AppError(404, "Tenant not found")
    if not tenant.features.get("custom_domain", False):
        raise AppError(403, "Custom domains are not available for this tenant")
    try:
        domain = await cloudflare_service.create_custom_domain(
            db=db, settings=settings, tenant_id=tenant_id, domain=data.domain)
        instructions = cloudflare_service.get_verification_instructions(
            db=db, settings=settings, domain=domain)
    except ValueError as e:
        raise AppError(400, str(e))
    return DomainVerificationResponse(**instructions)


def list_domains(*, tenant_id: str, db: Session, settings) -> List[DomainResponse]:
    domains = tenants_service.list_domains(db=db, settings=settings, tenant_id=tenant_id)
    return [domain_to_response(d) for d in domains]


async def get_domain(*, tenant_id: str, domain_id: str, db: Session, settings) -> DomainResponse:
    domain = await tenants_service.get_domain(
        db=db, settings=settings, tenant_id=tenant_id, domain_id=domain_id)
    if not domain:
        raise AppError(404, "Domain not found")
    return domain_to_response(domain)


async def delete_domain(*, tenant_id: str, domain_id: str, db: Session, settings) -> dict:
    ok = await tenants_service.delete_domain(
        db=db, settings=settings, tenant_id=tenant_id, domain_id=domain_id)
    if not ok:
        raise AppError(404, "Domain not found")
    return {"message": "Domain deleted"}
