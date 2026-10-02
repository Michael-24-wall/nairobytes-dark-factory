# Breaker Timezone Verification

Command:

```text
.venv\Scripts\python.exe -m pytest tests/timezone -q
```

Observed output:

```text
........                                                                 [100%]
============================== warnings summary ===============================
tests/timezone/test_timezone.py::test_naive_input_rejected_before_normalize
  C:\Users\Michael\Desktop\BANDS\nairobytes-dark-factory\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
8 passed, 1 warning in 7.02s
```

The equivalent-instant test uses different tables, so it verifies UTC normalization without contradicting the no-overlap invariant. A separate same-table test verifies that the equivalent second request receives `409 OVERLAP_CONFLICT`.

Malformed timestamp probe:

```text
malformed_timestamp_status= 422
malformed_timestamp_body= {'detail': [{'type': 'datetime_from_date_parsing', 'loc': ['body', 'start_time'], 'msg': 'Input should be a valid datetime or date, invalid character in year', 'input': 'not-a-timestamp', 'ctx': {'error': 'invalid character in year'}}]}
```

Result: **PASS**. UTC, positive-offset, negative-offset, equivalent-instant, naive, malformed, and returned-UTC timestamp behavior held.