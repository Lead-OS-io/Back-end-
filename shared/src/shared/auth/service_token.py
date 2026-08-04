from datetime import UTC, datetime, timedelta

import jwt


def mint_service_token(*, secret: str, issuer: str, ttl_seconds: int = 60) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "type": "service",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_service_token(token: str, *, secret: str) -> dict:
    claims = jwt.decode(token, secret, algorithms=["HS256"])
    if claims.get("type") != "service":
        raise jwt.InvalidTokenError("not a service token")
    return claims
