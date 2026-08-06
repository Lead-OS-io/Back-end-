"""
Tenant Service Business Logic (module-level functions; facade via app/controller.py).
"""
import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    Tenant, TenantDomain, TenantStatus, DomainStatus,
    DEFAULT_LIMITS, DEFAULT_FEATURES,
)

logger = logging.getLogger(__name__)


def resolve_tenant(*, db: Session, settings: Settings, host: str) -> Optional[Tenant]:
    """Resolve tenant from host header."""
    if not host:
        return None

    domain = host.split(":")[0].lower()

    base_domain = settings.BASE_DOMAIN.lower()
    if domain.endswith(f".{base_domain}"):
        slug = domain.replace(f".{base_domain}", "")
        if slug and slug != "www":
            return get_tenant_by_slug(db=db, settings=settings, slug=slug)

    return get_tenant_by_domain(db=db, settings=settings, domain=domain)


def resolve_tenant_by_email(*, db: Session, settings: Settings, email: str) -> Optional[Tenant]:
    """Resolve tenant by owner/billing email (case-insensitive)."""
    if not email:
        return None
    normalized = email.strip().lower()
    return db.exec(
        select(Tenant).where(
            (Tenant.owner_email == normalized) | (Tenant.billing_email == normalized)
        )
    ).first()


def resolve_tenant_by_slug(*, db: Session, settings: Settings, slug: str) -> Optional[Tenant]:
    return get_tenant_by_slug(db=db, settings=settings, slug=slug)


def create_tenant(*, db: Session, settings: Settings, data) -> Tenant:
    """Create a new tenant."""
    slug = data.slug
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")

    existing = db.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if existing:
        raise ValueError(f"Tenant with slug '{slug}' already exists")

    limits = dict(DEFAULT_LIMITS or {})
    features = dict(DEFAULT_FEATURES or {})

    tenant = Tenant(
        name=data.name,
        slug=slug,
        owner_email=data.owner_email,
        status=TenantStatus.TRIAL,
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
        settings=data.settings or {},
        branding=data.branding or {},
        limits=limits,
        features=features,
    )

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    logger.info(f"Created tenant: {tenant.id} ({tenant.slug})")
    return tenant


def get_tenant(*, db: Session, settings: Settings, tenant_id: str) -> Optional[Tenant]:
    """Get tenant by ID."""
    return db.get(Tenant, tenant_id)


def get_tenant_by_slug(*, db: Session, settings: Settings, slug: str) -> Optional[Tenant]:
    return db.exec(select(Tenant).where(Tenant.slug == slug)).first()


def get_tenant_by_domain(*, db: Session, settings: Settings, domain: str) -> Optional[Tenant]:
    """Get tenant by custom domain."""
    tenant = db.exec(select(Tenant).where(Tenant.custom_domain == domain)).first()
    if tenant:
        return tenant

    tenant_domain = db.exec(
        select(TenantDomain).where(
            TenantDomain.domain == domain,
            TenantDomain.status == DomainStatus.ACTIVE,
        )
    ).first()

    if tenant_domain:
        return get_tenant(db=db, settings=settings, tenant_id=str(tenant_domain.tenant_id))

    return None


def update_tenant(*, db: Session, settings: Settings, tenant_id: str, **updates) -> Optional[Tenant]:
    """Update a tenant."""
    tenant = get_tenant(db=db, settings=settings, tenant_id=tenant_id)
    if not tenant:
        return None

    for key, value in updates.items():
        if value is not None and hasattr(tenant, key):
            setattr(tenant, key, value)

    tenant.modified_at = datetime.utcnow()

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return tenant


def list_tenants(*, db: Session, settings: Settings, page: int = 1, page_size: int = 50,
                 status: Optional[TenantStatus] = None) -> tuple[List[Tenant], int]:
    """List tenants with pagination."""
    from sqlmodel import func

    query = select(Tenant)
    if status:
        query = query.where(Tenant.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = db.exec(count_query).one()

    query = query.order_by(Tenant.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    tenants = db.exec(query).all()
    return tenants, total


def list_active_tenant_ids(*, db: Session, settings: Settings) -> List[str]:
    """Internal: List all active tenant IDs for background tasks."""
    all_active, _ = list_tenants(db=db, settings=settings, page=1, page_size=1000,
                                 status=TenantStatus.ACTIVE)
    return [str(t.id) for t in all_active]


def get_tenant_db_credentials(*, db: Session, settings: Settings, tenant_id: str) -> dict:
    """Internal: credenciales de base de datos para el tenant (hoy: misma DB)."""
    from urllib.parse import urlparse, parse_qs

    url = settings.DATABASE_URL
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"Unsupported database scheme: {u.scheme}")

    netloc = u.netloc
    at = netloc.rfind("@")
    if at == -1:
        raise ValueError("DATABASE_URL: missing @ in netloc")
    userinfo, hostport = netloc[:at], netloc[at + 1:]
    colon = userinfo.find(":")
    if colon == -1:
        db_user, db_password = userinfo, ""
    else:
        db_user, db_password = userinfo[:colon], userinfo[colon + 1:]

    if ":" in hostport:
        db_host, port_str = hostport.rsplit(":", 1)
        db_port = int(port_str)
    else:
        db_host = hostport
        db_port = 5432

    path = (u.path or "/").lstrip("/")
    db_name = path.split("?")[0] or "postgres"

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


# ---- Domains (queries; la creación cloudflare vive en app/services/cloudflare.py) ----
def list_domains(*, db: Session, settings: Settings, tenant_id: str) -> List[TenantDomain]:
    """List domains for a tenant."""
    return db.exec(
        select(TenantDomain).where(TenantDomain.tenant_id == tenant_id)
    ).all()


def get_domain(*, db: Session, settings: Settings, tenant_id: str, domain_id: str) -> Optional[TenantDomain]:
    """Get domain status and check verification."""
    from app.services.cloudflare import check_domain_status
    domain = db.get(TenantDomain, domain_id)
    if not domain or str(domain.tenant_id) != tenant_id:
        return None
    return check_domain_status(db=db, settings=settings, domain_id=domain_id)


def delete_domain(*, db: Session, settings: Settings, tenant_id: str, domain_id: str) -> bool:
    """Delete a domain (validando que pertenezca al tenant)."""
    from app.services.cloudflare import delete_domain as cf_delete
    domain = db.get(TenantDomain, domain_id)
    if not domain or str(domain.tenant_id) != tenant_id:
        return False
    return cf_delete(db=db, settings=settings, domain_id=domain_id)
