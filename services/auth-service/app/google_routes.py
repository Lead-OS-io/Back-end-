"""
Google OAuth endpoints (Gmail + Calendar) for auth-service.

Mounted under `/api/auth/google/*`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional
from uuid import UUID

# Relax oauthlib scope validation - Google may return different scopes than requested
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from jose import JWTError, jwt

from app.config import settings
from app.database import get_db
from app.models import GoogleOAuthToken, User
from app.google_oauth import build_oauth_flow, build_state, parse_state, fetch_account_email, get_client_web_config
from app.security import decode_token, Encryption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["Google OAuth"])


@router.get("/check-config")
def google_check_config():
    """
    Comprueba si GOOGLE_CREDENTIALS_JSON es válido. Sin auth. Para depuración.
    GET /api/auth/google/check-config
    """
    try:
        get_client_web_config()
        return {"ok": True, "message": "GOOGLE_CREDENTIALS_JSON is valid"}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {e}"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _tenant_from_header(x_tenant_id: str = Header(..., alias="X-Tenant-Id")) -> UUID:
    try:
        return UUID(str(x_tenant_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-Id (must be UUID)")






def _claims_from_authorization(authorization: str = Header(..., alias="Authorization")) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return decode_token(token)
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token (decode failed). Check SECRET_KEY in auth-service matches the key that signed the JWT in desk_app. Err: {e}",
        )


def _user_and_tenant(
    request: Request,
    tenant_id: Optional[UUID] = Depends(_tenant_from_header),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> tuple[User, UUID]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id required")

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Token missing sub")
        final_user_id = UUID(str(sub))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, final_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    return user, tenant_id


def _user_and_tenant_for_access_token(
    request: Request,
    tenant_id: Optional[UUID] = Depends(_tenant_from_header),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> tuple[User, UUID]:
    """Same checks as _user_and_tenant. Only for GET /access-token."""
    return _user_and_tenant(request, tenant_id, authorization, db)


@router.get("/status")
def google_status(
    ctx: tuple[User, UUID] = Depends(_user_and_tenant),
    db: Session = Depends(get_db),
):
    user, tenant_id = ctx
    tok = db.exec(
        select(GoogleOAuthToken).where(
            GoogleOAuthToken.tenant_id == tenant_id,
            GoogleOAuthToken.user_id == user.id,
        )
    ).first()
    return {"authenticated": bool(tok), "google_account_email": (tok.google_account_email if tok else "") or ""}


@router.get("/auth-url")
def google_auth_url(
    request: Request,
    redirect_uri: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-Id"),
    db: Session = Depends(get_db),
):
    """
    Returns Google OAuth authorization URL. Frontend should open it in a popup.
    Requires Authorization (Bearer JWT, verified here) + X-Tenant-Id.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id required")
    try:
        tenant_id = UUID(x_tenant_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-Id")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing sub")
    try:
        user_id = UUID(str(sub))
    except Exception:
        raise HTTPException(status_code=400, detail="Token sub must be UUID")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    if not redirect_uri:
        # build callback url from current request url (/auth-url -> /callback)
        base_path = str(request.url.path).rsplit("/", 1)[0]  # .../auth-url -> .../google
        redirect_uri = str(request.url.replace(path=f"{base_path}/callback", query=""))

    try:
        flow = build_oauth_flow(redirect_uri=redirect_uri)
    except json.JSONDecodeError as e:
        logger.error(f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GOOGLE_CREDENTIALS_JSON is not valid JSON. It must be the full JSON (e.g. {\"web\":{\"client_id\":\"...\",\"client_secret\":\"...\",\"auth_uri\":\"...\",\"token_uri\":\"...\"}}), not a file path.",
        ) from e
    except RuntimeError as e:
        msg = str(e).lower()
        if "google_credentials" in msg or "google_credentials_json" in msg or "missing" in msg:
            logger.error(f"Google OAuth not configured in auth-service: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google OAuth is not configured. Set GOOGLE_CREDENTIALS_JSON in auth-service (JSON with 'web' or 'installed' client).",
            ) from e
        raise
    except Exception as e:
        logger.exception("build_oauth_flow failed: %s", e)
        err = str(e).lower()
        hint = ""
        if "client_id" in err or "client_secret" in err or "redirect" in err:
            hint = " Ensure GOOGLE_CREDENTIALS_JSON has a 'web' or 'installed' object with client_id, client_secret, auth_uri, token_uri."
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Google OAuth configuration error: {e}.{hint}",
        ) from e

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
        logger.exception("build_state or flow.authorization_url failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth error generating URL. Check auth-service SECRET_KEY is set and matches desk_app. See auth-service logs.",
        ) from e


@router.get("/callback")
def google_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    redirect_uri: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Google OAuth callback (NO Authorization header).
    Uses signed `state` to map to (tenant_id, user_id).
    """

    def _html(ok: bool, msg: str, email: str = "") -> HTMLResponse:
        kind = "GOOGLE_AUTH_SUCCESS" if ok else "GOOGLE_AUTH_ERROR"
        safe_msg = (msg or "").replace("<", "&lt;").replace(">", "&gt;")
        safe_email = (email or "").replace("<", "&lt;").replace(">", "&gt;")
        
        if ok:
            return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Google Account Connected - ARIADESK</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f49;
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .container {{
            background: white;
            border-radius: 12px;
            border: 1px solid #e4e7ec;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        }}
        .success-icon {{
            width: 64px;
            height: 64px;
            background: #0f0f49;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 24px;
        }}
        .success-icon svg {{
            width: 32px;
            height: 32px;
            color: white;
        }}
        .title {{
            color: #1d2939;
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 12px;
        }}
        .message {{
            color: #667085;
            font-size: 16px;
            line-height: 1.5;
            margin-bottom: 24px;
        }}
        .account-info {{
            background: #f8fafc;
            border: 1px solid #e4e7ec;
            border-radius: 8px;
            padding: 16px;
            margin: 20px 0;
        }}
        .account-email {{
            color: #1d2939;
            font-size: 14px;
            font-weight: 500;
        }}
        .button {{
            background: #0f0f49;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .button:hover {{
            background: #1a1a5c;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
            </svg>
        </div>
        <h1 class="title">Google Account Connected</h1>
        <p class="message">Your Google account has been successfully connected to ARIADESK.</p>
        <div class="account-info">
            <div class="account-email">Connected: {safe_email or 'your account'}</div>
        </div>
        <button class="button" onclick="closeWindow()">Continue</button>
    </div>
    <script>
        function closeWindow() {{
            try {{
                if (window.opener) {{
                    window.opener.postMessage({{ type: '{kind}', email: '{safe_email}' }}, '*');
                }}
                window.close();
            }} catch (e) {{
                console.error('Error closing window:', e);
            }}
        }}
        
        if (window.opener) {{
            window.opener.postMessage({{ type: '{kind}', email: '{safe_email}' }}, '*');
        }}
        
        setTimeout(closeWindow, 3000);
    </script>
</body>
</html>
""")
        else:
            return HTMLResponse(content=f"""
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Google Auth Error</title></head>
  <body style="font-family: sans-serif; text-align: center; padding: 50px;">
    <h2 style="color: #dc2626;">Authentication Error</h2>
    <p>{safe_msg}</p>
    <script>
      try {{
        if (window.opener) {{
          window.opener.postMessage({{ type: '{kind}', message: '{safe_msg}' }}, '*');
        }}
      }} catch (e) {{}}
      setTimeout(function() {{ window.close(); }}, 5000);
    </script>
  </body>
</html>
""")

    if error:
        return _html(False, f"Google auth error: {error}")
    if not code or not state:
        return _html(False, "Missing code/state")

    try:
        tenant_id, user_id = parse_state(state)
    except Exception as e:
        return _html(False, f"Invalid state: {e}")

    try:
        if not redirect_uri:
            redirect_uri = str(request.url.replace(query=""))
            
        flow = build_oauth_flow(redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        if not creds:
            return _html(False, "Missing credentials")

        # refresh_token may be None on subsequent consents; keep existing if present
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
                return _html(False, "Missing refresh_token (try removing access and re-consenting)")
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

        logger.info(f"Google auth success for user {user_id}: {email}")
        return _html(True, "Google account connected", email or "")
    except Exception as e:
        logger.exception("OAuth callback failed")
        return _html(False, f"OAuth callback failed: {e}")


@router.post("/disconnect")
def google_disconnect(
    ctx: tuple[User, UUID] = Depends(_user_and_tenant),
    db: Session = Depends(get_db),
):
    user, tenant_id = ctx
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


@router.get("/access-token")
def google_access_token(
    ctx: tuple[User, UUID] = Depends(_user_and_tenant_for_access_token),
    db: Session = Depends(get_db),
):
    """
    Returns a short-lived Google access token (refreshes using stored refresh_token).
    Used by mailing-service (Gmail) and users-service (Calendar).
    """
    user, tenant_id = ctx
    tok = db.exec(
        select(GoogleOAuthToken).where(
            GoogleOAuthToken.tenant_id == tenant_id,
            GoogleOAuthToken.user_id == user.id,
        )
    ).first()
    if not tok:
        raise HTTPException(status_code=400, detail="Google not connected")

    try:
        refresh_token = Encryption.decrypt(tok.refresh_token) or ""
    except RuntimeError:
        refresh_token = ""
    if not refresh_token:
        # If decryption fails (returns None) or empty
        logger.error(f"Google token decryption failed for user {user.id}. Check FERNET_KEY configuration.")
        raise HTTPException(
            status_code=500, 
            detail="Stored refresh_token is not decryptable. Check FERNET_KEY matches the one used to encrypt."
        )

    web = get_client_web_config()
    client_id = web.get("client_id")
    client_secret = web.get("client_secret")
    token_uri = web.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Invalid GOOGLE_CREDENTIALS_JSON (missing client_id/client_secret)")

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
        raise HTTPException(status_code=502, detail=f"Failed to refresh Google token: {e}")

    return {
        "access_token": creds.token,
        "expires_at": getattr(creds, "expiry", None).isoformat() if getattr(creds, "expiry", None) else None,
        "google_account_email": tok.google_account_email or "",
    }

