from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest
from app.schemas.user import UserUpdateRequest
from app.schemas.avatar import AvatarResponse


def test_login_request_email_password():
    req = LoginRequest(email="a@a.com", password="superlongpw")
    assert req.email == "a@a.com"


def test_login_request_short_password_raises():
    with pytest.raises(ValidationError):
        LoginRequest(email="a@a.com", password="short")


def test_user_update_forbids_unknown_field():
    with pytest.raises(ValidationError):
        UserUpdateRequest.model_validate(
            {"email": "evil@a.com", "full_name": "X"}
        )


def test_user_update_accepts_partial():
    req = UserUpdateRequest(full_name="New")
    assert req.full_name == "New" and req.phone is None

    req = UserUpdateRequest(phone="+14155550100")
    assert req.full_name is None and req.phone == "+14155550100"

    req = UserUpdateRequest()
    assert req.full_name is None and req.phone is None


def test_avatar_response_parses_minimal():
    r = AvatarResponse(
        media_id=uuid4(),
        avatar_url="https://x/y.png",
        size_bytes=42,
        mimetype="image/png",
    )
    assert isinstance(r.media_id, UUID)
