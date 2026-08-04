import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import Field, Session, SQLModel

from shared.db.engine import create_service_engine, get_db, get_session_factory
from shared.db.readonly import create_readonly_engine, readonly_dependency


class Widget(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


def _make_app(url: str) -> FastAPI:
    app = FastAPI()
    engine = create_service_engine(url)
    SQLModel.metadata.create_all(engine)
    app.state.session_factory = get_session_factory(engine)
    app.state.readonly_factories = {"widgets": get_session_factory(create_readonly_engine(url))}

    @app.post("/widgets")
    def create(name: str, db: Session = Depends(get_db)):
        w = Widget(name=name)
        db.add(w)
        db.commit()
        db.refresh(w)
        return {"id": w.id}

    @app.get("/widgets")
    def list_(db: Session = Depends(readonly_dependency("widgets"))):
        return {"count": len(db.query(Widget).all())}

    return app


def test_engine_session_and_dependencies_roundtrip(tmp_path):
    app = _make_app(f"sqlite:///{tmp_path / 'test.db'}")
    client = TestClient(app)
    assert client.post("/widgets", params={"name": "a"}).json() == {"id": 1}
    assert client.get("/widgets").json() == {"count": 1}


def test_get_db_requires_factory_on_app_state():
    app = FastAPI()

    @app.get("/x")
    def x(db: Session = Depends(get_db)):
        return {}

    with pytest.raises(AttributeError):
        list(TestClient(app, raise_server_exceptions=True).get("/x").iter_bytes())


def test_create_service_engine_accepts_sqlite():
    engine = create_service_engine("sqlite://", pool_size=5, max_overflow=10)
    assert engine is not None  # no lanza TypeError por pool args
