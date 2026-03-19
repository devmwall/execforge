from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from orchestrator.storage.models import Base


def make_engine(db_file: str):
    return create_engine(f"sqlite+pysqlite:///{db_file}", future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine):
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
