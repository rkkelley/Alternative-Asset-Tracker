"""Database URL resolution, engine creation, and narrow schema migrations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel, create_engine


SESSION_VERSION_DEFAULT = 1


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql://", 1)
    return value


def resolve_database_url(
    base_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the configured database URL or the effective local SQLite URL."""

    if environ is None:
        environ = os.environ
    configured_url = environ.get("DATABASE_URL") or environ.get("POSTGRES_URL")
    if configured_url:
        return normalize_database_url(configured_url)
    return f"sqlite:///{base_dir / 'database.db'}"


def create_database_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return create_engine(database_url, echo=False)


def migrate_schema(engine: Engine) -> None:
    """Apply the idempotent schema changes introduced by the security upgrade.

    The current model audit found one new persisted field: User.session_version.
    PostgreSQL uses ALTER TABLE ... IF NOT EXISTS plus normalization of any
    pre-existing zero/null values. SQLite uses its compatible ALTER TABLE form.
    """

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(
                text(
                    'ALTER TABLE "user" '
                    "ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1"
                )
            )
            connection.execute(
                text(
                    'UPDATE "user" SET session_version = 1 '
                    "WHERE session_version IS NULL OR session_version = 0"
                )
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN session_version SET DEFAULT 1')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN session_version SET NOT NULL')
            )
        return

    if engine.dialect.name == "sqlite":
        table_names = inspect(engine).get_table_names()
        if "user" not in table_names:
            return

        columns = {column["name"] for column in inspect(engine).get_columns("user")}
        if "session_version" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        'ALTER TABLE "user" '
                        "ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"
                    )
                )

        # A prior local development build used zero as the Python default.
        # Normalize those rows without deleting or recreating the table.
        with engine.begin() as connection:
            connection.execute(
                text(
                    'UPDATE "user" SET session_version = 1 '
                    "WHERE session_version IS NULL OR session_version = 0"
                )
            )


def initialize_database(engine: Engine) -> None:
    """Create missing tables, then apply migrations to existing tables."""

    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)
