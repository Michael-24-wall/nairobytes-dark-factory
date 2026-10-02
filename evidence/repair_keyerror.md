# Repair: tests/test_schema.py::test_db_allows_back_to_back_insert — KeyError: 0

## Reproduction

```
.venv/Scripts/python.exe -m pytest tests -q
...
>           count = conn.execute("SELECT count(*) FROM reservations").fetchone()[0]
E           KeyError: 0
tests\test_schema.py:55: KeyError
1 failed, 10 passed
```

## Root cause

`app/backend/db.py` connects with `row_factory=dict_row`, so every cursor
returns `dict` rows. The test indexed the row positionally (`row[0]`), which
on a dict raises `KeyError: 0`. The data itself was correct — the second
adjacent reservation (19:00–20:00, starting exactly when the first ends) was
inserted successfully; only the row access was wrong.

## Fix

`tests/test_schema.py:55` now reads the count through the dict key:

```python
count = conn.execute("SELECT count(*) AS count FROM reservations").fetchone()["count"]
```

The assertion is unchanged: `assert count == 2` still proves that adjacent
reservations (`end_time == start_time`) are both stored, while the exclusion
constraint tests in the same file still prove overlapping rows are rejected.
No test was weakened or removed.

## Result after fix

```
.venv/Scripts/python.exe -m pytest tests -q
11 passed, 1 warning in 4.96s
```

Full outputs: `evidence/builder_test_run_after_repair.txt` (quiet) and
`evidence/builder_test_run_verbose.txt` (per-test PASSED list).
