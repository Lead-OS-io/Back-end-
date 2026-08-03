"""
Tenant Service API Routes.
"""
from typing import Optional, List, Any
from urllib.parse import urlparse, parse_qs

import jwt
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query, Request
from app.redis_cache import cached
from sqlmodel import Session

from app.config import settings
from app.database import get_db
from app.models import TenantStatus
from app.schemas import (
    TenantCreateRequest,
    TenantUpdateRequest,
    DomainCreateRequest,
    SubdomainCreateRequest,
    TenantResponse,
    TenantDetailResponse,
    DomainResponse,
    DomainVerificationResponse,
    TenantContextResponse,
    HealthResponse,
)
from app.services import TenantService, DomainService
from app.cloudflare import cloudflare_client

router = APIRouter()


def _invalidate_shared_cache_safe() -> None:
    """tenant-service caches everything under the u:global segment (no
    per-user key here), so any tenant/domain write invalidates that whole
    prefix - otherwise resolve/list/detail stay stale up to their TTL
    (e.g. a suspended tenant would keep resolving for up to an hour)."""
    try:
        from app.redis_client import redis_client
        if not redis_client:
            return
        import asyncio

        async def _do():
            batch = []
            async for k in redis_client.scan_iter(match="ariadesk:shared:u:global:*", count=500):
                batch.append(k)
                if len(batch) >= 500:
                    await redis_client.delete(*batch)
                    batch = []
            if batch:
                await redis_client.delete(*batch)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_do())
        else:
            loop.create_task(_do())
    except Exception:
        return


def _decode_bearer(authorization: Optional[str]) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_service_token(authorization: Optional[str] = Header(None)) -> dict:
    """For machine-to-machine calls (db-credentials, active-ids): the signed
    JWT must carry type=service, produced by shared/tenant_db/router.py."""
    claims = _decode_bearer(authorization)
    if claims.get("type") != "service":
        raise HTTPException(status_code=403, detail="Service token required")
    return claims


def require_admin_token(authorization: Optional[str] = Header(None)) -> dict:
    """For tenant/domain administration: caller must be a signature-verified
    superuser (is_superuser claim, or role_id == 1)."""
    claims = _decode_bearer(authorization)
    role_id = claims.get("role_id")
    try:
        role_id = int(role_id) if role_id is not None else None
    except Exception:
        role_id = None
    if not (bool(claims.get("is_superuser")) or role_id == 1):
        raise HTTPException(status_code=403, detail="Admin access required")
    return claims


_cf_health_cache = {"ok": True, "checked_at": 0.0}
_CF_HEALTH_TTL_SECONDS = 60


async def _cloudflare_ok_cached() -> bool:
    """Cache the Cloudflare check so the health probe (hit every ~30s by the
    orchestrator) doesn't make a live external call every time."""
    import time
    now = time.monotonic()
    if now - _cf_health_cache["checked_at"] > _CF_HEALTH_TTL_SECONDS:
        _cf_health_cache["ok"] = await cloudflare_client.verify_connection()
        _cf_health_cache["checked_at"] = now
    return _cf_health_cache["ok"]


# Health check
@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    cf_ok = await _cloudflare_ok_cached()

    return HealthResponse(
        status="healthy" if cf_ok else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
        cloudflare_connected=cf_ok,
    )


# Tenant resolution (for other services)
@router.get("/resolve", response_model=TenantContextResponse)
@cached(ttl=3600, prefix="resolve_host")
async def resolve_tenant(
    request: Request,
    host: str = Query(..., description="Host header value"),
    db: Session = Depends(get_db),
):
    """Resolve tenant from host header (for inter-service communication)."""
    tenant_service = TenantService(db)
    tenant = tenant_service.resolve_tenant(host)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if not tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant is inactive")
    
    return TenantContextResponse(
        id=str(tenant.id),
        slug=tenant.slug,
        features=tenant.features,
        limits=tenant.limits,
    )


@router.get("/resolve/email", response_model=TenantContextResponse)
@cached(ttl=3600, prefix="resolve_email")
async def resolve_tenant_by_email(
    request: Request,
    email: str = Query(..., description="User email to resolve tenant"),
    db: Session = Depends(get_db),
):
    """Resolve tenant by owner/billing email (for auth service)."""
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant_by_email(email)

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found for email")

    if not tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant is inactive")

    return TenantContextResponse(
        id=str(tenant.id),
        slug=tenant.slug,
        features=tenant.features,
        limits=tenant.limits,
    )


@router.get("/resolve/{slug}", response_model=TenantContextResponse)
@cached(ttl=3600, prefix="resolve_slug")
async def resolve_tenant_by_slug(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
):
    """Resolve tenant by slug."""
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant_by_slug(slug)

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return TenantContextResponse(
        id=str(tenant.id),
        slug=tenant.slug,
        features=tenant.features,
        limits=tenant.limits,
    )


# Tenant CRUD
@router.post("/tenants", response_model=TenantDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: TenantCreateRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin_token),
):
    """Create a new tenant."""
    tenant_service = TenantService(db)
    
    try:
        tenant = tenant_service.create_tenant(
            name=request.name,
            slug=request.slug,
            owner_email=request.owner_email,
            settings=request.settings,
            branding=request.branding,
        )
        _invalidate_shared_cache_safe()
        return TenantDetailResponse.model_validate(tenant)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tenants", response_model=List[TenantResponse])
@cached(ttl=3600, prefix="tenant_list")
async def list_tenants(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[TenantStatus] = None,
    db: Session = Depends(get_db),
):
    """List all tenants."""
    tenant_service = TenantService(db)
    tenants, total = tenant_service.list_tenants(
        page=page,
        page_size=page_size,
        status=status,
    )
    return [TenantResponse.model_validate(t) for t in tenants]


@router.get("/internal/tenants/active-ids", response_model=List[str])
async def list_active_tenant_ids(
    db: Session = Depends(get_db),
    _svc: dict = Depends(require_service_token),
):
    """Internal: List all active tenant IDs for background tasks."""
    tenant_service = TenantService(db)
    # Assuming list_tenants can filter by status and return all if page_size is large enough
    # For a real implementation, add a specific method efficiently claiming IDs
    all_active, _ = tenant_service.list_tenants(page=1, page_size=1000, status=TenantStatus.ACTIVE)
    return [str(t.id) for t in all_active]


def _parse_database_url(url: str) -> dict[str, Any]:
    """Parsea DATABASE_URL y devuelve dict con db_host, db_port, db_name, db_user, db_password, db_sslmode."""
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"Unsupported database scheme: {u.scheme}")

    # netloc = "user:password@host:port"
    netloc = u.netloc
    at = netloc.rfind("@")
    if at == -1:
        raise ValueError("DATABASE_URL: missing @ in netloc")
    userinfo, hostport = netloc[:at], netloc[at + 1 :]
    colon = userinfo.find(":")
    if colon == -1:
        db_user, db_password = userinfo, ""
    else:
        db_user, db_password = userinfo[:colon], userinfo[colon + 1 :]

    # host:port
    if ":" in hostport:
        db_host, port_str = hostport.rsplit(":", 1)
        db_port = int(port_str)
    else:
        db_host = hostport
        db_port = 5432

    # path = /dbname o /dbname?...
    path = (u.path or "/").lstrip("/")
    db_name = path.split("?")[0] or "postgres"

    # query: sslmode=require
    qs = parse_qs(u.query or "")
    db_sslmode = (qs.get("sslmode") or ["require"])[0]

    return {
        "db_host": db_host,
        "db_port": db_port,
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "db_sslmode": db_sslmode,
    }


@router.get("/internal/tenants/{tenant_id}/db-credentials")
async def get_tenant_db_credentials(
    tenant_id: str,
    db: Session = Depends(get_db),
    _svc: dict = Depends(require_service_token),
):
    """
    Internal: Devuelve credenciales de base de datos para el tenant.
    Hoy usamos la misma DB para todos; en el futuro se puede devolver una DB distinta por tenant.
    El monolith (scheduler, workers) llama a este endpoint para obtener el engine por tenant.
    """
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant.is_active:
        raise HTTPException(status_code=404, detail="Tenant is not active")

    try:
        creds = _parse_database_url(settings.DATABASE_URL)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Invalid DATABASE_URL: {e}")

    return creds


@router.get("/tenants/{tenant_id}", response_model=TenantDetailResponse)
@cached(ttl=3600, prefix="tenant_detail")
async def get_tenant(
    request: Request,
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Get tenant by ID."""
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant(tenant_id)
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    return TenantDetailResponse.model_validate(tenant)


@router.put("/tenants/{tenant_id}", response_model=TenantDetailResponse)
async def update_tenant(
    tenant_id: str,
    request: TenantUpdateRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin_token),
):
    """Update a tenant."""
    tenant_service = TenantService(db)
    
    tenant = tenant_service.update_tenant(
        tenant_id=tenant_id,
        **request.model_dump(exclude_unset=True),
    )
    
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    _invalidate_shared_cache_safe()
    return TenantDetailResponse.model_validate(tenant)


# Domain management
@router.post("/tenants/{tenant_id}/domains/subdomain", response_model=DomainResponse)
async def create_subdomain(
    tenant_id: str,
    request: SubdomainCreateRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin_token),
):
    """Create a subdomain for a tenant (automatic DNS configuration)."""
    # Verify tenant exists
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    domain_service = DomainService(db)
    
    try:
        domain = await domain_service.create_subdomain(
            tenant_id=tenant_id,
            subdomain=request.subdomain,
        )
        _invalidate_shared_cache_safe()
        return DomainResponse.model_validate(domain)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tenants/{tenant_id}/domains/custom", response_model=DomainVerificationResponse)
async def create_custom_domain(
    tenant_id: str,
    request: DomainCreateRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin_token),
):
    """Create a custom domain for a tenant (requires DNS verification)."""
    # Verify tenant exists and has custom domain feature
    tenant_service = TenantService(db)
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    
    if not tenant.features.get("custom_domain", False):
        raise HTTPException(
            status_code=403,
            detail="Custom domains are not available for this tenant",
        )
    
    domain_service = DomainService(db)
    
    try:
        domain = await domain_service.create_custom_domain(
            tenant_id=tenant_id,
            domain=request.domain,
        )
        instructions = domain_service.get_verification_instructions(domain)
        _invalidate_shared_cache_safe()
        return DomainVerificationResponse(**instructions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tenants/{tenant_id}/domains", response_model=List[DomainResponse])
@cached(ttl=3600, prefix="tenant_domains")
async def list_domains(
    request: Request,
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """List domains for a tenant."""
    domain_service = DomainService(db)
    domains = domain_service.list_domains(tenant_id)
    return [DomainResponse.model_validate(d) for d in domains]


@router.get("/tenants/{tenant_id}/domains/{domain_id}", response_model=DomainResponse)
async def get_domain(
    tenant_id: str,
    domain_id: str,
    db: Session = Depends(get_db),
):
    """Get domain status and check verification."""
    domain_service = DomainService(db)
    domain = await domain_service.check_domain_status(domain_id)
    
    if not domain or str(domain.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    return DomainResponse.model_validate(domain)


@router.delete("/tenants/{tenant_id}/domains/{domain_id}")
async def delete_domain(
    tenant_id: str,
    domain_id: str,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin_token),
):
    """Delete a domain."""
    from app.models import TenantDomain
    
    domain = db.get(TenantDomain, domain_id)
    if not domain or str(domain.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Domain not found")
    
    domain_service = DomainService(db)
    await domain_service.delete_domain(domain_id)

    _invalidate_shared_cache_safe()
    return {"message": "Domain deleted"}

