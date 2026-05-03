"""Session scope helper."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from media_advisor.config import Settings
from media_advisor.db.engine import get_engine

_session_factories: dict[str, sessionmaker[Session]] = {}


def _factory_for_url(database_url: str) -> sessionmaker[Session]:
    if database_url not in _session_factories:
        engine = get_engine(database_url)
        _session_factories[database_url] = sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factories[database_url]


@contextmanager
def session_scope(root: Path, *, read_only: bool = False) -> Iterator[Session]:
    settings = Settings()
    url = settings.get_database_url(data_root=root)
    factory = _factory_for_url(url)
    session = factory()
    try:
        yield session
        if read_only:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
