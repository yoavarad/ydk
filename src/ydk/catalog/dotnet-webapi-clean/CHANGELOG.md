# Changelog

## 1.1.0 (2026-10-23)

### Added
- Analyzer enforcement in the generated `Directory.Build.props` / `.editorconfig`, mapped from the
  vendored `csharp-development-best-practices` skill (ADR 0003): `AnalysisLevel` `latest-recommended`,
  `EnforceCodeStyleInBuild`, `Microsoft.VisualStudio.Threading.Analyzers`, and warning severities for
  CA1849/VSTHRD002 (sync-over-async), CA2016 (forward `CancellationToken`), CA1848/CA2254 (structured
  logging) and CA2007 (`ConfigureAwait`, Domain/Application/Infrastructure library projects only).
- `YdkAnalyzersAsErrors` MSBuild property (default `true`) gating warnings-as-errors; set it to `false`
  (or pass `-p:YdkAnalyzersAsErrors=false`) to run warn-only while retrofitting an existing codebase.
- `agent_skills` generator vendoring the `csharp-development-best-practices` agent skill into
  `.claude/skills/` of generated repos.

### Changed
- Generated service methods now carry the `Async` suffix (`CreateOrderAsync`, VSTHRD200), service unit
  test names drop underscores (CA1707), and repository implementations use `ConfigureAwait(false)`
  (CA2007) so the skeleton builds clean with analyzers as errors.

## 1.0.0 (2026-09-17)

### Added
- Initial YDK dotnet-webapi-clean catalog release
- Pack metadata (`catalog.yaml`) and generator manifest (`manifest.yaml`) for a Clean-style ASP.NET Core Web API pack
- Directory skeleton for generators, templates, sample components, and tests (populated by downstream tasks)
