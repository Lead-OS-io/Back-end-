"""
Cloudflare API integration for domain management + domain business logic.
"""
import logging
import secrets
import re
from datetime import datetime
from typing import Optional, Dict, Any

import httpx
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.models import TenantDomain, DomainStatus

logger = logging.getLogger(__name__)


class CloudflareClient:
    """Cloudflare API client for DNS and Custom Hostnames management."""

    def __init__(self):
        self.api_token = app_settings.CLOUDFLARE_API_TOKEN
        self.zone_id = app_settings.CLOUDFLARE_ZONE_ID
        self.account_id = app_settings.CLOUDFLARE_ACCOUNT_ID
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token and self.zone_id)

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make API request to Cloudflare."""
        url = f"{self.base_url}{endpoint}"

        response = await self._client.request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
        )

        result = response.json()

        if not result.get("success", False):
            errors = result.get("errors", [])
            error_msg = "; ".join([e.get("message", "Unknown error") for e in errors])
            logger.error(f"Cloudflare API error: {error_msg}")
            raise Exception(f"Cloudflare API error: {error_msg}")

        return result

    # DNS Records
    async def create_dns_record(
        self,
        name: str,
        content: str,
        record_type: str = "CNAME",
        proxied: bool = True,
        ttl: int = 1,  # 1 = automatic
    ) -> Dict[str, Any]:
        """Create a DNS record."""
        if not self.is_configured:
            logger.warning("Cloudflare not configured, skipping DNS record creation")
            return {"id": "mock-dns-id", "name": name}

        data = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
            "ttl": ttl,
        }

        result = await self._request(
            "POST",
            f"/zones/{self.zone_id}/dns_records",
            data,
        )

        return result.get("result", {})

    async def delete_dns_record(self, record_id: str) -> bool:
        """Delete a DNS record."""
        if not self.is_configured:
            return True

        try:
            await self._request(
                "DELETE",
                f"/zones/{self.zone_id}/dns_records/{record_id}",
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete DNS record: {e}")
            return False

    async def get_dns_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Get a DNS record by ID."""
        if not self.is_configured:
            return None

        try:
            result = await self._request(
                "GET",
                f"/zones/{self.zone_id}/dns_records/{record_id}",
            )
            return result.get("result")
        except Exception:
            return None

    # Custom Hostnames (Cloudflare for SaaS)
    async def create_custom_hostname(
        self,
        hostname: str,
        ssl_method: str = "http",
    ) -> Dict[str, Any]:
        """Create a custom hostname for Cloudflare for SaaS."""
        if not self.is_configured:
            logger.warning("Cloudflare not configured, skipping custom hostname creation")
            return {
                "id": "mock-hostname-id",
                "hostname": hostname,
                "status": "pending",
                "ssl": {"status": "pending_validation"},
            }

        data = {
            "hostname": hostname,
            "ssl": {
                "method": ssl_method,
                "type": "dv",
                "settings": {
                    "min_tls_version": "1.2",
                },
            },
        }

        result = await self._request(
            "POST",
            f"/zones/{self.zone_id}/custom_hostnames",
            data,
        )

        return result.get("result", {})

    async def get_custom_hostname(self, hostname_id: str) -> Optional[Dict[str, Any]]:
        """Get custom hostname status."""
        if not self.is_configured:
            return None

        try:
            result = await self._request(
                "GET",
                f"/zones/{self.zone_id}/custom_hostnames/{hostname_id}",
            )
            return result.get("result")
        except Exception:
            return None

    async def delete_custom_hostname(self, hostname_id: str) -> bool:
        """Delete a custom hostname."""
        if not self.is_configured:
            return True

        try:
            await self._request(
                "DELETE",
                f"/zones/{self.zone_id}/custom_hostnames/{hostname_id}",
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete custom hostname: {e}")
            return False

    async def verify_connection(self) -> bool:
        """Verify Cloudflare connection."""
        if not self.is_configured:
            return False

        try:
            result = await self._request("GET", f"/zones/{self.zone_id}")
            return result.get("success", False)
        except Exception:
            return False


# Global client instance
cloudflare_client = CloudflareClient()


# ---- Domain business logic (módulo, facade via controller) ----
async def create_subdomain(*, db: Session, settings, tenant_id: str, subdomain: str) -> TenantDomain:
    """Create a subdomain for a tenant (fully automatic)."""
    if not re.match(r"^[a-z0-9-]+$", subdomain):
        raise ValueError("Subdomain must contain only lowercase letters, numbers, and hyphens")

    full_domain = f"{subdomain}.{settings.BASE_DOMAIN}"

    existing = db.exec(
        select(TenantDomain).where(TenantDomain.domain == full_domain)
    ).first()
    if existing:
        raise ValueError(f"Subdomain '{subdomain}' is already taken")

    dns_record = await cloudflare_client.create_dns_record(
        name=subdomain,
        content=settings.CNAME_TARGET,
        record_type="CNAME",
        proxied=True,
    )

    domain = TenantDomain(
        tenant_id=tenant_id,
        domain=full_domain,
        domain_type="subdomain",
        status=DomainStatus.ACTIVE,  # Subdomains are immediately active
        cloudflare_record_id=dns_record.get("id"),
        ssl_status="active",  # Cloudflare handles SSL
        verified_at=datetime.utcnow(),
    )

    db.add(domain)
    db.commit()
    db.refresh(domain)

    logger.info(f"Created subdomain: {full_domain} for tenant {tenant_id}")
    return domain


async def create_custom_domain(*, db: Session, settings, tenant_id: str, domain: str) -> TenantDomain:
    """Create a custom domain for a tenant (requires DNS verification)."""
    domain = domain.lower().strip()

    existing = db.exec(
        select(TenantDomain).where(TenantDomain.domain == domain)
    ).first()
    if existing:
        raise ValueError(f"Domain '{domain}' is already registered")

    verification_token = secrets.token_urlsafe(32)

    hostname_result = await cloudflare_client.create_custom_hostname(domain)

    tenant_domain = TenantDomain(
        tenant_id=tenant_id,
        domain=domain,
        domain_type="custom",
        status=DomainStatus.PENDING,
        cloudflare_hostname_id=hostname_result.get("id"),
        verification_token=verification_token,
        ssl_status="pending_validation",
    )

    db.add(tenant_domain)
    db.commit()
    db.refresh(tenant_domain)

    logger.info(f"Created custom domain: {domain} for tenant {tenant_id}")
    return tenant_domain


def get_verification_instructions(*, db: Session, settings, domain: TenantDomain) -> Dict[str, Any]:
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


async def check_domain_status(*, db: Session, settings, domain_id: str) -> Optional[TenantDomain]:
    """Check and update domain verification status."""
    domain = db.get(TenantDomain, domain_id)
    if not domain:
        return None

    if domain.status == DomainStatus.ACTIVE:
        return domain

    if domain.cloudflare_hostname_id:
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

            db.add(domain)
            db.commit()
            db.refresh(domain)

    return domain


async def delete_domain(*, db: Session, settings, domain_id: str) -> bool:
    """Delete a domain."""
    domain = db.get(TenantDomain, domain_id)
    if not domain:
        return False

    if domain.cloudflare_record_id:
        await cloudflare_client.delete_dns_record(domain.cloudflare_record_id)

    if domain.cloudflare_hostname_id:
        await cloudflare_client.delete_custom_hostname(domain.cloudflare_hostname_id)

    db.delete(domain)
    db.commit()

    logger.info(f"Deleted domain: {domain.domain}")
    return True
