# dotnet-webapi-clean

YDK ignition pack for generating an ASP.NET Core Web API using Clean-style layering
(Domain / Application / Infrastructure / Api), Minimal APIs, EF Core with SQLite,
and xUnit test scaffolding. Targets `net8.0` (LTS) by default; `net10.0` is a
documented opt-in swap. See `docs/adrs/0001-dotnet-webapi-clean-defaults.md` in the
YDK repo for the accepted defaults and considered alternatives.

## Architecture

- **Domain** -- entities and core domain types, no framework dependencies.
- **Application** -- service contracts and business logic, depends only on Domain.
- **Infrastructure** -- EF Core `DbContext`, repository implementations, DI wiring.
- **Api** -- Minimal API endpoint definitions, thin route delegates that call into
  Application-layer services (mirrors the thin-route-delegates-to-service style used
  by `python-fastapi-hexagonal`).

Minimal APIs are used instead of Controllers to avoid an extra attribute-routing
layer that would buy nothing, since business logic already lives in Application
services either way.

## Inputs

| Component Type | Required | Description |
|---|---|---|
| entity | yes | Domain entities with fields, types, table names |
| route | yes | HTTP route definitions (method, path, request/response) |
| contract | yes | Service contracts with methods, ports, errors |
| error | no | Custom error definitions |

## Generators

See `manifest.yaml` for the full execution order. All 13 generators:

- **solution_scaffold** -- .sln/.csproj files and Domain/Application/Infrastructure/Api project skeleton
- **program_and_config** -- `Program.cs` bootstrap, `appsettings.json`, minimal API host wiring
- **domain_entities** -- Domain-layer entity classes from entity definitions
- **efcore_dbcontext** -- EF Core `DbContext` and entity configurations (SQLite default)
- **repository_interfaces** -- Repository interface contracts in the Application layer
- **repository_implementations** -- EF Core-backed repository implementations in Infrastructure
- **service_stubs** -- Application service classes with TODO stubs from contract definitions
- **api_endpoints** -- Minimal API endpoint mappings delegating to Application services
- **dependency_injection** -- DI container wiring for repositories and services
- **fake_repositories** -- In-memory fake repositories for testing
- **unit_test_stubs** -- xUnit unit test scaffolding for services
- **endpoint_test_stubs** -- xUnit integration test scaffolding for API endpoints
- **entity_test_stubs** -- xUnit unit test scaffolding for domain entities

## Verification Sets

- `dotnet-quality` -- `dotnet build`, `dotnet format` checks
- `dotnet-tdd-guard` -- `dotnet test` enforcement, test-first guardrails
