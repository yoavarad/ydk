# python-fastapi-hexagonal

YDK ignition pack for generating a complete FastAPI backend using hexagonal architecture with Protocol-based ports, SQLAlchemy models, Pydantic schemas, and full test scaffolding.

## Architecture

Generators read YDK component manifests directly via `YDK_COMPONENTS_*` env vars.
Entity/service names are derived from the component `id` field. Fields are consumed
as maps (keyed by field name). No adapter layers or format translation.

## Inputs

| Component Type | Required | Description |
|---|---|---|
| entity | yes | Domain entities with fields, types, table names |
| route | yes | HTTP route definitions (method, path, request/response) |
| contract | yes | Service contracts with methods, ports, errors |
| error | no | Custom error definitions |
| event | no | Domain event definitions (reserved) |

## Generators

See `manifest.yaml` for the full execution order. Key generators:

- **sqlalchemy_models** -- ORM model files from entity definitions
- **repository_ports / protocol_ports** -- Protocol-based port interfaces
- **db_postgres_repos** -- PostgreSQL repository implementations
- **pydantic_schemas** -- Request/response Pydantic models
- **fastapi_service_stubs** -- Service layer with TODO stubs
- **fastapi_routes** -- Thin route handlers delegating via Depends()
- **fastapi_dependencies** -- DI wiring
- **app_factory** -- FastAPI app with lifespan, middleware, router registration
- **alembic_initial** -- Database migration scaffolding
- **fake_repos / fake_ports** -- In-memory fakes for testing
- **conftest_generator / unit_test_stubs / route_test_stubs / contract_tests** -- Test scaffolding

## Verification Sets

- `hexagonal-architecture` -- Ensures adapter isolation, core purity, route delegation
- `python-quality` -- Ruff, type checking, import ordering
