"""
Cloudflare API integration for domain management.
"""
import logging
from typing import Optional, Dict, Any
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CloudflareClient:
    """Cloudflare API client for DNS and Custom Hostnames management."""
    
    def __init__(self):
        self.api_token = settings.CLOUDFLARE_API_TOKEN
        self.zone_id = settings.CLOUDFLARE_ZONE_ID
        self.account_id = settings.CLOUDFLARE_ACCOUNT_ID
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        # Pooled client reused across requests instead of opening a new
        # connection (and doing a fresh TLS handshake) on every call.
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

