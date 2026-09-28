"""Database session configuration — auto-detects PostgreSQL or falls back to SQLite."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from core.config import load_env, logger
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker


def _sqlite_unaccent(value: str | None) -> str | None:
    """SQL function: strip accents (SQLite has no native unaccent)."""
    if value is None:
        return None
    return unicodedata.normalize("NFD", value).encode("ascii", "ignore").decode("ascii")


env = load_env()
DATABASE_URL = env.get("DATABASE_URL", "")

_is_sqlite = False
engine = None

if DATABASE_URL and "sqlite" not in DATABASE_URL:
    # Try PostgreSQL
    try:
        test_engine = create_engine(
            DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with test_engine.connect() as conn:
            conn.close()
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        logger.info("Conectado ao PostgreSQL")
    except Exception:
        logger.warning("PostgreSQL indisponível, usando SQLite local")
        DATABASE_URL = ""

if engine is None:
    _is_sqlite = True
    _db_path = Path(__file__).resolve().parent.parent / "data" / "regulatory.db"
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{_db_path}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    # Enable WAL mode for better concurrency
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
        dbapi_conn.create_function("unaccent", 1, _sqlite_unaccent)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
