"""Equipment browser fixtures must reject non-local databases before connecting."""

import runpy
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "prepare_e2e_equipment.py"


@pytest.mark.parametrize(
    "database",
    [
        "postgresql+psycopg://fixture:fixture@example.invalid/db",
        "postgresql+psycopg://fixture:fixture@localhost.example.invalid/db",
        "sqlite:///fixture.db",
    ],
)
def test_rejects_nonlocal_database_before_engine_creation(monkeypatch, database):
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    engine = Mock(side_effect=AssertionError("Must refuse before creating a database engine"))
    monkeypatch.setattr("sqlalchemy.create_engine", engine)

    with pytest.raises(SystemExit, match="local-only"):
        runpy.run_path(str(SCRIPT), run_name="__main__")

    engine.assert_not_called()


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_allows_existing_local_database_hosts(monkeypatch, host):
    database = f"postgresql+psycopg://fixture:fixture@{host}:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    # Stop at the database boundary: the guard test must never mutate real fixture records.
    engine = Mock(side_effect=RuntimeError("Local database accepted"))
    monkeypatch.setattr("sqlalchemy.create_engine", engine)

    with pytest.raises(RuntimeError, match="Local database accepted"):
        runpy.run_path(str(SCRIPT), run_name="__main__")

    engine.assert_called_once_with(database)
