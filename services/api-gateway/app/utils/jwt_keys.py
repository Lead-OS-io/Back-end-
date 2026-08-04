import jwt

from app.config import Settings


def decode_user_token(token: str, settings: Settings) -> dict:
    """Decodifica el JWT de usuario firmado con SECRET_KEY (HS256) por auth-service."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
