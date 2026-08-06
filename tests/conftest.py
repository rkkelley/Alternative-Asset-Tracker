from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


TEST_DATABASE = Path(tempfile.gettempdir()) / "alt_track_pytest.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["SECRET_KEY"] = "pytest-only-secret-key"
os.environ["ENVIRONMENT"] = "test"


@pytest.fixture(scope="session")
def app():
    import main

    main.create_db_and_tables()
    return main.app


@pytest.fixture(autouse=True)
def isolated_database(app):
    from sqlmodel import SQLModel

    SQLModel.metadata.drop_all(main_engine(app))
    SQLModel.metadata.create_all(main_engine(app))
    yield


def main_engine(app):
    # The test app exposes the module-level engine through its route module.
    import main

    return main.engine


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
