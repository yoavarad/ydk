# Testing Strategy

## Three Levels

Every project using ODK has three test levels with strict structure.

### Unit Tests (`tests/unit/`)

**Mirror the source structure exactly.** For every `src/X/Y/Z.py` there MUST be `tests/unit/X/Y/test_Z.py`.

Example:
```
src/
├── domain/
│   └── validation/
│       └── order_validator.py
├── services/
│   └── order_service.py

tests/unit/
├── domain/
│   └── validation/
│       └── test_order_validator.py
├── services/
│   └── test_order_service.py
```

**Rules:**
- No I/O. No database. No network. No filesystem (except tmp_path).
- Fast: entire unit suite < 10 seconds
- Test domain logic, validation rules, pure functions, data transformations
- Mock ONLY at system boundaries (database, external APIs, clock)
- NEVER mock internal classes. If OrderService calls OrderValidator, test them together or test each independently — don't mock the validator inside the service test.

### Integration Tests (`tests/integration/`)

Tests that verify interaction with real external systems.

**Rules:**
- Database: real PostgreSQL via testcontainers. NEVER SQLite as substitute.
- External APIs: stubbed with recorded real responses (respx, responses)
- Each test gets clean state (TRUNCATE between tests, not shared state)
- Slower: suite may take minutes
- Test service + repository together against real DB

### E2E Tests (`tests/e2e/`)

Full HTTP stack via test client.

**Rules:**
- Real database (same as integration)
- External APIs stubbed
- Tests the complete request → response cycle
- Every endpoint: at minimum happy path + one error path
- Use httpx AsyncClient for FastAPI, supertest for Express, etc.

## TDD — Red-Green-Refactor

Mandatory for all implementation. This is non-negotiable.

### The Cycle

```
RED:    Write a failing test that describes desired behavior
        → Run it → MUST fail
        → If it passes, the test is wrong — it's not testing what you think

GREEN:  Write MINIMUM code to make the test pass
        → Run it → MUST pass
        → Don't write more than needed — resist the urge to "finish" the implementation

REFACTOR: Clean up without changing behavior
        → Run tests → MUST still pass
        → Only if the code needs cleaning
```

### TDD in Practice

For a task with 11 tests:

```
1. Write ALL 11 test cases (importing code that doesn't exist yet)
2. Run → 11 FAIL (ImportError)
   → odk task comment T-002 "RED: 11 tests written, all failing"

3. Implement first function — enough for 5 tests
4. Run → 5 PASS, 6 FAIL
   → odk task comment T-002 "GREEN partial: 5/11 passing"

5. Implement second function — enough for remaining
6. Run → 11 PASS
   → odk task comment T-002 "GREEN: 11/11 passing"

7. Refactor if needed
8. Run → still 11 PASS
```

### Naming Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>` (only for grouping related tests)
- Test functions: `test_<what_it_tests>` — descriptive, reads as a sentence
  - Good: `test_insufficient_balance_returns_422`
  - Bad: `test_1`, `test_order`, `test_validation`

### Test Data

- Use factories or fixtures, not shared global state
- Each test creates its own data
- Fixtures in `conftest.py` at appropriate level (project, module, test)
- Never rely on test execution order

## When to Run What

| Trigger | Tests |
|---|---|
| During TDD development | `odk verify tests --unit` (fast feedback) |
| Pre-push hook | All levels (unit + integration + E2E) |
| `odk verify tests` | All levels |
| `odk verify tests --unit` | Unit only |
| `odk verify tests --integration` | Integration only |
| `odk verify tests --e2e` | E2E only |
