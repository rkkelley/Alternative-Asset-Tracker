from __future__ import annotations

from sqlalchemy import inspect, text
from sqlmodel import create_engine

from database import (
    create_database_engine,
    initialize_database,
    migrate_schema,
    resolve_database_url,
)


def test_session_version_migration_upgrades_older_sqlite_schema_without_data_loss(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                'CREATE TABLE "user" ('
                "id INTEGER PRIMARY KEY, "
                "email VARCHAR NOT NULL, "
                "hashed_password VARCHAR NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                'INSERT INTO "user" (id, email, hashed_password) '
                "VALUES (1, 'existing@example.com', 'legacy-hash')"
            )
        )

    migrate_schema(engine)
    columns = {column["name"]: column for column in inspect(engine).get_columns("user")}
    assert columns["session_version"]["nullable"] is False
    assert str(columns["session_version"]["default"]) == "1"
    assert columns["is_demo"]["nullable"] is False
    assert str(columns["is_demo"]["default"]) == "0"

    with engine.connect() as connection:
        row = connection.execute(
            text('SELECT email, session_version, is_demo, created_at FROM "user" WHERE id = 1')
        ).one()
        assert row.email == "existing@example.com"
        assert row.session_version == 1
        assert row.is_demo == 0
        assert row.created_at is not None

    migrate_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM "user"')).scalar_one() == 1
        assert connection.execute(
            text('SELECT session_version FROM "user" WHERE id = 1')
        ).scalar_one() == 1
        assert connection.execute(
            text('SELECT is_demo FROM "user" WHERE id = 1')
        ).scalar_one() == 0


def test_postgresql_migration_statements_are_idempotent_and_narrow():
    statements: list[str] = []

    class RecordingConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            statements.append(str(statement))

    class RecordingEngine:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def begin(self):
            return RecordingConnection()

    migrate_schema(RecordingEngine())
    assert (
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS '
        "session_version INTEGER NOT NULL DEFAULT 1"
    ) in statements
    assert (
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS '
        "is_demo BOOLEAN NOT NULL DEFAULT FALSE"
    ) in statements
    assert (
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS '
        "created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
    ) in statements
    assert 'CREATE INDEX IF NOT EXISTS ix_user_is_demo ON "user" (is_demo)' in statements
    assert 'CREATE INDEX IF NOT EXISTS ix_user_created_at ON "user" (created_at)' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN session_version SET DEFAULT 1' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN session_version SET NOT NULL' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN is_demo SET DEFAULT FALSE' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN is_demo SET NOT NULL' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN created_at SET NOT NULL' in statements


def test_cleared_environment_uses_local_sqlite_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)

    fallback_url = resolve_database_url(tmp_path)
    assert fallback_url.startswith("sqlite:///")

    engine = create_database_engine(fallback_url)
    initialize_database(engine)
    assert "user" in inspect(engine).get_table_names()
    engine.dispose()
