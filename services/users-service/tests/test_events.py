"""Contrato del consumer de events de users-service (Task 26)."""
from shared.events.envelope import EventEnvelope


class _FakeSession:
    """Simula una sesión SQLModel: exec(...).first() devuelve lo que tenga self.existing."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.commits = 0

    def exec(self, *args, **kwargs):
        return type("Result", (), {"first": lambda _self: self.existing})()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def test_handle_user_registered_creates_profile():
    from app.events import handle_user_registered

    db = _FakeSession(existing=None)
    event = EventEnvelope(type="user.registered", aggregate_id="77",
                          tenant_id=1, payload={"email": "n@x.com", "full_name": "N"})
    handle_user_registered(event, db=db)
    assert len(db.added) == 1 and db.commits == 1


def test_handle_user_registered_is_idempotent():
    from app.events import handle_user_registered

    db = _FakeSession(existing=object())  # ya existe perfil para aggregate_id
    event = EventEnvelope(type="user.registered", aggregate_id="77",
                          tenant_id=1, payload={"email": "n@x.com", "full_name": "N"})
    handle_user_registered(event, db=db)  # no lanza, no duplica
    assert db.added == [] and db.commits == 0
