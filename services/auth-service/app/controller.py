from typing import Optional

from fastapi import Response, UploadFile

from app.config import Settings
from app.models.entities import User
from app.schemas.onboarding import (
    OnboardingAcceptedResponse,
    OnboardingRequest,
)
from app.schemas.user import UserResponse
from app.services.onboarding import publish_pending, start_onboarding
from shared.events.bus import EventBus


def onboarding(
    *, data: OnboardingRequest, db, settings, event_bus: EventBus
) -> OnboardingAcceptedResponse:
    user = start_onboarding(db=db, data=data)
    publish_pending(event_bus=event_bus, user=user, data=data)
    return OnboardingAcceptedResponse(user_id=user.id, status=user.status)


def _client_ip(request) -> Optional[str]:
    return request.client.host if request.client else None


def _user_agent(request) -> Optional[str]:
    return request.headers.get("user-agent")


def _set_refresh_cookie(response: Response, raw: str, settings: Settings) -> None:
    response.set_cookie(
        key="refresh_token",
        value=raw,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=settings.COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN or None,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key="refresh_token",
        path=settings.COOKIE_PATH,
        domain=settings.COOKIE_DOMAIN or None,
    )


def _build_user_response(
    *, user: User, db, settings: Settings
) -> dict:
    from app.services.avatars_read import get_avatar_summary

    summary = get_avatar_summary(settings=settings, user_id=user.id)
    return UserResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        status=user.status,
        has_avatar=summary.has_avatar,
        avatar_url=summary.avatar_url,
        created_at=user.created_at.isoformat(),
        modified_at=user.modified_at.isoformat(),
    ).model_dump()


def login(*, data, settings: Settings, db, event_bus: EventBus,
          response: Response, request) -> dict:
    from app.schemas.auth import LoginRequest, LoginResponse
    from app.services.login import authenticate_and_open_session

    outcome = authenticate_and_open_session(
        db=db, settings=settings,
        email=data.email, password=data.password,
        ip=_client_ip(request), user_agent=_user_agent(request),
    )
    _set_refresh_cookie(response, outcome.refresh_token, settings)
    return LoginResponse(
        access_token=outcome.access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_build_user_response(
            user=outcome.user, db=db, settings=settings,
        ),
    ).model_dump()


def logout(*, settings: Settings, db, response: Response,
           cookie_token: Optional[str]) -> None:
    from app.services.logout import revoke_session_for_token

    revoke_session_for_token(db=db, raw_refresh_token=cookie_token)
    _clear_refresh_cookie(response, settings)


def refresh(*, settings: Settings, db, response: Response,
            cookie_token: Optional[str], request) -> dict:
    from app.schemas.auth import LoginResponse
    from app.services.refresh import rotate_refresh
    from shared.utils.exceptions import AppError

    if not cookie_token:
        raise AppError(401, "invalid refresh token")
    outcome = rotate_refresh(
        db=db, settings=settings,
        raw_refresh_token=cookie_token,
        ip=_client_ip(request), user_agent=_user_agent(request),
    )
    _set_refresh_cookie(response, outcome.new_refresh_token, settings)
    return LoginResponse(
        access_token=outcome.access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_build_user_response(
            user=outcome.user, db=db, settings=settings,
        ),
    ).model_dump()


def validate(*, settings: Settings, authorization: Optional[str]) -> dict:
    import uuid

    from app.schemas.auth import ValidateResponse
    from app.services.validate import validate_access_token
    from shared.utils.exceptions import AppError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    return ValidateResponse(
        valid=True, expires_at=result.expires_at, claims=result.claims,
    ).model_dump()


def get_me(*, settings: Settings, db, authorization: Optional[str]) -> dict:
    import uuid

    from app.services.users import get_user_by_id
    from app.services.validate import validate_access_token
    from shared.utils.exceptions import AppError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    user_id = uuid.UUID(result.claims["sub"])
    user = get_user_by_id(db=db, user_id=user_id)
    return _build_user_response(user=user, db=db, settings=settings)


def patch_me(*, data, settings: Settings, db,
             authorization: Optional[str], event_bus: EventBus) -> dict:
    import uuid

    from app.services.users import get_user_by_id, update_user
    from app.services.validate import validate_access_token
    from shared.events.envelope import EventEnvelope
    from shared.utils.exceptions import AppError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    user_id = uuid.UUID(result.claims["sub"])
    user = get_user_by_id(db=db, user_id=user_id)
    changed = update_user(
        db=db, user_id=user_id,
        full_name=data.full_name, phone=data.phone,
    )
    event_bus.publish(
        "auth",
        EventEnvelope(
            type="user.updated",
            aggregate_id=str(changed.id),
            tenant_id=str(changed.tenant_id) if changed.tenant_id else None,
            payload={
                "user_id": str(changed.id),
                "changes": {
                    k: v for k, v in [
                        ("full_name", data.full_name),
                        ("phone", data.phone),
                    ] if v is not None
                },
            },
        ),
    )
    return _build_user_response(user=changed, db=db, settings=settings)


def get_my_avatar_response(*, settings: Settings, db, authorization: Optional[str],
                            response: Response) -> Response:
    import uuid

    from app.services.avatars import get_avatar_for_user
    from app.services.users import get_user_by_id
    from app.services.validate import validate_access_token
    from shared.utils.exceptions import AppError, NotFoundError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    user_id = uuid.UUID(result.claims["sub"])
    user = get_user_by_id(db=db, user_id=user_id)
    outcome = get_avatar_for_user(db=db, settings=settings, user=user)
    if outcome is None:
        raise NotFoundError("no avatar")
    _, url = outcome
    response.status_code = 302
    response.headers["location"] = url
    return response


def post_my_avatar(*, settings: Settings, db, authorization: Optional[str],
                   event_bus: EventBus, file: UploadFile,
                   request) -> dict:
    import uuid

    from app.schemas.avatar import AvatarResponse
    from app.services.avatars import upload_avatar_for_user
    from app.services.users import get_user_by_id
    from app.services.validate import validate_access_token
    from shared.events.envelope import EventEnvelope
    from shared.utils.exceptions import AppError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    user_id = uuid.UUID(result.claims["sub"])
    user = get_user_by_id(db=db, user_id=user_id)
    content = file.file.read()
    media, url = upload_avatar_for_user(
        db=db, settings=settings, user=user,
        content=content,
        filename=file.filename or "avatar.bin",
        content_type=file.content_type or "application/octet-stream",
    )
    event_bus.publish(
        "auth",
        EventEnvelope(
            type="user.avatar.changed",
            aggregate_id=str(user.id),
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            payload={
                "user_id": str(user.id),
                "media_id": str(media.media_id),
                "mimetype": media.mimetype,
                "size_bytes": media.size_bytes,
            },
        ),
    )
    return AvatarResponse(
        media_id=media.media_id,
        avatar_url=url,
        size_bytes=media.size_bytes,
        mimetype=media.mimetype,
    ).model_dump()


def delete_my_avatar(*, settings: Settings, db,
                     authorization: Optional[str], event_bus: EventBus) -> None:
    import uuid

    from app.services.avatars import delete_avatar_for_user
    from app.services.users import get_user_by_id
    from app.services.validate import validate_access_token
    from shared.events.envelope import EventEnvelope
    from shared.utils.exceptions import AppError, NotFoundError

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "invalid token")
    token = authorization.split(None, 1)[1].strip()
    result = validate_access_token(token=token, secret=settings.SECRET_KEY)
    user_id = uuid.UUID(result.claims["sub"])
    user = get_user_by_id(db=db, user_id=user_id)
    if not delete_avatar_for_user(db=db, settings=settings, user=user):
        raise NotFoundError("no avatar")
    event_bus.publish(
        "auth",
        EventEnvelope(
            type="user.avatar.removed",
            aggregate_id=str(user.id),
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            payload={"user_id": str(user.id)},
        ),
    )
