"""Shared fixtures for tests that need a local Postgres."""

import psycopg
import pytest


def is_postgres_available() -> bool:
    try:
        with psycopg.connect("postgresql://localhost:5432/postgres", connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marked = [item for item in items if "postgres" in item.keywords]
    if marked and not is_postgres_available():
        skip = pytest.mark.skip(reason="local Postgres is not running")
        for item in marked:
            item.add_marker(skip)


@pytest.fixture
def test_db_url() -> str:
    with psycopg.connect(
        "postgresql://localhost:5432/postgres", autocommit=True
    ) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'sumi_test'"
        ).fetchone()
        if row is None:
            conn.execute("CREATE DATABASE sumi_test")
    return "postgresql://localhost:5432/sumi_test"
