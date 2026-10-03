"""Test configuration.

Test-database isolation (hard requirement):
  * the application/demo uses ``DATABASE_URL`` (default .../reservations);
  * automated tests use ``TEST_DATABASE_URL`` (default .../reservations_test).

The test process re-points ``DATABASE_URL`` at the isolated test database before
the application code is imported, and refuses to run at all if the two URLs are
the same. This is what stops ``pytest`` from truncating demo projects/runs.
"""

import os
import socket
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import pytest

DEFAULT_APPLICATION_URL = "postgresql://postgres@127.0.0.1:5439/reservations"


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, ""))


def _derive_test_url(application_url: str) -> str:
    parts = urlsplit(application_url)
    name = (parts.path.lstrip("/") or "reservations") + "_test"
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, ""))


APPLICATION_DATABASE_URL = (
    os.environ.get("APPLICATION_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or DEFAULT_APPLICATION_URL
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or _derive_test_url(APPLICATION_DATABASE_URL)

if _canonical(TEST_DATABASE_URL) == _canonical(APPLICATION_DATABASE_URL):
    raise RuntimeError(
        "Refusing to run tests: TEST_DATABASE_URL must not point at the application "
        f"database ({_canonical(TEST_DATABASE_URL)}). Set TEST_DATABASE_URL to an "
        "isolated database, or unset it to use the derived '<name>_test' database."
    )

# Point the application code at the isolated test database BEFORE importing it.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Make both URLs available to tests that assert isolation.
os.environ["APPLICATION_DATABASE_URL"] = APPLICATION_DATABASE_URL
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL

from pg_utils import ensure_database, ensure_server  # noqa: E402

from app.backend.db import apply_schema, session  # noqa: E402

TEST_DB_NAME = urlsplit(TEST_DATABASE_URL).path.lstrip("/")


@pytest.fixture(scope="session", autouse=True)
def database():
    ensure_server()
    ensure_database(TEST_DB_NAME)
    apply_schema()
    yield


@pytest.fixture(autouse=True)
def clean_tables(database):
    with session() as conn:
        conn.execute("TRUNCATE reservations, tables, accounts, transfers, ledger_entries, projects CASCADE")
    yield


@pytest.fixture()
def client(database):
    from fastapi.testclient import TestClient

    from app.backend.main import app

    return TestClient(app)


@pytest.fixture()
def live_server(database):
    """Run the app under a real uvicorn server for concurrency tests."""
    import uvicorn

    from app.backend.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
