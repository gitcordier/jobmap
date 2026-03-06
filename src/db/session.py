# -*- coding: utf-8 -*-
"""
src/db/session.py
=================
SQLAlchemy engine and session-factory configuration.

A single module-level ``Engine`` and ``SessionFactory`` are constructed
once at import time and reused throughout the application lifetime.

Usage
-----
    from src.db.session import SessionFactory

    with SessionFactory() as session:
        session.add(some_model)
        session.commit()
"""

from __future__ import annotations

import logging

import sqlalchemy
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from src.db.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

#: Shared SQLAlchemy engine.  ``echo=False`` keeps logs clean in production.
engine: Engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},  # SQLite-specific — harmless for others.
)


# ---------------------------------------------------------------------------
# SQLite WAL mode pragma (SQLite only, no-op elsewhere)
# ---------------------------------------------------------------------------

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[type-arg]
    """
    Enable WAL journal mode for SQLite connections.

    WAL mode allows concurrent readers while a writer is active, which is
    important when the HTTP server reads the DB while the ingest pipeline
    writes to it.
    """
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

#: Callable session factory.  Each call returns a new :class:`Session`.
SessionFactory: sessionmaker[Session] = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all tables defined in :mod:`src.db.models` if they do not exist,
    and apply any additive schema migrations required for existing databases.

    Safe to call multiple times (idempotent).

    Migrations applied
    ------------------
    - ``jobs.search_run`` (integer, default 0) — added in the run-scoping
      refactor.  Existing rows receive ``0`` so they are never surfaced by
      the current-run filter (which starts at ``1``).
    """
    logger.info("Initialising database schema at %s", settings.DATABASE_URL)
    Base.metadata.create_all(engine, checkfirst=True)

    # Additive migration: add search_run column if the table pre-dates it.
    with engine.connect() as conn:
        existing_cols = [
            row[1]
            for row in conn.execute(
                sqlalchemy.text("PRAGMA table_info(jobs)")
            )
        ]
        if "search_run" not in existing_cols:
            logger.warning(
                "Column 'jobs.search_run' missing — applying migration."
            )
            conn.execute(
                sqlalchemy.text(
                    "ALTER TABLE jobs ADD COLUMN search_run INTEGER NOT NULL DEFAULT 0"
                )
            )
            conn.commit()
            logger.info("Migration applied: jobs.search_run added.")

    logger.info("Database schema ready.")
