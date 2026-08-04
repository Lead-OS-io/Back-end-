"""
Handlers de eventos (consumer). Se registran en HANDLERS por tipo de evento.
La factory build_handlers(session_factory) envuelve los handlers con una sesión
propia por evento (EventHandler = Callable[[EventEnvelope], None]).
"""
from typing import Callable

from sqlmodel import Session, select

from app.models import User
from shared.events.consumer import EventHandler
from shared.events.envelope import EventEnvelope

logger = None  # logging configurado por setup_logging


def handle_user_registered(event: EventEnvelope, *, db) -> None:
    """Idempotente: crea el perfil si no existe para aggregate_id (user_id).

    El evento lo publica auth-service post-registro; aquí materializamos el
    perfil en users_db (tenants locales no requieren FK cross-db)."""
    import logging
    global logger
    logger = logger or logging.getLogger(__name__)
    try:
        user_id = int(event.aggregate_id)
    except ValueError:
        # Los usuarios de auth usan UUID; aggregate_id es str(user.id).
        user_id = event.aggregate_id

    existing = db.exec(select(User).where(User.id == user_id)).first()
    if existing:
        logger.info("profile already exists for user %s, skipping", event.aggregate_id)
        return

    tenant_id = event.tenant_id
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=event.payload.get("email", ""),
        first_name=(event.payload.get("full_name") or "").split(" ", 1)[0] or None,
        last_name=(event.payload.get("full_name") or "").split(" ", 1)[1].strip() if " " in (event.payload.get("full_name") or "") else None,
        password="",  # auth-service es la fuente de verdad del password
        is_active=True,
        is_staff=False,
        is_superuser=False,
        first_login=True,
    )
    db.add(user)
    db.commit()


def build_handlers(session_factory) -> dict[str, EventHandler]:
    """Crea sesión por evento (los handlers no pueden compartir sesión)."""

    def _session_handler(event: EventEnvelope) -> None:
        session: Session = session_factory()
        try:
            handle_user_registered(event, db=session)
        finally:
            session.close()

    return {
        "user.registered": _session_handler,
    }


HANDLERS: dict[str, EventHandler] = {}
