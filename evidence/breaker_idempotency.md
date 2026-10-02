# Breaker Idempotency Verification

Command:

```text
.venv\Scripts\python.exe -m pytest tests/idempotency -q
```

Observed output:

```text
........                                                                 [100%]
============================== warnings summary ===============================
tests/idempotency/test_idempotency.py::test_replay_identical_payload_200_same_id_one_row
  C:\Users\Michael\Desktop\BANDS\nairobytes-dark-factory\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
8 passed, 1 warning in 8.20s
```

The eight tests verify identical replay, repeated replay, offset-equivalent replay, same-key payload mismatch for changed name and windows, distinct keys, and the unique-key invariant. Concurrent replay is also covered by the concurrency suite and passed in all fifteen repeated stress cases.

Result: **PASS**. No duplicate reservation was created and mismatched payloads were rejected.