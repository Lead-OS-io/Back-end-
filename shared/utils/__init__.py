"""
Shared utilities for AireDesk microservices.
"""
from shared.utils.exceptions import (
    ServiceException,
    NotFoundError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    RateLimitError,
    ServiceUnavailableError,
)
from shared.utils.logging import get_logger, setup_logging
from shared.utils.http_client import ServiceClient

__all__ = [
    "ServiceException",
    "NotFoundError",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "RateLimitError",
    "ServiceUnavailableError",
    "get_logger",
    "setup_logging",
    "ServiceClient",
]

