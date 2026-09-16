from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        return
    raw_path = database_url.removeprefix(prefix)
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str) -> Engine:
    ensure_sqlite_parent(database_url)
    connect_args = (
        {"check_same_thread": False, "timeout": 5.0} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
