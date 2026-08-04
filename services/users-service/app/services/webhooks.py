"""
Aria webhook handling (users-service).

Ruta pública (via gateway con service-token); la autenticación del webhook
es X-API-Key o Authorization Bearer contra WEBHOOK_API_KEY (compare_digest).
"""
from datetime import datetime
from typing import Any, Dict, Optional
import hashlib
import hmac
import json
import logging
import secrets
import uuid

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import User
from app.schemas.webhook import AriaWebhookPayload
from shared.utils.exceptions import AppError

logger = logging.getLogger(__name__)

ARIA_TENANT_SLUG = "aria"
SUPPORTED_EVENTS = {
    "ACCESS_GRANTED",
    "ACCESS_STATUS_CHANGED",
    "PAYMENT_SUCCESS",
    "PAYMENT_FAILED",
    "SUBSCRIPTION_CANCELLED",
}


def verify_webhook_auth(*, x_api_key: Optional[str], authorization: Optional[str],
                        expected_key: str) -> None:
    """Verifica las credenciales del webhook (constante-time)."""
    if not expected_key:
        raise AppError(500, "Webhook key is not configured")
    bearer = (authorization or "").strip()
    expected_bearer = f"Bearer {expected_key}"
    key_ok = hmac.compare_digest(x_api_key or "", expected_key)
    bearer_ok = hmac.compare_digest(bearer, expected_bearer)
    if not key_ok and not bearer_ok:
        raise AppError(401, "Invalid webhook credentials")


def handle_aria_webhook(*, db: Session, settings, payload: AriaWebhookPayload,
                        x_api_key: Optional[str] = None,
                        authorization: Optional[str] = None) -> Dict[str, Any]:
    """Procesa un webhook de Aria: dedupe, creación de usuario y sync de estado."""
    verify_webhook_auth(x_api_key=x_api_key, authorization=authorization,
                        expected_key=settings.WEBHOOK_API_KEY)
    if payload.event_type not in SUPPORTED_EVENTS:
        raise AppError(400, "Unsupported event type")

    tenant_id = _resolve_aria_tenant_id(db)
    is_new_event = _store_event_if_new(db, tenant_id, payload)
    if not is_new_event:
        db.commit()
        return {"status": "ok", "processed": False, "reason": "duplicate_event"}

    user = _find_user_by_email(db, tenant_id, payload.user.email)
    user_id = user.id if user else None
    created = False
    if payload.event_type == "ACCESS_GRANTED" and user is None and _is_new_subscription_signup(payload):
        created_user = _create_user_for_aria(db, tenant_id, payload)
        user = created_user
        user_id = created_user.id
        created = True
    _upsert_subscription_state(db, tenant_id, payload, user_id)
    _sync_user_access_fields(db, user_id, payload)
    db.commit()

    if created and user_id:
        _send_welcome_email(user)

    return {
        "status": "ok",
        "processed": True,
        "user_created": created,
        "tenant_slug": ARIA_TENANT_SLUG,
    }


def _resolve_aria_tenant_id(session: Session) -> uuid.UUID:
    row = session.execute(
        text("SELECT id FROM public.tenants WHERE lower(slug)=:slug LIMIT 1"),
        {"slug": ARIA_TENANT_SLUG},
    ).first()
    if not row:
        raise AppError(500, "Aria tenant not found")
    return uuid.UUID(str(row[0]))


def _normalize_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value).strip().lower()


def _build_event_key(payload: AriaWebhookPayload) -> str:
    raw = f"{payload.access_id or ''}|{payload.event_type}|{payload.timestamp.isoformat()}|{payload.user.email.lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_new_subscription_signup(payload: AriaWebhookPayload) -> bool:
    product_type = _normalize_status(payload.product.type if payload.product else None)
    if product_type != "subscription":
        return False
    sub_id = payload.subscription_id or (payload.subscription.id if payload.subscription else None)
    if not sub_id:
        return False
    access_status = _normalize_status(payload.access.status if payload.access else None)
    subscription_status = _normalize_status(payload.subscription.status if payload.subscription else None)
    subscription_is_active = payload.subscription.is_active if payload.subscription else None
    if access_status not in {"active"}:
        return False
    if subscription_status in {"success", "active", "trial", "trialing"}:
        return True
    if subscription_is_active is True:
        return True

    if payload.event_type == "ACCESS_GRANTED" and access_status == "active":
        return True

    return False


def _split_name(full_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not full_name:
        return None, None
    parts = [p for p in full_name.strip().split(" ") if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _find_user_by_email(session: Session, tenant_id: uuid.UUID, email: str) -> Optional[User]:
    return session.exec(
        select(User).where(
            User.tenant_id == tenant_id,
            User.email == email.lower(),
        )
    ).first()


def _send_welcome_email(user: User) -> None:
    """Email delivery disabled: mailing-service was removed.
    Wire the new mailer here when it exists."""
    logger.warning(f"Welcome email for {user.email} NOT sent — no mailing service configured.")


def _create_user_for_aria(session: Session, tenant_id: uuid.UUID,
                          payload: AriaWebhookPayload) -> User:
    first_name, last_name = _split_name(payload.user.name)
    user = User(
        tenant_id=tenant_id,
        email=payload.user.email.lower(),
        password=secrets.token_urlsafe(48),
        first_name=first_name,
        last_name=last_name,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        role_id=3,
        first_login=True,
        date_joined=datetime.utcnow(),
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _store_event_if_new(session: Session, tenant_id: uuid.UUID,
                        payload: AriaWebhookPayload) -> bool:
    event_key = _build_event_key(payload)
    result = session.execute(
        text(
            """
            INSERT INTO public.aria_webhook_events
            (tenant_id, event_key, event_type, access_id, user_email, payload, created_at)
            VALUES
            (:tenant_id, :event_key, :event_type, :access_id, :user_email, CAST(:payload AS json), :created_at)
            ON CONFLICT (event_key) DO NOTHING
            RETURNING id
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "event_key": event_key,
            "event_type": payload.event_type,
            "access_id": payload.access_id,
            "user_email": payload.user.email.lower(),
            "payload": json.dumps(payload.model_dump(mode="json")),
            "created_at": datetime.utcnow(),
        },
    ).first()
    return bool(result)


def _upsert_subscription_state(session: Session, tenant_id: uuid.UUID,
                               payload: AriaWebhookPayload,
                               user_id: Optional[uuid.UUID]) -> None:
    session.execute(
        text(
            """
            INSERT INTO public.aria_subscription_states
            (
                tenant_id, user_id, user_email, access_id, subscription_id,
                access_status, subscription_status, subscription_is_active,
                next_payment, last_event_type, last_event_at, updated_at
            )
            VALUES
            (
                :tenant_id, :user_id, :user_email, :access_id, :subscription_id,
                :access_status, :subscription_status, :subscription_is_active,
                :next_payment, :last_event_type, :last_event_at, :updated_at
            )
            ON CONFLICT (tenant_id, user_email)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                access_id = COALESCE(EXCLUDED.access_id, public.aria_subscription_states.access_id),
                subscription_id = COALESCE(EXCLUDED.subscription_id, public.aria_subscription_states.subscription_id),
                access_status = COALESCE(EXCLUDED.access_status, public.aria_subscription_states.access_status),
                subscription_status = COALESCE(EXCLUDED.subscription_status, public.aria_subscription_states.subscription_status),
                subscription_is_active = COALESCE(EXCLUDED.subscription_is_active, public.aria_subscription_states.subscription_is_active),
                next_payment = COALESCE(EXCLUDED.next_payment, public.aria_subscription_states.next_payment),
                last_event_type = EXCLUDED.last_event_type,
                last_event_at = EXCLUDED.last_event_at,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id) if user_id else None,
            "user_email": payload.user.email.lower(),
            "access_id": payload.access_id or (payload.access.id if payload.access else None),
            "subscription_id": payload.subscription_id or (payload.subscription.id if payload.subscription else None),
            "access_status": _normalize_status(payload.access.status if payload.access else None),
            "subscription_status": _normalize_status(payload.subscription.status if payload.subscription else None),
            "subscription_is_active": payload.subscription.is_active if payload.subscription else None,
            "next_payment": payload.subscription.next_payment if payload.subscription else None,
            "last_event_type": payload.event_type,
            "last_event_at": payload.timestamp,
            "updated_at": datetime.utcnow(),
        },
    )


def _sync_user_access_fields(session: Session, user_id: Optional[uuid.UUID],
                             payload: AriaWebhookPayload) -> None:
    if not user_id:
        return
    if not payload.access_id and not (payload.subscription and payload.subscription.id):
        return

    is_active_part = ""
    if payload.event_type == "ACCESS_GRANTED":
        is_active_part = "is_active = true,"

    session.execute(
        text(
            f"""
            UPDATE public.users
            SET
                access_id = COALESCE(CAST(:access_id AS uuid), access_id),
                subscription_id = COALESCE(CAST(:subscription_id AS uuid), subscription_id),
                {is_active_part}
                modified_at = :modified_at
            WHERE id = CAST(:user_id AS uuid)
            """
        ),
        {
            "access_id": str(payload.access_id) if payload.access_id else None,
            "subscription_id": str(payload.subscription_id or (payload.subscription.id if payload.subscription else None)) if (payload.subscription_id or (payload.subscription and payload.subscription.id)) else None,
            "modified_at": datetime.utcnow(),
            "user_id": str(user_id),
        },
    )
