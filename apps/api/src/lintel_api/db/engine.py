"""Engine and sessions. Every unit of work runs inside one transaction with app.user_id set."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
    role = settings.db_app_role

    if role:

        @event.listens_for(engine, "connect")
        def _set_role(dbapi_conn, _record):  # pragma: no cover - exercised in every test
            with dbapi_conn.cursor() as cur:
                cur.execute(f'SET ROLE "{role}"')
            dbapi_conn.commit()

    return engine


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=True)


def set_user(session: Session, user_id: UUID | str | None) -> None:
    session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id) if user_id else ""}
    )


def set_actor(session: Session, actor: str, reason: str) -> None:
    """Name who changes lifecycle state and why. The database refuses transitions without it."""

    session.execute(
        text("SELECT set_config('lintel.actor', :a, true), set_config('lintel.reason', :r, true)"),
        {"a": actor, "r": reason},
    )


@contextmanager
def user_session(user_id: UUID | str | None) -> Iterator[Session]:
    """One transaction under row-level security for one user (or for nobody)."""

    session = _factory()()
    try:
        session.begin()
        set_user(session, user_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def anon_session() -> Iterator[Session]:
    with user_session(None) as s:
        yield s
