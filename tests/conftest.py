import os
import socket
import threading
import time

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres@127.0.0.1:5439/reservations"
)

from pg_utils import ensure_server  # noqa: E402

from app.backend.db import apply_schema, session  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    ensure_server()
    apply_schema()
    yield


@pytest.fixture(autouse=True)
def clean_tables(database):
    with session() as conn:
        conn.execute("TRUNCATE reservations, tables, projects CASCADE")
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
