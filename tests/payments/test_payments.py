"""Payment / wallet workload tests (ledger integrity, idempotency, no overdraft, concurrency).

These tests are hermetic: they use the in-process client for behaviour and a real
uvicorn server for the concurrency race, exactly like the reservation suite.
"""

import concurrent.futures as cf
import threading
import uuid

import httpx

from app.backend.db import session

WORKERS = 8


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _create_account(client, owner="Alice", currency="USD", opening=0):
    r = client.post(
        "/payments/accounts",
        json={"owner_name": owner, "currency": currency, "opening_balance_minor": opening},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _transfer(client, source, target, amount, key=None, currency="USD"):
    return client.post(
        "/payments/transfers",
        json={
            "idempotency_key": key or _uniq("key"),
            "source_account": source,
            "target_account": target,
            "amount_minor": amount,
            "currency": currency,
        },
    )


def _balance(account_id):
    with session() as conn:
        return conn.execute(
            "SELECT balance_minor FROM accounts WHERE account_id = %s", (account_id,)
        ).fetchone()["balance_minor"]


def _counts():
    with session() as conn:
        transfers = conn.execute("SELECT count(*) AS n FROM transfers").fetchone()["n"]
        entries = conn.execute("SELECT count(*) AS n FROM ledger_entries").fetchone()["n"]
    return transfers, entries


def test_create_account_201_shape(client):
    account = _create_account(client, owner="Alice", opening=500)
    assert account["account_id"]
    assert account["owner_name"] == "Alice"
    assert account["currency"] == "USD"
    assert account["balance_minor"] == 500
    assert account["created_at"].endswith("+00:00")


def test_blank_owner_rejected_422(client):
    r = client.post("/payments/accounts", json={"owner_name": "", "currency": "USD"})
    assert r.status_code == 422


def test_transfer_moves_funds_and_double_entry(client):
    src = _create_account(client, "Alice", opening=1000)
    dst = _create_account(client, "Bob", opening=0)
    r = _transfer(client, src["account_id"], dst["account_id"], 300)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_minor"] == 300
    assert body["status"] == "settled"
    assert body["source_account"] == src["account_id"]
    assert body["target_account"] == dst["account_id"]
    assert _balance(src["account_id"]) == 700
    assert _balance(dst["account_id"]) == 300
    with session() as conn:
        rows = conn.execute(
            "SELECT direction, amount_minor FROM ledger_entries WHERE transfer_id = %s ORDER BY direction",
            (body["transfer_id"],),
        ).fetchall()
    assert [(row["direction"], row["amount_minor"]) for row in rows] == [("credit", 300), ("debit", 300)]


def test_trial_balance_stays_balanced(client):
    src = _create_account(client, "Alice", opening=1000)
    dst = _create_account(client, "Bob", opening=1000)
    for _ in range(4):
        assert _transfer(client, src["account_id"], dst["account_id"], 100).status_code == 201
    tb = client.get("/payments/ledger/trial-balance").json()
    assert tb["balanced"] is True
    assert tb["debits_minor"] == tb["credits_minor"] == 400
    assert tb["total_balance_minor"] == 2000


def test_insufficient_funds_409_and_nothing_persisted(client):
    src = _create_account(client, opening=100)
    dst = _create_account(client, opening=0)
    before = _counts()
    r = _transfer(client, src["account_id"], dst["account_id"], 150)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "INSUFFICIENT_FUNDS"
    assert _balance(src["account_id"]) == 100
    assert _balance(dst["account_id"]) == 0
    assert _counts() == before


def test_idempotent_replay_returns_same_transfer(client):
    src = _create_account(client, opening=1000)
    dst = _create_account(client, opening=0)
    key = _uniq("replay")
    first = _transfer(client, src["account_id"], dst["account_id"], 250, key=key)
    second = _transfer(client, src["account_id"], dst["account_id"], 250, key=key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["transfer_id"] == first.json()["transfer_id"]
    assert _balance(src["account_id"]) == 750
    assert _counts() == (1, 2)


def test_same_key_different_payload_409(client):
    src = _create_account(client, opening=1000)
    dst = _create_account(client, opening=0)
    key = _uniq("mismatch")
    assert _transfer(client, src["account_id"], dst["account_id"], 100, key=key).status_code == 201
    r = _transfer(client, src["account_id"], dst["account_id"], 200, key=key)
    assert r.status_code == 409
    assert r.json()["error"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    assert _balance(src["account_id"]) == 900
    assert _counts() == (1, 2)


def test_same_account_400(client):
    account = _create_account(client, opening=100)
    r = _transfer(client, account["account_id"], account["account_id"], 10)
    assert r.status_code == 400
    assert r.json()["error"] == "SAME_ACCOUNT"


def test_unknown_account_404(client):
    account = _create_account(client, opening=100)
    r = _transfer(client, account["account_id"], str(uuid.uuid4()), 10)
    assert r.status_code == 404
    assert r.json()["error"] == "UNKNOWN_ACCOUNT"


def test_currency_mismatch_409(client):
    usd = _create_account(client, "USD holder", currency="USD", opening=100)
    eur = _create_account(client, "EUR holder", currency="EUR", opening=0)
    r = _transfer(client, usd["account_id"], eur["account_id"], 10, currency="USD")
    assert r.status_code == 409
    assert r.json()["error"] == "CURRENCY_MISMATCH"


def test_malformed_ids_404(client):
    assert client.get("/payments/transfers/not-a-uuid").status_code == 404
    assert client.get("/payments/accounts/not-a-uuid").status_code == 404


# ---------------------------------------------------------------------------
# concurrency: a live server, real parallel transfers, no overdraft allowed
# ---------------------------------------------------------------------------


def _post_transfer(base_url, payload, barrier):
    barrier.wait()
    with httpx.Client(base_url=base_url, timeout=30) as http:
        response = http.post("/payments/transfers", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        return response.status_code, body


def test_concurrent_transfers_never_overdraw(live_server):
    with httpx.Client(base_url=live_server, timeout=30) as http:
        src = http.post("/payments/accounts", json={"owner_name": "Src", "currency": "USD", "opening_balance_minor": 100}).json()
        dst = http.post("/payments/accounts", json={"owner_name": "Dst", "currency": "USD", "opening_balance_minor": 0}).json()

    payloads = [
        {
            "idempotency_key": _uniq("race"),
            "source_account": src["account_id"],
            "target_account": dst["account_id"],
            "amount_minor": 30,
            "currency": "USD",
        }
        for _ in range(WORKERS)
    ]
    barrier = threading.Barrier(WORKERS)
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = [f.result() for f in [pool.submit(_post_transfer, live_server, p, barrier) for p in payloads]]

    statuses = [status for status, _ in results]
    assert set(statuses) <= {201, 409}, results
    assert statuses.count(201) == 3, results  # 100 // 30
    assert statuses.count(409) == WORKERS - 3, results
    assert {body.get("error") for status, body in results if status == 409} == {"INSUFFICIENT_FUNDS"}

    assert _balance(src["account_id"]) == 10
    assert _balance(dst["account_id"]) == 90
    assert _counts() == (3, 6)

    with httpx.Client(base_url=live_server, timeout=30) as http:
        tb = http.get("/payments/ledger/trial-balance").json()
    assert tb["balanced"] is True