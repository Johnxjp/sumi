# Testing

How tests run and what a change must cover. Tests live in
`sumi-backend/tests/`; run everything from `sumi-backend/`.

## Running

- `uv run pytest` — the full suite. `uv run pytest tests/test_pooling.py::test_pool_merges_same_text_across_retrievers` — one test.
- Tests marked `pytest.mark.postgres` need a local Postgres. The `test_db_url`
  fixture in `tests/conftest.py` skips them when none is running — a run where
  they skipped is not a green run. They never use the real `DATABASE_URL`.
- A task is done only when `uv run pytest` and `uv run ruff check .` both pass
  and the output has been checked against a real input, not just the tests.

## Standards

- **Target exactly 100% coverage of what the PR changes — no more, no less.**
  Every changed or added behaviour must have a test; every test must fail without
  the PR's change. Do not add tests for pre-existing logic, and do not test
  standard-library or third-party functions. The exception is deliberate
  behaviour or integration tests, which may cross those boundaries by design.
- Tests live in `tests/` and test logic, not HTTP/framework plumbing.
- Use pytest patterns, not `unittest.TestCase`.
- Use `spec`/`autospec` when mocking.
- Prefer `@mock.patch` decorators over `with mock.patch(...)` context managers.
- Use `@pytest.mark.parametrize` for multiple similar inputs — consolidate tests
  that only differ in input/expected values into a single parametrized test.
- Tests that need a database are marked `pytest.mark.postgres` and use the
  `test_db_url` fixture from `tests/conftest.py`, which skips them when local
  Postgres isn't running; never point them at the real `DATABASE_URL`.
- Do not assert on raw log text.
