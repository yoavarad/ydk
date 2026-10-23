---
name: csharp-development-best-practices
description: Apply the project's C#/.NET engineering standards when implementing features, fixing bugs, reviewing code, refactoring, designing APIs, or writing tests. Use for C# and .NET repositories; consult the bundled reference before making changes.
license: MIT
---

# C# Development Best Practices

Use this skill to make C#/.NET changes that are safe, maintainable, testable, and consistent with the engineering playbook.

## Required operating procedure

1. **Inspect before changing.**
   - Read the repository's `README`, contribution instructions, solution/project files, and any local `AGENTS.md`, `CLAUDE.md`, or equivalent guidance.
   - Identify the target framework, nullable settings, analyzers, test framework, architecture, naming conventions, and existing patterns.
   - Treat repository-specific instructions and established conventions as authoritative where they do not conflict with security or correctness.
2. **Load the reference.**
   - Read `references/csharp-development-best-practices.md` for the relevant topic before implementing or reviewing non-trivial changes.
   - Apply the guidance in context; do not mechanically introduce abstractions or refactor unrelated code.
3. **Plan proportionately.**
   - For a small, localized fix, make a short plan and proceed.
   - For a broad or risky change, identify the behavior to preserve, likely affected layers, tests, migration/configuration implications, and failure modes before editing.
4. **Make the smallest complete change.**
   - Follow existing architecture and public contracts unless changing them is explicitly required.
   - Avoid unrelated cleanup, speculative abstractions, and unnecessary dependencies.
   - Handle errors deliberately; do not swallow exceptions, log and rethrow without added value, or expose sensitive data.
   - Propagate cancellation through async call chains and use explicit timeouts for outbound calls.
   - Validate untrusted input at system boundaries and enforce authorization where data is accessed or changed.
   - Keep persistence models separate from external API contracts.
5. **Verify.**
   - Run the narrowest relevant tests first, then applicable project/solution tests.
   - Build the affected project or solution and run configured formatters/analyzers when feasible.
   - If a command cannot be run, state that clearly; never claim a build or test passed unless it actually ran successfully.
6. **Report clearly.**
   - Summarize what changed and why.
   - List tests/build/analyzer commands actually run and their results.
   - Call out assumptions, known limitations, risks, and any follow-up work.

## Workflow: implement a feature

1. Restate the expected behavior and acceptance criteria from the issue/request.
2. Trace the existing path through the API endpoint, application/domain logic, persistence, and external integrations as applicable.
3. Define boundary validation, error behavior, authorization, cancellation, and API/data-contract implications.
4. Implement the feature using existing patterns and the smallest complete design.
5. Add or update tests for expected behavior, edge cases, invalid input, and failure paths.
6. Verify build, tests, and analyzers as available.
7. Report behavior changes, compatibility implications, and verification results.

## Workflow: fix a bug

1. Reproduce the failure or identify a concrete failing condition before editing when feasible.
2. Find the root cause rather than masking the symptom.
3. Add a regression test that fails before the fix when practical.
4. Make a focused correction; preserve unrelated behavior and public contracts.
5. Run the regression test and relevant surrounding tests, then build the affected project.
6. Report the root cause, fix, and verification. Distinguish confirmed facts from hypotheses if reproduction was not possible.

## Workflow: review code

Review for correctness and risk, not personal style preferences. Prioritize findings in this order:

1. Security, authorization, privacy, and secret exposure.
2. Data loss/corruption, transaction boundaries, concurrency, and consistency.
3. Incorrect behavior, exception handling, cancellation, and resource leaks.
4. API/serialization compatibility and persistence/query problems.
5. Missing or misleading tests and observability.
6. Performance problems supported by evidence or a credible execution path.
7. Maintainability issues that materially increase future defect risk.

For each finding:
- State the concrete issue and its likely impact.
- Point to the relevant file/line when available.
- Explain a realistic triggering condition.
- Recommend a focused fix.
- Avoid reporting speculative issues as definite defects.
- If no significant issues are found, say so and mention important test or verification gaps.

## Workflow: refactor

1. State the maintainability or reliability goal.
2. Identify observable behavior and contracts that must remain unchanged.
3. Add or identify tests that characterize the current behavior.
4. Refactor in small steps; do not combine unrelated behavior changes.
5. Avoid broad public API changes unless requested.
6. Run tests and build after meaningful steps; compare behavior where practical.
7. Explain what changed, what intentionally did not change, and the evidence that behavior is preserved.

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

## Definition of done

Before declaring work complete, check all applicable items:

- [ ] Requirements and existing project conventions were understood.
- [ ] The implementation is focused and avoids unrelated changes.
- [ ] Inputs, errors, authorization, cancellation, and resource ownership are handled appropriately.
- [ ] API/JSON/database compatibility was considered.
- [ ] Tests cover the main behavior and important edge/failure cases.
- [ ] Relevant tests and build were run, or inability to run them is disclosed.
- [ ] No secrets or sensitive data were added to logs or source control.
- [ ] The final response reports changes, verification, and remaining risks accurately.

## Source of truth

The full engineering guidance is bundled at `references/csharp-development-best-practices.md`. Read it for detailed principles, examples, the defaults of repositories generated by YDK's `dotnet-webapi-clean` pack (Section 1.1: `net8.0`, Minimal APIs, EF Core with SQLite, repository interfaces, xUnit), and the pull-request checklist (Section 16). Do not invent a project convention where the repository can be inspected; adapt these general standards to the project's target framework and architecture.

## Authorship and license

Written by the YDK owner (yoavarad) and vendored into this repository by the YDK `dotnet-webapi-clean` ignition pack. Released under the MIT License.
