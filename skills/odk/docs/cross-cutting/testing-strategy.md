# Testing Strategy (Cross-Cutting)

This defines the default testing strategy for all ODK-managed projects. Projects can customize, but these are the sensible defaults.

## Structure

```
tests/
├── unit/           # Mirrors src/ structure. No I/O. Fast.
├── integration/    # Real external systems. Slower.
├── e2e/            # Full stack. Slowest.
└── conftest.py     # Shared fixtures
```

## Unit Test Mirroring Rule

For every source module, there MUST be a corresponding unit test:

```
src/domain/validation/order_validator.py
  → tests/unit/domain/validation/test_order_validator.py

src/services/order_service.py
  → tests/unit/services/test_order_service.py
```

Pattern: `tests/unit/<same path>/test_<module_name>.py`

## TDD is Mandatory

Red-Green-Refactor for all implementation. Tests written BEFORE code. See `stages/03-execution/aspects/testing-strategy.md` for the full TDD protocol.

## Rules

- NEVER mock internal classes
- NEVER use SQLite as PostgreSQL substitute
- Database tests use testcontainers (real PostgreSQL)
- External API stubs use recorded real responses
- Each test creates its own data (no shared global state)
- Test names read as sentences: `test_insufficient_balance_returns_422`
