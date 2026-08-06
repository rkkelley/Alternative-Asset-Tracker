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
    """Apply the idempotent schema changes introduced by the security/demo upgrades.

    The model audit found these new persisted User fields since the original
    schema: session_version, is_demo, and created_at. PostgreSQL uses ALTER
    TABLE ... IF NOT EXISTS plus normalization of any pre-existing null values.
    SQLite uses its compatible ALTER TABLE form. No existing table or row is
    recreated or removed by this helper.
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
                    'ALTER TABLE "user" '
                    "ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
            connection.execute(
                text(
                    'ALTER TABLE "user" '
                    "ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE "
                    "NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            )
            connection.execute(
                text('CREATE INDEX IF NOT EXISTS ix_user_is_demo ON "user" (is_demo)')
            )
            connection.execute(
                text('CREATE INDEX IF NOT EXISTS ix_user_created_at ON "user" (created_at)')
            )
            connection.execute(
                text(
                    'UPDATE "user" SET session_version = 1 '
                    "WHERE session_version IS NULL OR session_version = 0"
                )
            )
            connection.execute(
                text('UPDATE "user" SET is_demo = FALSE WHERE is_demo IS NULL')
            )
            connection.execute(
                text('UPDATE "user" SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN session_version SET DEFAULT 1')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN session_version SET NOT NULL')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN is_demo SET DEFAULT FALSE')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN is_demo SET NOT NULL')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP')
            )
            connection.execute(
                text('ALTER TABLE "user" ALTER COLUMN created_at SET NOT NULL')
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
        if "is_demo" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        'ALTER TABLE "user" '
                        "ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
        if "created_at" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        'ALTER TABLE "user" '
                        "ADD COLUMN created_at DATETIME"
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                text('CREATE INDEX IF NOT EXISTS ix_user_is_demo ON "user" (is_demo)')
            )
            connection.execute(
                text('CREATE INDEX IF NOT EXISTS ix_user_created_at ON "user" (created_at)')
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
            connection.execute(
                text('UPDATE "user" SET is_demo = 0 WHERE is_demo IS NULL')
            )
            connection.execute(
                text('UPDATE "user" SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')
            )


def initialize_database(engine: Engine) -> None:
    """Create missing tables, then apply migrations to existing tables."""

    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)
