"""Payment / wallet workload.

Real, DB-backed money movement with the same rigour as the reservation
workload: integer minor units, double-entry ledger, no-overdraft invariant,
idempotent replay, and advisory-lock serialisation of concurrent transfers.

Nothing here is simulated. If the database cannot guarantee an invariant the
request fails closed.
"""

import hashlib
import json
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg import errors
from pydantic import BaseModel, Field

from .db import session

router = APIRouter(prefix="/payments", tags=["payments"])


class AccountBody(BaseModel):
    owner_name: str = Field(min_length=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    opening_balance_minor: int = Field(default=0, ge=0)


class TransferBody(BaseModel):
    idempotency_key: str = Field(min_length=1)
    source_account: UUID
    target_account: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


def _err(status: int, code: str, message: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _iso(value) -> str:
    """Render every timestamp in UTC, matching the reservation API contract."""
    return value.astimezone(timezone.utc).isoformat()


def _account_out(row: dict) -> dict:
    return {
        "account_id": str(row["account_id"]),
        "owner_name": row["owner_name"],
        "currency": row["currency"],
        "balance_minor": row["balance_minor"],
        "created_at": _iso(row["created_at"]),
    }


def _transfer_out(row: dict) -> dict:
    out = dict(row)
    out.pop("request_hash", None)
    out["transfer_id"] = str(out["transfer_id"])
    out["source_account"] = str(out["source_account"])
    out["target_account"] = str(out["target_account"])
    out["created_at"] = _iso(out["created_at"])
    return out


def _request_hash(source: UUID, target: UUID, amount_minor: int, currency: str) -> str:
    payload = {
        "source_account": str(source),
        "target_account": str(target),
        "amount_minor": amount_minor,
        "currency": currency,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@router.post("/accounts", status_code=201)
def create_account(body: AccountBody):
    currency = body.currency.upper()
    if not body.owner_name.strip():
        return _err(400, "INVALID_OWNER", "owner_name must not be blank")
    with session() as conn:
        row = conn.execute(
            "INSERT INTO accounts (owner_name, currency, balance_minor) VALUES (%s, %s, %s)"
            " RETURNING account_id, owner_name, currency, balance_minor, created_at",
            (body.owner_name.strip(), currency, body.opening_balance_minor),
        ).fetchone()
    return _account_out(row)


@router.get("/accounts/{account_id}")
def get_account(account_id: str):
    try:
        with session() as conn:
            row = conn.execute(
                "SELECT account_id, owner_name, currency, balance_minor, created_at"
                "  FROM accounts WHERE account_id = %s",
                (account_id,),
            ).fetchone()
    except errors.InvalidTextRepresentation:
        row = None
    if row is None:
        return _err(404, "ACCOUNT_NOT_FOUND", "account not found")
    return _account_out(row)


@router.get("/accounts/{account_id}/entries")
def account_entries(account_id: str):
    """The account's half of the double-entry ledger, newest first."""
    try:
        with session() as conn:
            account = conn.execute(
                "SELECT account_id FROM accounts WHERE account_id = %s", (account_id,)
            ).fetchone()
            if account is None:
                return _err(404, "ACCOUNT_NOT_FOUND", "account not found")
            rows = conn.execute(
                "SELECT entry_id, transfer_id, direction, amount_minor, created_at"
                "  FROM ledger_entries WHERE account_id = %s ORDER BY entry_id DESC LIMIT 100",
                (account_id,),
            ).fetchall()
    except errors.InvalidTextRepresentation:
        return _err(404, "ACCOUNT_NOT_FOUND", "account not found")
    return {
        "account_id": str(account_id),
        "entries": [
            {
                "entry_id": row["entry_id"],
                "transfer_id": str(row["transfer_id"]),
                "direction": row["direction"],
                "amount_minor": row["amount_minor"],
                "created_at": _iso(row["created_at"]),
            }
            for row in rows
        ],
    }


@router.get("/ledger/trial-balance")
def trial_balance():
    """Global ledger invariant: total debits must equal total credits."""
    with session() as conn:
        row = conn.execute(
            "SELECT COALESCE(sum(amount_minor) FILTER (WHERE direction = 'debit'), 0) AS debits,"
            "       COALESCE(sum(amount_minor) FILTER (WHERE direction = 'credit'), 0) AS credits,"
            "       count(*) AS entries"
            "  FROM ledger_entries"
        ).fetchone()
        balances = conn.execute(
            "SELECT COALESCE(sum(balance_minor), 0) AS total, count(*) AS accounts FROM accounts"
        ).fetchone()
    return {
        "debits_minor": row["debits"],
        "credits_minor": row["credits"],
        "entries": row["entries"],
        "accounts": balances["accounts"],
        "total_balance_minor": balances["total"],
        "balanced": row["debits"] == row["credits"],
    }


@router.post("/transfers", status_code=201)
def create_transfer(body: TransferBody, request: Request):
    if body.source_account == body.target_account:
        return _err(400, "SAME_ACCOUNT", "source and target accounts must differ")
    currency = body.currency.upper()
    rhash = _request_hash(body.source_account, body.target_account, body.amount_minor, currency)
    # Deterministic lock order on the two accounts prevents deadlocks between
    # opposite-direction concurrent transfers.
    low, high = sorted([str(body.source_account), str(body.target_account)])
    with session() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (low,))
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (high,))

            existing = conn.execute(
                "SELECT transfer_id, idempotency_key, request_hash, source_account, target_account,"
                "       amount_minor, currency, status, created_at"
                "  FROM transfers WHERE idempotency_key = %s",
                (body.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != rhash:
                    return _err(409, "IDEMPOTENCY_PAYLOAD_MISMATCH",
                                "same idempotency_key with a different payload")
                return JSONResponse(status_code=200, content=_transfer_out(existing))

            source = conn.execute(
                "SELECT account_id, currency FROM accounts WHERE account_id = %s",
                (body.source_account,),
            ).fetchone()
            target = conn.execute(
                "SELECT account_id, currency FROM accounts WHERE account_id = %s",
                (body.target_account,),
            ).fetchone()
            if source is None or target is None:
                return _err(404, "UNKNOWN_ACCOUNT", "source or target account does not exist")
            if source["currency"] != currency or target["currency"] != currency:
                return _err(409, "CURRENCY_MISMATCH", "account currency does not match the transfer")

            # The no-overdraft invariant is enforced here by the conditional
            # UPDATE, and again in the database by CHECK (balance_minor >= 0).
            debited = conn.execute(
                "UPDATE accounts SET balance_minor = balance_minor - %s"
                " WHERE account_id = %s AND balance_minor >= %s RETURNING balance_minor",
                (body.amount_minor, body.source_account, body.amount_minor),
            ).fetchone()
            if debited is None:
                return _err(409, "INSUFFICIENT_FUNDS", "source account has insufficient funds")

            conn.execute(
                "UPDATE accounts SET balance_minor = balance_minor + %s WHERE account_id = %s",
                (body.amount_minor, body.target_account),
            )
            transfer = conn.execute(
                "INSERT INTO transfers (idempotency_key, request_hash, source_account, target_account,"
                " amount_minor, currency) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (body.idempotency_key, rhash, body.source_account, body.target_account,
                 body.amount_minor, currency),
            ).fetchone()
            conn.execute(
                "INSERT INTO ledger_entries (transfer_id, account_id, direction, amount_minor)"
                " VALUES (%s, %s, 'debit', %s), (%s, %s, 'credit', %s)",
                (transfer["transfer_id"], body.source_account, body.amount_minor,
                 transfer["transfer_id"], body.target_account, body.amount_minor),
            )
    return _transfer_out(transfer)


@router.get("/transfers/{transfer_id}")
def get_transfer(transfer_id: str):
    try:
        with session() as conn:
            row = conn.execute(
                "SELECT transfer_id, idempotency_key, source_account, target_account, amount_minor,"
                "       currency, status, created_at FROM transfers WHERE transfer_id = %s",
                (transfer_id,),
            ).fetchone()
    except errors.InvalidTextRepresentation:
        row = None
    if row is None:
        return _err(404, "TRANSFER_NOT_FOUND", "transfer not found")
    return _transfer_out(row)