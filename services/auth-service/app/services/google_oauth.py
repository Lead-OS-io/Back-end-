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
from sqlmodel import Session, select

from app.config import settings
from app.models import GoogleOAuthToken
from app.services.security import Encryption
from shared.utils.exceptions import AppError

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


def check_config() -> dict:
    """Comprueba si GOOGLE_CREDENTIALS_JSON es válido (sin auth, para depuración)."""
    try:
        get_client_web_config()
        return {"ok": True, "message": "GOOGLE_CREDENTIALS_JSON is valid"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_status(*, db: Session, user, tenant_id: UUID) -> dict:
    tok = db.exec(
        select(GoogleOAuthToken).where(
            GoogleOAuthToken.tenant_id == tenant_id,
            GoogleOAuthToken.user_id == user.id,
        )
    ).first()
    return {"authenticated": bool(tok),
            "google_account_email": (tok.google_account_email if tok else "") or ""}


def get_auth_url(*, request, db: Session, redirect_uri: Optional[str],
                 user, tenant_id: UUID) -> dict:
    """Returns Google OAuth authorization URL. Frontend should open it in a popup."""
    if not redirect_uri:
        # build callback url from current request url (/auth-url -> /callback)
        base_path = str(request.url.path).rsplit("/", 1)[0]
        redirect_uri = str(request.url.replace(path=f"{base_path}/callback", query=""))

    try:
        flow = build_oauth_flow(redirect_uri=redirect_uri)
    except json.JSONDecodeError as e:
        raise AppError(500, "GOOGLE_CREDENTIALS_JSON is not valid JSON.") from e
    except RuntimeError as e:
        msg = str(e).lower()
        if "google_credentials" in msg or "missing" in msg:
            raise AppError(500, "Google OAuth is not configured. Set GOOGLE_CREDENTIALS_JSON.") from e
        raise

    try:
        state = build_state(tenant_id=tenant_id, user_id=user.id)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        return {"url": auth_url}
    except Exception as e:
        raise AppError(500, "Google OAuth error generating URL.") from e


def handle_callback(*, request, db: Session, code: Optional[str],
                    state: Optional[str], error: Optional[str],
                    redirect_uri: Optional[str]) -> dict:
    """Google OAuth callback (NO Authorization header). Returns dict for the controller
    to render as HTML (kind: success|error)."""
    if error:
        return {"kind": "error", "html": _html_error(f"Google auth error: {error}")}
    if not code or not state:
        return {"kind": "error", "html": _html_error("Missing code/state")}

    try:
        tenant_id, user_id = parse_state(state)
    except Exception as e:
        return {"kind": "error", "html": _html_error(f"Invalid state: {e}")}

    try:
        if not redirect_uri:
            redirect_uri = str(request.url.replace(query=""))
        flow = build_oauth_flow(redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        if not creds:
            return {"kind": "error", "html": _html_error("Missing credentials")}

        refresh_token = getattr(creds, "refresh_token", None)
        email = fetch_account_email(creds)

        existing = db.exec(
            select(GoogleOAuthToken).where(
                GoogleOAuthToken.tenant_id == tenant_id,
                GoogleOAuthToken.user_id == user_id,
            )
        ).first()

        now = datetime.utcnow()
        if existing:
            if refresh_token:
                existing.refresh_token = Encryption.encrypt(refresh_token)
            existing.google_account_email = email
            existing.updated_at = now
            db.add(existing)
            db.commit()
        else:
            if not refresh_token:
                return {"kind": "error",
                        "html": _html_error("Missing refresh_token (try removing access and re-consenting)")}
            row = GoogleOAuthToken(
                tenant_id=tenant_id,
                user_id=user_id,
                refresh_token=Encryption.encrypt(refresh_token),
                google_account_email=email,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()

        return {"kind": "success", "email": email or "", "html": _html_success(email or "")}
    except Exception as e:
        return {"kind": "error", "html": _html_error(f"OAuth callback failed: {e}")}


def disconnect(*, db: Session, user, tenant_id: UUID) -> dict:
    tok = db.exec(
        select(GoogleOAuthToken).where(
            GoogleOAuthToken.tenant_id == tenant_id,
            GoogleOAuthToken.user_id == user.id,
        )
    ).first()
    if tok:
        db.delete(tok)
        db.commit()
    return {"success": True}


def get_access_token(*, db: Session, user, tenant_id: UUID) -> dict:
    """Returns a short-lived Google access token (refreshes using stored refresh_token)."""
    tok = db.exec(
        select(GoogleOAuthToken).where(
            GoogleOAuthToken.tenant_id == tenant_id,
            GoogleOAuthToken.user_id == user.id,
        )
    ).first()
    if not tok:
        raise AppError(400, "Google not connected")

    try:
        refresh_token = Encryption.decrypt(tok.refresh_token) or ""
    except RuntimeError:
        refresh_token = ""
    if not refresh_token:
        raise AppError(500, "Stored refresh_token is not decryptable. Check FERNET_KEY.")

    web = get_client_web_config()
    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    token_uri = web.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not client_id or not client_secret:
        raise AppError(500, "Invalid GOOGLE_CREDENTIALS_JSON (missing client_id/client_secret)")

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=None,
    )
    try:
        creds.refresh(GoogleRequest())
    except Exception as e:
        raise AppError(502, f"Failed to refresh Google token: {e}")

    return {
        "access_token": creds.token,
        "expires_at": getattr(creds, "expiry", None).isoformat() if getattr(creds, "expiry", None) else None,
        "google_account_email": tok.google_account_email or "",
    }


def _html_success(email: str) -> str:
    safe_email = (email or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html>
<head><title>Google Account Connected - ARIADESK</title></head>
<body>
<div class="container">
    <h1 class="title">Google Account Connected</h1>
    <p class="message">Your Google account has been successfully connected to ARIADESK.</p>
    <div class="account-info"><div class="account-email">Connected: {safe_email or 'your account'}</div></div>
    <button class="button" onclick="closeWindow()">Continue</button>
</div>
<script>
    function closeWindow() {{
        try {{
            if (window.opener) window.opener.postMessage({{ type: 'GOOGLE_AUTH_SUCCESS', email: '{safe_email}' }}, '*');
            window.close();
        }} catch (e) {{ console.error('Error closing window:', e); }}
    }}
    if (window.opener) window.opener.postMessage({{ type: 'GOOGLE_AUTH_SUCCESS', email: '{safe_email}' }}, '*');
    setTimeout(closeWindow, 3000);
</script>
</body>
</html>"""


def _html_error(msg: str) -> str:
    safe_msg = (msg or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Google Auth Error</title></head>
  <body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h2 style="color: #dc2626;">Authentication Error</h2>
    <p>{safe_msg}</p>
    <script>
      try {{
        if (window.opener) window.opener.postMessage({{ type: 'GOOGLE_AUTH_ERROR', message: '{safe_msg}' }}, '*');
      }} catch (e) {{}}
      setTimeout(function() {{ window.close(); }}, 5000);
    </script>
  </body>
</html>"""
