"""
JWT handling for all microservices.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import jwt
from pydantic import BaseModel, ValidationError

from shared.schemas.user import TokenPayload
from shared.utils.exceptions import AuthenticationError


class JWTConfig(BaseModel):
    """JWT configuration."""
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    refresh_token_expire_days: int = 7


class JWTHandler:
    """JWT token handler."""
    
    def __init__(self, config: JWTConfig):
        self.config = config
    
    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        role_id: Optional[int] = None,
        is_staff: bool = False,
        is_superuser: bool = False,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create an access token."""
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.config.access_token_expire_minutes)
        
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "role_id": role_id,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "exp": expire,
            "iat": now,
            "type": "access",
        }
        
        if extra_claims:
            payload.update(extra_claims)
        
        return jwt.encode(
            payload,
            self.config.secret_key,
            algorithm=self.config.algorithm,
        )
    
    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
    ) -> str:
        """Create a refresh token."""
        now = datetime.utcnow()
        expire = now + timedelta(days=self.config.refresh_token_expire_days)
        
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }
        
        return jwt.encode(
            payload,
            self.config.secret_key,
            algorithm=self.config.algorithm,
        )
    
    def decode(self, token: str, expected_type: Optional[str] = "access") -> TokenPayload:
        """Decode and validate a token. Verifies signature, expiry, and (unless
        expected_type=None) that the token's `type` claim matches expected_type -
        blocks a refresh/service/reset token from being used where an access
        token is required (and vice versa)."""
        try:
            payload = jwt.decode(
                token,
                self.config.secret_key,
                algorithms=[self.config.algorithm],
            )
            if expected_type is not None and payload.get("type") != expected_type:
                raise AuthenticationError(
                    f"Invalid token type: expected '{expected_type}', got '{payload.get('type')}'"
                )
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {e}")
        except ValidationError as e:
            raise AuthenticationError(f"Malformed token payload: {e}")
    
    def verify(self, token: str) -> bool:
        """Verify a token is valid."""
        try:
            self.decode(token)
            return True
        except AuthenticationError:
            return False


# Global functions for simple use cases
_jwt_handler: Optional[JWTHandler] = None


def init_jwt(config: JWTConfig) -> JWTHandler:
    """Initialize the global JWT handler."""
    global _jwt_handler
    _jwt_handler = JWTHandler(config)
    return _jwt_handler


def get_jwt_handler() -> JWTHandler:
    """Get the global JWT handler."""
    if _jwt_handler is None:
        raise RuntimeError("JWT handler not initialized. Call init_jwt() first.")
    return _jwt_handler


def decode_token(token: str, expected_type: Optional[str] = "access") -> TokenPayload:
    """Decode a token using the global handler."""
    return get_jwt_handler().decode(token, expected_type=expected_type)


def verify_token(token: str) -> bool:
    """Verify a token using the global handler."""
    return get_jwt_handler().verify(token)

