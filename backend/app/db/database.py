"""
Database configuration.

Provides the SQLAlchemy 2.0 engine, session factory, declarative base and the
FastAPI ``get_db`` dependency. The connection string is read from the
``DATABASE_URL`` environment variable, for example::

    DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ansme

This module defines no models, repositories or migrations.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from dotenv import load_dotenv

load_dotenv()

__all__ = ["Base", "SessionLocal", "engine", "get_db"]

DATABASE_URL_ENV_VAR = "DATABASE_URL"


class Base(DeclarativeBase):
    """Declarative base class that all ORM models inherit from."""


def _get_database_url() -> str:
    """
    Read and normalize the database URL from the environment.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is missing or empty.
    """
    url = os.getenv(DATABASE_URL_ENV_VAR, "").strip()
    if not url:
        raise RuntimeError(
            f"The {DATABASE_URL_ENV_VAR} environment variable is not set."
        )

    # Some providers emit the legacy "postgres://" scheme, which SQLAlchemy
    # 2.0 no longer accepts.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _create_engine(database_url: str) -> Engine:
    """Create the SQLAlchemy engine with settings suited to the backend."""
    connect_args: dict[str, Any] = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        # FastAPI may use a session from a different thread than the one
        # that created the connection.
        connect_args["check_same_thread"] = False

    return create_engine(
        database_url,
        pool_pre_ping=True,  # drop stale connections instead of failing requests
        connect_args=connect_args,
    )


DATABASE_URL: str = _get_database_url()

engine: Engine = _create_engine(DATABASE_URL)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session per request.

    The session is always closed when the request finishes, even if the
    request handler raises. Usage::

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)): ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

   