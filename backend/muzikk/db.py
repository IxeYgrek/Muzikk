"""Database engine, session factory and schema bootstrap."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_env_config
from .models import Base

logger = logging.getLogger(__name__)

_env = get_env_config()

engine: Engine = create_engine(
    _env.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    # WAL lets the worker write while the API reads.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background work."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _alembic_config():
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", _env.database_url)
    return config


def init_db() -> None:
    """Create the schema on a fresh install, migrate it otherwise."""
    from alembic import command

    _env.database_path.parent.mkdir(parents=True, exist_ok=True)
    config = _alembic_config()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if not tables:
        logger.info("Fresh database detected, creating schema")
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return

    if "alembic_version" not in tables:
        # Database created by an older build without migration bookkeeping.
        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        return

    logger.info("Applying pending migrations")
    command.upgrade(config, "head")
