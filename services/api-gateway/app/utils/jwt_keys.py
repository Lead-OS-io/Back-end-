import jwt

from app.config import Settings


def decode_user_token(token: str, settings: Settings) -> dict:
    """Replica la selección de clave por claim `platform` de auth-service/app/security.py:
    desk|hub|nest usan su clave propia (o SECRET_KEY como fallback), algoritmo HS256."""
    unverified = jwt.decode(token, options={"verify_signature": False})
    platform = unverified.get("platform") or unverified.get("system_origin")
    if not platform:
        platform = "desk"
    platform = str(platform).lower()
    key = {
        "desk": settings.DESK_SECRET_KEY,
        "hub": settings.HUB_SECRET_KEY,
        "nest": settings.NEST_SECRET_KEY,
    }.get(platform) or settings.SECRET_KEY
    return jwt.decode(token, key, algorithms=["HS256"])
