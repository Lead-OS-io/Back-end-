"""
Shared exceptions for all microservices.
"""
from typing import Optional, Dict, Any


class ServiceException(Exception):
    """Base exception for all services."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code or "INTERNAL_ERROR"
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "detail": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class NotFoundError(ServiceException):
    """Resource not found."""
    
    def __init__(self, message: str = "Resource not found", resource: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="NOT_FOUND",
            status_code=404,
            details={"resource": resource} if resource else {},
        )


class ValidationError(ServiceException):
    """Validation error."""
    
    def __init__(self, message: str = "Validation error", field_errors: Optional[Dict[str, str]] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=422,
            details={"field_errors": field_errors} if field_errors else {},
        )


class AuthenticationError(ServiceException):
    """Authentication failed."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=401,
        )


class AuthorizationError(ServiceException):
    """Authorization failed."""
    
    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
        )


class RateLimitError(ServiceException):
    """Rate limit exceeded."""
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: Optional[int] = None):
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={"retry_after": retry_after} if retry_after else {},
        )


class ServiceUnavailableError(ServiceException):
    """Service unavailable."""
    
    def __init__(self, message: str = "Service temporarily unavailable", service: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
            details={"service": service} if service else {},
        )


class TenantNotFoundError(NotFoundError):
    """Tenant not found."""
    
    def __init__(self, tenant_id: Optional[str] = None):
        super().__init__(
            message=f"Tenant not found: {tenant_id}" if tenant_id else "Tenant not found",
            resource="tenant",
        )


class UserNotFoundError(NotFoundError):
    """User not found."""
    
    def __init__(self, user_id: Optional[str] = None):
        super().__init__(
            message=f"User not found: {user_id}" if user_id else "User not found",
            resource="user",
        )

