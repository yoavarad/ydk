# dotnet-webapi-clean pack: architecture and default choices

**Status:** accepted

We're adding `dotnet-webapi-clean`, a new YDK catalog ignition pack scaffolding an ASP.NET Core Web API with Clean-style layering (Domain/Application/Infrastructure/Api). Verification plugins for dotnet (`dotnet-build`, `dotnet-test`, `dotnet-format`, `dotnet-quality`, `dotnet-tdd-guard`) already existed with no pack to generate against. We chose Minimal APIs over Controllers to mirror the thin-route-delegates-to-service style already used by `python-fastapi-hexagonal`, `net8.0` (LTS) as the default target framework with `net10.0` as a documented opt-in swap (rather than multi-targeting, which would require both SDKs installed locally for verification plugins to exercise both), SQLite as the default EF Core provider so `dotnet build`/`dotnet test` never require a live database out of the box, and xUnit as the test framework.

## Considered options

- **Controllers instead of Minimal APIs** — more familiar to enterprise .NET teams, but adds an extra attribute-routing/`ControllerBase` layer that buys nothing since business logic already lives in Application-layer services either way.
- **PostgreSQL as default provider** — would match `python-fastapi-hexagonal`'s Postgres-first convention, but requires a live DB for the generated skeleton to build/test, conflicting with the fail-open "just works" design of the existing dotnet verify plugins. Documented as an easy swap instead.
- **Multi-targeting `net8.0;net10.0`** — rejected as the generated default; doubles the build/test matrix and requires both SDKs present locally. A project can bump to `net10.0` by changing one line.

## Consequences

- `docs/adrs/` did not previously exist in this repo; created here as the first entry.
- Pack naming (`dotnet-webapi-clean`) intentionally diverges from `python-fastapi-hexagonal`'s "hexagonal" label — the C# community says "Clean Architecture" for this layering, not "hexagonal."
