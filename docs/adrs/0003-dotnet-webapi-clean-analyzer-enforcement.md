# dotnet-webapi-clean pack: analyzer enforcement and the YdkAnalyzersAsErrors toggle

**Status:** accepted

The `csharp-development-best-practices` skill vendored into generated repos says its rules should be enforced by analyzers and CI rather than by review alone. We map the mechanically checkable guardrails (§3 logging, §4 async, §5 nullability, §15 tooling) into the generated `Directory.Build.props` and `.editorconfig`. `<Nullable>enable</Nullable>` was already generated and stays. We add `AnalysisLevel` `latest-recommended`, `EnableNETAnalyzers`, `EnforceCodeStyleInBuild`, a `Microsoft.VisualStudio.Threading.Analyzers` package reference (`PrivateAssets=all`), and `warning` severities for CA1849/VSTHRD002 (sync-over-async), CA2016 (forward `CancellationToken`), CA1848/CA2254 (structured logging) and CA2007 (`ConfigureAwait`). Severities live in `.editorconfig`, the MSBuild switches in `Directory.Build.props`. Warnings become build errors through one MSBuild property, `YdkAnalyzersAsErrors`, which defaults to `true` for new repos. Only the exact value `true` enables it. It can be set to `false` (in `Directory.Build.props`, or per build with `-p:YdkAnalyzersAsErrors=false`) so a retrofit can start warn-only and tighten later.

## Decisions

- **CA2007 only in library projects.** The skill (§4.9) asks for `ConfigureAwait(false)` in reusable library code but not mechanically in ASP.NET Core application code. `Domain`, `Application` and `Infrastructure` are class libraries, so a later `.editorconfig` section `[{Domain,Application,Infrastructure}/**.cs]` raises CA2007 to `warning` there; the global `[*.cs]` section sets it to `none`, which covers the `Api` host and the xUnit test project (where xUnit1030 discourages `ConfigureAwait(false)`).
- **One toggle, not per-rule overrides.** `YdkAnalyzersAsErrors=true` sets both `TreatWarningsAsErrors` and `CodeAnalysisTreatWarningsAsErrors`. There is no `NoWarn` or `WarningsNotAsErrors` list.
- **Fix generator output, never suppress.** Turning analyzers on surfaced VSTHRD200, CA2007 and CA1707 in the generated sample. We changed the generators instead of silencing rules: service methods carry the `Async` suffix, repository implementations call `ConfigureAwait(false)`, and service unit-test names drop underscores.
- **Pack version 1.1.0 (minor).** Regenerating `Directory.Build.props` in an existing repo turns on warnings-as-errors. The toggle is the documented escape hatch for that case.

## Considered options

- **Plain `TreatWarningsAsErrors` with no toggle**: simpler, but it blocks any incremental retrofit of an existing codebase.
- **`AnalysisLevel` `latest-all`**: rejected as the default because it enables many style and design rules that are not in the skill, which makes the noise worse for teams adopting the analyzers.
- **CA2007 everywhere**: contradicts skill §4.9 and xUnit guidance for the host and test projects.

## Consequences

- The ignited sample builds clean with analyzers as errors, and `dotnet format --verify-no-changes` passes. `tests/integration/test_dotnet_webapi_clean_e2e.py::TestAnalyzerEnforcement` covers this and shows the toggle switching a CA2007 violation between error and warning.
- `AnalysisLevel` `latest` follows the installed SDK, so a newer SDK can bring in new recommended rules. The e2e test is what detects that.
