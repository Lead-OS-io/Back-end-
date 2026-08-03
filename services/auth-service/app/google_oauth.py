"""
Google OAuth helpers (shared by Gmail + Calendar).

OAuth flow is owned by auth-service. Other services should NOT store refresh tokens.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from jose import jwt

from app.config import settings


SCOPES = [
    # Gmail
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    # Calendar
    "https://www.googleapis.com/auth/calendar",
]


def _client_config() -> Dict[str, Any]:
    raw = getattr(settings, "GOOGLE_CREDENTIALS_JSON", None)
    if not raw or not str(raw).strip():
        raise RuntimeError("Missing GOOGLE_CREDENTIALS_JSON")
    cfg = json.loads(raw)
    if "installed" in cfg or "web" in cfg:
        inner = cfg.get("web") or cfg.get("installed") or {}
        if not inner.get("client_id") or not inner.get("client_secret"):
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_JSON must have 'web' or 'installed' with client_id and client_secret"
            )
        return cfg
    # allow inner web config when keys are at top level
    if "client_id" in cfg and "client_secret" in cfg and "auth_uri" in cfg:
        return {"web": cfg}
    raise RuntimeError(
        "GOOGLE_CREDENTIALS_JSON must have 'web' or 'installed' with client_id, client_secret, auth_uri, token_uri"
    )


def get_client_web_config() -> Dict[str, Any]:
    cfg = _client_config()
    return cfg.get("web") or cfg.get("installed") or cfg


def build_oauth_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)


def build_state(tenant_id: UUID, user_id: UUID) -> str:
    now = datetime.utcnow()
    payload = {
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "typ": "google_oauth_state",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def parse_state(state: str) -> Tuple[UUID, UUID]:
    data = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if data.get("typ") != "google_oauth_state":
        raise ValueError("Invalid state typ")
    return UUID(str(data["tenant_id"])), UUID(str(data["user_id"]))


def fetch_account_email(credentials) -> Optional[str]:
    """
    Best-effort to resolve the Google account email.
    """
    try:
        from googleapiclient.discovery import build

        svc = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
        info = svc.userinfo().get().execute()
        email = info.get("email")
        return str(email) if email else None
    except Exception:
        return None

