"""Engine factory with SQLite WAL and schema creation."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from media_advisor.db.models import Base

_ENGINES: dict[str, Engine] = {}


def get_engine(database_url: str) -> Engine:
    if database_url in _ENGINES:
        return _ENGINES[database_url]

    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        m = re.match(r"sqlite:///(.*)", database_url)
        if m:
            raw_path = m.group(1)
            if raw_path and raw_path != ":memory:":
                Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, connect_args=connect_args, echo=False, future=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: object, _connection_record: object) -> None:
            cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(bind=engine)
    _ENGINES[database_url] = engine
    return engine
