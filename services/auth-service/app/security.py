"""
Security utilities for Auth Service.
Password hashing, JWT tokens, encryption.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hashlib
import logging
import secrets

from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import InvalidHashError, UnknownHashError
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

# Password hashing context
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,
)


class Encryption:
    """Fernet encryption for sensitive data."""
    
    _fernets: Optional[list[Fernet]] = None
    
    @classmethod
    def _get_fernets(cls) -> list[Fernet]:
        if cls._fernets is not None:
            return cls._fernets

        # Preferimos la key explícita para passwords si existe; fallback a FERNET_KEY.
        # Incluimos keys de otros servicios (DESK, HUB, NEST) para compatibilidad con legacy/migraciones.
        keys_raw = [
            settings.PASSWORD_FERNET_KEY,
            settings.FERNET_KEY,
            settings.DESK_FERNET_KEY,
            settings.HUB_FERNET_KEY,
            settings.NEST_FERNET_KEY
        ]
        
        # Filtrar vacías y duplicados manteniendo el orden
        seen = set()
        keys = []
        for k in keys_raw:
            k_clean = (k or "").strip()
            if k_clean and k_clean not in seen:
                keys.append(k_clean)
                seen.add(k_clean)

        cls._fernets = []
        for key in keys:
            try:
                cls._fernets.append(Fernet(key.encode()))
            except Exception as e:
                # Log error but continue with other keys
                from app.config import settings as app_settings
                if app_settings.DEBUG:
                    print(f"Invalid Fernet key in auth-service: {e}")
        
        return cls._fernets
    
    @classmethod
    def encrypt(cls, data: str) -> str:
        """Encrypt a string. Fails hard rather than silently storing the
        plaintext (this protects live secrets like Google refresh tokens,
        not just password hashes)."""
        fernets = cls._get_fernets()
        if not fernets:
            raise RuntimeError(
                "No Fernet key configured (FERNET_KEY/PASSWORD_FERNET_KEY/"
                "DESK_FERNET_KEY/HUB_FERNET_KEY/NEST_FERNET_KEY) - refusing "
                "to store this value unencrypted."
            )
        # Encriptamos con la primera (preferida)
        return fernets[0].encrypt(data.encode()).decode()

    @classmethod
    def decrypt(cls, data: str) -> Optional[str]:
        """Decrypt a string."""
        fernets = cls._get_fernets()
        if not fernets:
            raise RuntimeError(
                "No Fernet key configured (FERNET_KEY/PASSWORD_FERNET_KEY/"
                "DESK_FERNET_KEY/HUB_FERNET_KEY/NEST_FERNET_KEY) - cannot decrypt."
            )
        for f in fernets:
            try:
                return f.decrypt(data.encode()).decode()
            except InvalidToken:
                continue
            except Exception:
                continue
        return None


def verify_password(plain_password: str, stored_password: str) -> bool:
    """
    Verify password against stored hash.
    Soporta:
    - bcrypt ($2...)
    - Fernet(bcrypt) / Fernet(pbkdf2_sha256)
    """
    if not stored_password:
        return False

    # Si ya viene como hash en claro (sin cifrar), no intentamos decrypt.
    if stored_password.startswith("$2"):
        decrypted = stored_password
    else:
        # Intentar decrypt (gAAAA... u otros tokens)
        try:
            decrypted = Encryption.decrypt(stored_password)
        except RuntimeError:
            logging.getLogger(__name__).error("Password decrypt failed: no Fernet key configured")
            return False
        if not decrypted:
            return False

    # bcrypt
    if decrypted.startswith("$2"):
        try:
            candidate = plain_password or ""
            if isinstance(candidate, str):
                candidate_bytes = candidate.encode("utf-8")
            else:
                candidate_bytes = bytes(candidate)

            # bcrypt truncates at 72 bytes
            if len(candidate_bytes) > 72:
                candidate = candidate_bytes[:72].decode("utf-8", errors="ignore")

            return pwd_context.verify(candidate, decrypted)
        except (InvalidHashError, UnknownHashError, ValueError):
            return False
        except Exception:
            return False

    return False


def get_password_hash(password: str) -> str:
    """Hash password with bcrypt and encrypt with Fernet."""
    candidate = password or ""
    if isinstance(candidate, str):
        candidate_bytes = candidate.encode("utf-8")
    else:
        candidate_bytes = bytes(candidate)
    
    if len(candidate_bytes) > 72:
        candidate = candidate_bytes[:72].decode("utf-8", errors="ignore")
    
    bcrypt_hash = pwd_context.hash(candidate)
    return Encryption.encrypt(bcrypt_hash)


def _get_platform_key(platform: str) -> str:
    key_map = {
        "desk": settings.DESK_SECRET_KEY or settings.SECRET_KEY,
        "hub": settings.HUB_SECRET_KEY or settings.SECRET_KEY,
        "nest": settings.NEST_SECRET_KEY or settings.SECRET_KEY,
    }
    key = key_map.get(platform)
    if not key:
        return settings.SECRET_KEY
    return key


def create_access_token(
    user_id: str,
    tenant_id: str,
    email: str,
    platform: str,
    role_id: Optional[int] = None,
    is_staff: bool = False,
    is_superuser: bool = False,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create JWT access token firmado con la clave específica de la plataforma."""
    if not platform:
        # Check platform but we will use SECRET_KEY anyway
        pass 

    platform_norm = str(platform).lower() if platform else "desk"
    key = _get_platform_key(platform_norm)

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "role_id": role_id if role_id is not None else None,  # Explicitly include None
        "is_staff": bool(is_staff),  # Ensure boolean
        "is_superuser": bool(is_superuser),  # Ensure boolean
        "first_name": first_name or "",
        "last_name": last_name or "",
        "platform": platform_norm,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access",
    }
    
    return jwt.encode(payload, key, algorithm=settings.ALGORITHM)


def create_service_token(
    tenant_id: str,
    expires_minutes: int = 60 * 24,
) -> str:
    """Create a service token bound to a tenant."""
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    payload = {
        "tenant_id": tenant_id,
        "type": "service",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    """Create refresh token."""
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
    }
    
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT token usando la clave específica de la plataforma.
    Sin fallbacks: requiere que el token traiga claim 'platform' (desk|hub|nest).
    """
    try:
        claims = jwt.get_unverified_claims(token)
    except Exception as e:
        raise ValueError(f"Invalid token (cannot read claims): {e}")

    platform = claims.get("platform") or claims.get("system_origin")
    if not platform:
        # Fallback for legacy tokens (default to 'desk')
        platform = "desk"

    platform = str(platform).lower()
    key_map = {
        "desk": settings.DESK_SECRET_KEY or settings.SECRET_KEY,
        "hub": settings.HUB_SECRET_KEY or settings.SECRET_KEY,
        "nest": settings.NEST_SECRET_KEY or settings.SECRET_KEY,
    }
    key = key_map.get(platform)
    if not key:
        key = settings.SECRET_KEY

    try:
        return jwt.decode(token, key, algorithms=[settings.ALGORITHM])
    except JWTError:
        # No fallback to SECRET_KEY: refresh/service tokens are signed with it,
        # so accepting it here would collapse platform key separation.
        raise ValueError("Invalid token (signature failed)")


def create_password_reset_token(user_id: str) -> str:
    """Create password reset token."""
    expire = datetime.utcnow() + timedelta(hours=1)
    
    payload = {
        "sub": user_id,
        "pr": True,  # password reset flag
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password_reset_token(token: str) -> Optional[str]:
    """Verify password reset token and return user_id."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        if not payload.get("pr"):
            return None
        return payload.get("sub")
    except JWTError:
        return None


def hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()

