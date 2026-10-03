import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5439/reservations"


def resolve_database_url() -> str:
    """The database URL used for real work.

    Resolved at call time (not import time) so that a test process can point the
    application code at an isolated database before the first connection.
    """
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row, autocommit=True)


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def apply_schema() -> None:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        ddl = f.read()
    with session() as conn:
        conn.execute(ddl)
