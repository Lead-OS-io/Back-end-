from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.models import TenantStatus
from app.schemas.tenant import (
    DomainCreateRequest, DomainResponse, DomainVerificationResponse,
    SubdomainCreateRequest, TenantContextResponse, TenantCreateRequest,
    TenantDetailResponse, TenantResponse, TenantUpdateRequest,
)
from shared.auth.dependencies import Identity, get_current_identity, require_admin
from shared.db.engine import get_db

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_admin_identity(identity: Identity = Depends(get_current_identity)) -> Identity:
    return require_admin(identity)


# ---- Resolve (público) ----
@router.get("/resolve", response_model=TenantContextResponse)
def resolve_tenant(host: str = Query(...), db: Session = Depends(get_db),
                   settings: Settings = Depends(get_settings)) -> TenantContextResponse:
    return controller.resolve(request_host=host, db=db, settings=settings)


@router.get("/resolve/email", response_model=TenantContextResponse)
def resolve_tenant_by_email(email: str = Query(...), db: Session = Depends(get_db),
                            settings: Settings = Depends(get_settings)) -> TenantContextResponse:
    return controller.resolve_email(email=email, db=db, settings=settings)


@router.get("/resolve/{slug}", response_model=TenantContextResponse)
def resolve_tenant_by_slug(slug: str, db: Session = Depends(get_db),
                           settings: Settings = Depends(get_settings)) -> TenantContextResponse:
    return controller.resolve_slug(slug=slug, db=db, settings=settings)


# ---- CRUD tenants ----
@router.post("/tenants", response_model=TenantDetailResponse, status_code=201)
def create_tenant(data: TenantCreateRequest, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings),
                  _admin: Identity = Depends(get_admin_identity)) -> TenantDetailResponse:
    return controller.create_tenant(data=data, db=db, settings=settings)


@router.get("/tenants", response_model=List[TenantResponse])
def list_tenants(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                 status: Optional[TenantStatus] = None, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> List[TenantResponse]:
    return controller.list_tenants(page=page, page_size=page_size, status=status,
                                   db=db, settings=settings)


@router.get("/tenants/{tenant_id}", response_model=TenantDetailResponse)
def get_tenant(tenant_id: str, db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)) -> TenantDetailResponse:
    return controller.get_tenant(tenant_id=tenant_id, db=db, settings=settings)


@router.put("/tenants/{tenant_id}", response_model=TenantDetailResponse)
def update_tenant(tenant_id: str, data: TenantUpdateRequest, db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings),
                  _admin: Identity = Depends(get_admin_identity)) -> TenantDetailResponse:
    return controller.update_tenant(tenant_id=tenant_id, data=data, db=db, settings=settings)


# ---- Internals (solo red interna) ----
@router.get("/internal/tenants/active-ids", response_model=List[str])
def list_active_tenant_ids(db: Session = Depends(get_db),
                           settings: Settings = Depends(get_settings)) -> List[str]:
    return controller.list_active_ids(db=db, settings=settings)


@router.get("/internal/tenants/{tenant_id}/db-credentials")
def get_tenant_db_credentials(tenant_id: str, db: Session = Depends(get_db),
                              settings: Settings = Depends(get_settings)) -> dict:
    return controller.db_credentials(tenant_id=tenant_id, db=db, settings=settings)


# ---- Domains ----
@router.post("/tenants/{tenant_id}/domains/subdomain", response_model=DomainResponse)
async def create_subdomain(tenant_id: str, data: SubdomainCreateRequest,
                           db: Session = Depends(get_db),
                           settings: Settings = Depends(get_settings),
                           _admin: Identity = Depends(get_admin_identity)) -> DomainResponse:
    return await controller.create_subdomain(tenant_id=tenant_id, data=data, db=db,
                                             settings=settings)


@router.post("/tenants/{tenant_id}/domains/custom", response_model=DomainVerificationResponse)
async def create_custom_domain(tenant_id: str, data: DomainCreateRequest,
                               db: Session = Depends(get_db),
                               settings: Settings = Depends(get_settings),
                               _admin: Identity = Depends(get_admin_identity)) -> DomainVerificationResponse:
    return await controller.create_custom_domain(tenant_id=tenant_id, data=data, db=db,
                                                 settings=settings)


@router.get("/tenants/{tenant_id}/domains", response_model=List[DomainResponse])
def list_domains(tenant_id: str, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> List[DomainResponse]:
    return controller.list_domains(tenant_id=tenant_id, db=db, settings=settings)


@router.get("/tenants/{tenant_id}/domains/{domain_id}", response_model=DomainResponse)
async def get_domain(tenant_id: str, domain_id: str, db: Session = Depends(get_db),
                     settings: Settings = Depends(get_settings)) -> DomainResponse:
    return await controller.get_domain(tenant_id=tenant_id, domain_id=domain_id,
                                       db=db, settings=settings)


@router.delete("/tenants/{tenant_id}/domains/{domain_id}")
async def delete_domain(tenant_id: str, domain_id: str, db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings),
                        _admin: Identity = Depends(get_admin_identity)) -> dict:
    return await controller.delete_domain(tenant_id=tenant_id, domain_id=domain_id,
                                          db=db, settings=settings)
