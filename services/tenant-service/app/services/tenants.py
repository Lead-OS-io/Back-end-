"""
Tenant Service Business Logic.
"""
import logging
import secrets
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Tenant, TenantDomain, TenantStatus, DomainStatus,
    DEFAULT_LIMITS, DEFAULT_FEATURES,
)
from app.cloudflare import cloudflare_client

logger = logging.getLogger(__name__)


class TenantService:
    """Tenant management service."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_tenant(
        self,
        name: str,
        slug: str,
        owner_email: str,
        settings: Optional[Dict[str, Any]] = None,
        branding: Optional[Dict[str, Any]] = None,
    ) -> Tenant:
        """Create a new tenant."""
        # Validate slug
        if not re.match(r"^[a-z0-9-]+$", slug):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        
        # Check if slug already exists
        existing = self.db.exec(
            select(Tenant).where(Tenant.slug == slug)
        ).first()
        
        if existing:
            raise ValueError(f"Tenant with slug '{slug}' already exists")
        
        # Default limits/features (no subscription plans)
        limits = dict(DEFAULT_LIMITS or {})
        features = dict(DEFAULT_FEATURES or {})
        
        # Create tenant
        tenant = Tenant(
            name=name,
            slug=slug,
            owner_email=owner_email,
            status=TenantStatus.TRIAL,
            trial_ends_at=datetime.utcnow() + timedelta(days=14),
            settings=settings or {},
            branding=branding or {},
            limits=limits,
            features=features,
        )
        
        self.db.add(tenant)
        self.db.commit()
        self.db.refresh(tenant)
        
        logger.info(f"Created tenant: {tenant.id} ({tenant.slug})")
        return tenant
    
    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self.db.get(Tenant, tenant_id)
    
    def get_tenant_by_slug(self, slug: str) -> Optional[Tenant]:
        """Get tenant by slug."""
        return self.db.exec(
            select(Tenant).where(Tenant.slug == slug)
        ).first()
    
    def get_tenant_by_domain(self, domain: str) -> Optional[Tenant]:
        """Get tenant by custom domain."""
        # Check primary custom domain
        tenant = self.db.exec(
            select(Tenant).where(Tenant.custom_domain == domain)
        ).first()
        
        if tenant:
            return tenant
        
        # Check additional domains
        tenant_domain = self.db.exec(
            select(TenantDomain).where(
                TenantDomain.domain == domain,
                TenantDomain.status == DomainStatus.ACTIVE,
            )
        ).first()
        
        if tenant_domain:
            return self.get_tenant(str(tenant_domain.tenant_id))
        
        return None

    def get_tenant_by_email(self, email: str) -> Optional[Tenant]:
        """Resolve tenant by owner/billing email (case-insensitive)."""
        if not email:
            return None
        normalized = email.strip().lower()
        tenant = self.db.exec(
            select(Tenant).where(
                (Tenant.owner_email == normalized) | (Tenant.billing_email == normalized)
            )
        ).first()
        return tenant
    
    def update_tenant(
        self,
        tenant_id: str,
        **updates,
    ) -> Optional[Tenant]:
        """Update a tenant."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return None
        
        for key, value in updates.items():
            if value is not None and hasattr(tenant, key):
                setattr(tenant, key, value)
        
        tenant.modified_at = datetime.utcnow()
        
        self.db.add(tenant)
        self.db.commit()
        self.db.refresh(tenant)
        
        return tenant
    
    def list_tenants(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[TenantStatus] = None,
    ) -> tuple[List[Tenant], int]:
        """List tenants with pagination."""
        from sqlmodel import func
        
        query = select(Tenant)
        
        if status:
            query = query.where(Tenant.status == status)
        
        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.exec(count_query).one()
        
        # Paginate
        query = query.order_by(Tenant.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        
        tenants = self.db.exec(query).all()
        return tenants, total
    
    def resolve_tenant(self, host: str) -> Optional[Tenant]:
        """Resolve tenant from host header."""
        if not host:
            return None
        
        # Remove port if present
        domain = host.split(":")[0].lower()
        
        # Check if it's a subdomain of base domain
        base_domain = settings.BASE_DOMAIN.lower()
        if domain.endswith(f".{base_domain}"):
            slug = domain.replace(f".{base_domain}", "")
            if slug and slug != "www":
                return self.get_tenant_by_slug(slug)
        
        # Check custom domain
        return self.get_tenant_by_domain(domain)


class DomainService:
    """Domain management service."""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def create_subdomain(
        self,
        tenant_id: str,
        subdomain: str,
    ) -> TenantDomain:
        """Create a subdomain for a tenant (fully automatic)."""
        # Validate subdomain
        if not re.match(r"^[a-z0-9-]+$", subdomain):
            raise ValueError("Subdomain must contain only lowercase letters, numbers, and hyphens")
        
        full_domain = f"{subdomain}.{settings.BASE_DOMAIN}"
        
        # Check if already exists
        existing = self.db.exec(
            select(TenantDomain).where(TenantDomain.domain == full_domain)
        ).first()
        
        if existing:
            raise ValueError(f"Subdomain '{subdomain}' is already taken")
        
        # Create DNS record in Cloudflare
        dns_record = await cloudflare_client.create_dns_record(
            name=subdomain,
            content=settings.CNAME_TARGET,
            record_type="CNAME",
            proxied=True,
        )
        
        # Create domain record
        domain = TenantDomain(
            tenant_id=tenant_id,
            domain=full_domain,
            domain_type="subdomain",
            status=DomainStatus.ACTIVE,  # Subdomains are immediately active
            cloudflare_record_id=dns_record.get("id"),
            ssl_status="active",  # Cloudflare handles SSL
            verified_at=datetime.utcnow(),
        )
        
        self.db.add(domain)
        self.db.commit()
        self.db.refresh(domain)
        
        logger.info(f"Created subdomain: {full_domain} for tenant {tenant_id}")
        return domain
    
    async def create_custom_domain(
        self,
        tenant_id: str,
        domain: str,
    ) -> TenantDomain:
        """Create a custom domain for a tenant (requires DNS verification)."""
        # Normalize domain
        domain = domain.lower().strip()
        
        # Check if already exists
        existing = self.db.exec(
            select(TenantDomain).where(TenantDomain.domain == domain)
        ).first()
        
        if existing:
            raise ValueError(f"Domain '{domain}' is already registered")
        
        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        
        # Create custom hostname in Cloudflare for SaaS
        hostname_result = await cloudflare_client.create_custom_hostname(domain)
        
        # Create domain record
        tenant_domain = TenantDomain(
            tenant_id=tenant_id,
            domain=domain,
            domain_type="custom",
            status=DomainStatus.PENDING,
            cloudflare_hostname_id=hostname_result.get("id"),
            verification_token=verification_token,
            ssl_status="pending_validation",
        )
        
        self.db.add(tenant_domain)
        self.db.commit()
        self.db.refresh(tenant_domain)
        
        logger.info(f"Created custom domain: {domain} for tenant {tenant_id}")
        return tenant_domain
    
    def get_verification_instructions(self, domain: TenantDomain) -> Dict[str, Any]:
        """Get DNS verification instructions for a custom domain."""
        return {
            "domain": domain.domain,
            "status": domain.status,
            "verification_type": "CNAME",
            "verification_record": {
                "type": "CNAME",
                "name": domain.domain,
                "value": settings.CNAME_TARGET,
            },
            "instructions": f"""
To verify your domain, create a CNAME record in your DNS provider:

Type: CNAME
Name: {domain.domain} (or @ for root domain)
Value: {settings.CNAME_TARGET}

Note: DNS changes can take up to 48 hours to propagate.
Once the CNAME is set up, we will automatically verify and activate your domain.
""".strip(),
        }
    
    async def check_domain_status(self, domain_id: str) -> Optional[TenantDomain]:
        """Check and update domain verification status."""
        domain = self.db.get(TenantDomain, domain_id)
        if not domain:
            return None
        
        if domain.status == DomainStatus.ACTIVE:
            return domain
        
        if domain.cloudflare_hostname_id:
            # Check Cloudflare custom hostname status
            hostname = await cloudflare_client.get_custom_hostname(
                domain.cloudflare_hostname_id
            )
            
            if hostname:
                cf_status = hostname.get("status", "pending")
                ssl_status = hostname.get("ssl", {}).get("status", "pending")
                
                if cf_status == "active":
                    domain.status = DomainStatus.ACTIVE
                    domain.verified_at = datetime.utcnow()
                elif cf_status == "pending":
                    domain.status = DomainStatus.VERIFYING
                elif cf_status in ["moved", "deleted"]:
                    domain.status = DomainStatus.FAILED
                
                domain.ssl_status = ssl_status
                domain.modified_at = datetime.utcnow()
                
                self.db.add(domain)
                self.db.commit()
                self.db.refresh(domain)
        
        return domain
    
    async def delete_domain(self, domain_id: str) -> bool:
        """Delete a domain."""
        domain = self.db.get(TenantDomain, domain_id)
        if not domain:
            return False
        
        # Delete from Cloudflare
        if domain.cloudflare_record_id:
            await cloudflare_client.delete_dns_record(domain.cloudflare_record_id)
        
        if domain.cloudflare_hostname_id:
            await cloudflare_client.delete_custom_hostname(domain.cloudflare_hostname_id)
        
        self.db.delete(domain)
        self.db.commit()
        
        logger.info(f"Deleted domain: {domain.domain}")
        return True
    
    def list_domains(self, tenant_id: str) -> List[TenantDomain]:
        """List domains for a tenant."""
        return self.db.exec(
            select(TenantDomain).where(TenantDomain.tenant_id == tenant_id)
        ).all()

