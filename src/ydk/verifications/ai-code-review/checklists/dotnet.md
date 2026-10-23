=== .NET REVIEW CHECKLIST ===

This project uses a C#/.NET stack. In addition to the general review above,
check the diff against the C#/.NET standards below. Report violations using
the existing categories and severities. Treat repository conventions as
authoritative where they do not conflict with security or correctness, and do
not report speculative issues as definite defects.

Prioritize findings in this order:
1. Security, authorization, privacy, and secret exposure.
2. Data loss/corruption, transaction boundaries, concurrency, and consistency.
3. Incorrect behavior, exception handling, cancellation, and resource leaks.
4. API/serialization compatibility and persistence/query problems.
5. Missing or misleading tests and observability.
6. Performance problems supported by evidence or a credible execution path.
7. Maintainability issues that materially increase future defect risk.

## C#/.NET guardrails

- Prefer asynchronous APIs for I/O-bound work; avoid sync-over-async and `.Result`/`.Wait()` in request paths.
- Accept and propagate `CancellationToken` through async boundaries when cancellation is meaningful.
- Use explicit outbound HTTP timeouts and `IHttpClientFactory` or the repository's established equivalent.
- Use dependency injection with correct service lifetimes; do not capture scoped services in singletons.
- Enable and respect nullable reference types; avoid null-forgiving operators unless the invariant is justified.
- Validate external input at boundaries; keep domain invariants explicit.
- Use structured logging with stable message templates; never log secrets, credentials, tokens, or unnecessary personal data.
- Preserve exception context with `throw;` when rethrowing the caught exception; catch only when the code can handle, translate, clean up, or add meaningful context.
- Use `decimal` for money and explicit, consistent UTC/time-zone handling for timestamps.
- Configure JSON serialization consistently; treat names, enum representations, null behavior, and date formats as contracts.
- For EF Core, project only required fields, use `AsNoTracking()` for read-only queries where appropriate, avoid N+1 queries, and paginate potentially large results.
- Parameterize SQL; do not concatenate untrusted input into SQL.
- Keep transactions short and intentional; do not hold them across slow external calls.
- Dispose owned disposable resources; use `using`/`await using` where appropriate.
- Test behavior, edge cases, and failure paths; avoid brittle tests tied to implementation details.
- Prefer automated enforcement via compiler settings, analyzers, formatting, and CI rather than relying on memory alone.

## Pull request checklist

### Correctness and errors
- No empty or meaningless `catch` blocks.
- Caught exceptions are specific and handled at the correct layer.
- Rethrows preserve stack traces; wrapped exceptions preserve the inner exception.
- Errors are not logged repeatedly at every layer.
- Guard clauses keep the main path readable.
- Expected outcomes are modeled without exceptions as routine control flow.

### Logging and diagnostics
- Logs use structured placeholders, not interpolation or concatenation.
- Log levels are deliberate.
- No secrets, credentials, or unnecessary personal data are logged.
- Requests can be traced with a correlation/trace ID.
- No noisy per-item logging in hot loops.

### Async and concurrency
- No `.Result`, `.Wait()`, or `.GetAwaiter().GetResult()` in normal async flow.
- Cancellation tokens are passed through.
- Outbound calls have explicit timeouts.
- No unmanaged fire-and-forget tasks.
- Shared mutable state has a concurrency strategy.
- Parallel work is bounded.

### Contracts and data
- APIs use DTOs rather than exposing persistence entities.
- Published contracts remain backward compatible or have a migration plan.
- Money uses `decimal`.
- Queries are parameterized.
- No database query inside a loop where set-based access is possible.
- Collections are bounded/paginated.
- Transactions contain short database work, not remote I/O.

### Configuration and resources
- No environment-specific values or secrets are hard-coded.
- Configuration is typed and validated at startup.
- DI lifetimes are correct; no scoped dependency is captured by a singleton.
- HTTP clients are managed through `IHttpClientFactory` or an explicitly justified alternative.
- Opened resources are disposed deterministically.
- Time is handled with UTC/explicit zones and testable clock behavior where relevant.

### Tests and maintainability
- Tests verify observable behavior and use independent expected values.
- Test names describe scenario and expectation.
- Bug fixes include regression tests.
- Relevant error, boundary, and cancellation paths are covered.
- No dead/commented-out code remains.
- Comments explain why rather than restating what.

## Definition of done

Items a diff reviewer cannot verify (build and analyzer results, PR
description, reported limitations) are covered by other verification
plugins and the PR process, so they are omitted here.

A change is ready for review when:
1. It meets the rules above or documents a justified deviation.
2. The implementation fits the existing architecture and naming conventions.
3. Tests cover the intended behavior and relevant failure paths.
4. Configuration, secrets, logging, and API compatibility have been considered.
5. The implementation is focused and avoids unrelated changes.
6. Inputs, errors, authorization, cancellation, and resource ownership are handled appropriately.
