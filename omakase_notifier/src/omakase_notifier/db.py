from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Config, project_root
from .models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(config: Config) -> Engine:
    global _engine, _SessionLocal
    url = config.app.database_url
    if url.startswith("sqlite:///./"):
        rel = url.replace("sqlite:///./", "", 1)
        abs_path = project_root() / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{abs_path}"
    _engine = create_engine(url, echo=False, future=True)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        raise RuntimeError("init_engine() must be called first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
