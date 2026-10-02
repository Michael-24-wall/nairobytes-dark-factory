import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres@127.0.0.1:5439/reservations"
)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


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
