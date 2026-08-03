"""
HTTP client for inter-service communication.
"""
import httpx
from typing import Optional, Dict, Any, TypeVar, Type
from pydantic import BaseModel
import logging

from shared.utils.exceptions import ServiceUnavailableError, NotFoundError, AuthenticationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ServiceClient:
    """HTTP client for calling other microservices."""
    
    def __init__(
        self,
        base_url: str,
        service_name: str,
        timeout: float = 30.0,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout = timeout
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-Service-Key"] = self.api_key
            
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def _prepare_headers(
        self,
        tenant_id: Optional[str] = None,
        user_token: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        headers = {}
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id
        if user_token:
            headers["Authorization"] = f"Bearer {user_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers
    
    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        user_token: Optional[str] = None,
        response_model: Optional[Type[T]] = None,
    ) -> Any:
        """Make a GET request."""
        client = await self._get_client()
        headers = self._prepare_headers(tenant_id, user_token)
        
        try:
            response = await client.get(path, params=params, headers=headers)
            return self._handle_response(response, response_model)
        except httpx.RequestError as e:
            logger.error(f"Request to {self.service_name} failed: {e}")
            raise ServiceUnavailableError(service=self.service_name)
    
    async def post(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        user_token: Optional[str] = None,
        response_model: Optional[Type[T]] = None,
    ) -> Any:
        """Make a POST request."""
        client = await self._get_client()
        headers = self._prepare_headers(tenant_id, user_token)
        
        try:
            response = await client.post(path, json=data, headers=headers)
            return self._handle_response(response, response_model)
        except httpx.RequestError as e:
            logger.error(f"Request to {self.service_name} failed: {e}")
            raise ServiceUnavailableError(service=self.service_name)
    
    async def put(
        self,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
        user_token: Optional[str] = None,
        response_model: Optional[Type[T]] = None,
    ) -> Any:
        """Make a PUT request."""
        client = await self._get_client()
        headers = self._prepare_headers(tenant_id, user_token)
        
        try:
            response = await client.put(path, json=data, headers=headers)
            return self._handle_response(response, response_model)
        except httpx.RequestError as e:
            logger.error(f"Request to {self.service_name} failed: {e}")
            raise ServiceUnavailableError(service=self.service_name)
    
    async def delete(
        self,
        path: str,
        tenant_id: Optional[str] = None,
        user_token: Optional[str] = None,
    ) -> bool:
        """Make a DELETE request."""
        client = await self._get_client()
        headers = self._prepare_headers(tenant_id, user_token)
        
        try:
            response = await client.delete(path, headers=headers)
            if response.status_code == 204:
                return True
            self._handle_response(response)
            return True
        except httpx.RequestError as e:
            logger.error(f"Request to {self.service_name} failed: {e}")
            raise ServiceUnavailableError(service=self.service_name)
    
    def _handle_response(
        self,
        response: httpx.Response,
        response_model: Optional[Type[T]] = None,
    ) -> Any:
        """Handle HTTP response and errors."""
        if response.status_code == 404:
            raise NotFoundError()
        elif response.status_code == 401:
            raise AuthenticationError()
        elif response.status_code >= 500:
            raise ServiceUnavailableError(service=self.service_name)
        elif response.status_code >= 400:
            try:
                error_data = response.json()
                raise ServiceUnavailableError(
                    message=error_data.get("detail", "Request failed"),
                    service=self.service_name,
                )
            except Exception:
                raise ServiceUnavailableError(service=self.service_name)
        
        if response_model:
            return response_model.model_validate(response.json())
        
        try:
            return response.json()
        except Exception:
            return response.text

