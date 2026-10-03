"""Prove that the test suite cannot destroy the application/demo database.

These tests intentionally read ``APPLICATION_DATABASE_URL`` (the demo database)
directly and perform destructive work on the isolated test database, then assert
the demo database is untouched.
"""

import os
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

from app.backend.db import session

APPLICATION_DATABASE_URL = os.environ["APPLICATION_DATABASE_URL"]
TEST_DATABASE_URL = os.environ["DATABASE_URL"]


def _db_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def test_tests_run_against_an_isolated_database():
    assert _db_name(TEST_DATABASE_URL) != _db_name(APPLICATION_DATABASE_URL)
    with session() as conn:
        current = conn.execute("SELECT current_database() AS name").fetchone()["name"]
    assert current == _db_name(TEST_DATABASE_URL), current
    assert current != _db_name(APPLICATION_DATABASE_URL), current


def test_testing_cannot_destroy_application_state():
    """Create a project in the demo DB, truncate the test DB, prove the demo row survives."""
    marker = f"isolation-proof-{uuid4().hex[:8]}"
    with psycopg.connect(APPLICATION_DATABASE_URL, autocommit=True) as conn:
        project_id = conn.execute(
            "INSERT INTO projects (name, slug, project_type) VALUES (%s, %s, %s) RETURNING id",
            ("Isolation Proof", marker, "Website"),
        ).fetchone()[0]
    try:
        # Destructive operations that a normal test fixture performs, on the TEST database.
        with session() as conn:
            conn.execute("TRUNCATE reservations, tables, accounts, transfers, ledger_entries, projects CASCADE")

        # The application database row must still exist.
        with psycopg.connect(APPLICATION_DATABASE_URL, autocommit=True) as conn:
            survived = conn.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,)).fetchone()
        assert survived is not None, "the automated test suite destroyed application/demo data"
    finally:
        with psycopg.connect(APPLICATION_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM projects WHERE id = %s", (project_id,))

    # And the test database really is empty of that project.
    with session() as conn:
        leaked = conn.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,)).fetchone()
    assert leaked is None