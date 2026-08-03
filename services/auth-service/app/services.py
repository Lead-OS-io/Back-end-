"""
Auth Service Business Logic.
"""
from typing import Optional
from datetime import datetime, timedelta
import logging
import httpx

from sqlmodel import Session, select

from app.config import settings
from app.models import User, RefreshToken, LoginAttempt
from app.schemas import UserResponse, LoginResponse
from app.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
    decode_token,
    hash_token,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Authentication service."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate user with email and password."""
        statement = select(User).where(User.email == email)
        user = self.db.exec(statement).first()
        
        if not user:
            return None

        if not verify_password(password, user.password):
            return None
        
        return user
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        return self.db.get(User, user_id)
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        statement = select(User).where(User.email == email)
        return self.db.exec(statement).first()
    
    def create_user(
        self,
        email: str,
        password: str,
        tenant_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        role_id: Optional[int] = None,
    ) -> User:
        """Create a new user."""
        user = User(
            email=email,
            password=get_password_hash(password),
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            role_id=role_id,
            is_active=True,
            date_joined=datetime.utcnow(),
            created_at=datetime.utcnow(),
            modified_at=datetime.utcnow(),
        )
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        return user
    
    def update_password(self, user: User, new_password: str) -> User:
        """Update user password and mark first login as completed."""
        user.password = get_password_hash(new_password)
        user.password_recovery_token = None
        user.first_login = False
        user.modified_at = datetime.utcnow()
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        return user
    
    def update_last_login(self, user: User) -> None:
        """Update user's last login timestamp."""
        user.last_login = datetime.utcnow()
        self.db.add(user)
        self.db.commit()
    
    def create_tokens(
        self,
        user: User,
        platform: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Create access and refresh tokens for user, persisting the refresh token so it can be revoked/rotated."""
        tenant_id = str(getattr(user, "tenant_id", "") or "")
        if not tenant_id:
            # fallback legacy (si faltara tenant_id en la fila)
            tenant_id = self._resolve_tenant_id(user.email)
        access_token = create_access_token(
            user_id=str(user.id),
            tenant_id=tenant_id,
            email=user.email,
            platform=platform,
            role_id=user.role_id,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        refresh_token = create_refresh_token(
            user_id=str(user.id),
            tenant_id=tenant_id,
        )

        self.db.add(RefreshToken(
            user_id=user.id,
            tenant_id=tenant_id,
            token_hash=hash_token(refresh_token),
            device_info=(user_agent[:255] if user_agent else None),
            ip_address=ip_address,
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ))
        self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def refresh_access_token(
        self,
        refresh_token: str,
        platform: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """Exchange a valid, unrevoked refresh token for a new access/refresh pair.

        The old refresh token is revoked (rotation) so a stolen token can't be replayed
        after its first legitimate use.
        """
        try:
            payload = decode_token(refresh_token)
        except ValueError:
            raise ValueError("Invalid refresh token")
        if payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")

        token_hash = hash_token(refresh_token)
        stored = self.db.exec(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).first()
        if not stored or stored.is_revoked or stored.expires_at < datetime.utcnow():
            raise ValueError("Refresh token is invalid, revoked, or expired")

        user = self.get_user_by_id(payload.get("sub"))
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")

        stored.is_revoked = True
        self.db.add(stored)

        tokens = self.create_tokens(user, platform=platform, ip_address=ip_address, user_agent=user_agent)
        tokens["user_id"] = str(user.id)
        tokens["email"] = user.email
        return tokens

    def revoke_refresh_token(self, refresh_token: str) -> None:
        """Revoke a refresh token (logout). Silently no-ops if it's unknown/already revoked."""
        stored = self.db.exec(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        ).first()
        if stored and not stored.is_revoked:
            stored.is_revoked = True
            self.db.add(stored)
            self.db.commit()
    
    def _resolve_tenant_id(self, email: str) -> str:
        """Resolve tenant_id via tenant-service using user email."""
        if not email:
            raise ValueError("Email required to resolve tenant")
        url = f"{settings.TENANT_SERVICE_URL}/api/resolve/email"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, params={"email": email})
                if resp.status_code == 404:
                    raise ValueError("Tenant not found for user email")
                resp.raise_for_status()
                data = resp.json()
                tenant_id = data.get("id")
                if not tenant_id:
                    raise ValueError("Tenant resolution missing id")
                return tenant_id
        except Exception as e:
            raise ValueError(f"Failed to resolve tenant: {e}")
    
    def log_login_attempt(
        self,
        email: str,
        ip_address: str,
        success: bool,
        failure_reason: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Log a login attempt."""
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success,
            failure_reason=failure_reason,
            user_agent=user_agent[:500] if user_agent else None,
        )
        
        self.db.add(attempt)
        self.db.commit()
    
    def check_admin_status(self, user: User) -> dict:
        """Check if user has admin privileges."""
        is_admin = False
        permissions = []
        
        # Check role_id
        if user.role_id in [1, 2]:
            is_admin = True
            permissions.append("admin_role")
        
        # Check is_superuser or is_staff
        if user.is_superuser:
            is_admin = True
            permissions.append("superuser")
        elif user.is_staff:
            is_admin = True
            permissions.append("staff")
        
        return {
            "isAdmin": is_admin,
            "permissions": permissions,
        }
    
    async def send_password_reset_email(self, user: User) -> bool:
        """Generate and store the reset token. Email delivery is disabled:
        mailing-service was removed; wire the new mailer here when it exists."""
        reset_token = create_password_reset_token(str(user.id))

        # Store token in user record
        user.password_recovery_token = reset_token
        self.db.add(user)
        self.db.commit()

        logger.warning(
            f"Password reset requested for {user.email} but no mailing service is "
            f"configured — token stored, email NOT sent."
        )
        return False
    
    def verify_reset_token(self, token: str) -> Optional[User]:
        """Verify password reset token and return user."""
        user_id = verify_password_reset_token(token)
        if not user_id:
            return None
        
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        
        # Verify token matches stored token
        if user.password_recovery_token != token:
            return None
        
        return user

