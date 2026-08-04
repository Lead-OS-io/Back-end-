"""Google OAuth schemas."""
from pydantic import BaseModel


class GoogleStatusResponse(BaseModel):
    authenticated: bool
    google_account_email: str = ""


class GoogleAuthUrlResponse(BaseModel):
    url: str


class GoogleAccessTokenResponse(BaseModel):
    access_token: str
    expires_at: str | None = None
    google_account_email: str = ""
