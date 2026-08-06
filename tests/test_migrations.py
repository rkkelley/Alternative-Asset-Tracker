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

    with engine.connect() as connection:
        row = connection.execute(
            text('SELECT email, session_version FROM "user" WHERE id = 1')
        ).one()
        assert row.email == "existing@example.com"
        assert row.session_version == 1

    migrate_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM "user"')).scalar_one() == 1
        assert connection.execute(
            text('SELECT session_version FROM "user" WHERE id = 1')
        ).scalar_one() == 1


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
    assert 'ALTER TABLE "user" ALTER COLUMN session_version SET DEFAULT 1' in statements
    assert 'ALTER TABLE "user" ALTER COLUMN session_version SET NOT NULL' in statements


def test_cleared_environment_uses_local_sqlite_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)

    fallback_url = resolve_database_url(tmp_path)
    assert fallback_url.startswith("sqlite:///")

    engine = create_database_engine(fallback_url)
    initialize_database(engine)
    assert "user" in inspect(engine).get_table_names()
    engine.dispose()
