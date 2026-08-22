# Upstream recommendation: .NET/C# support in YDK

Author context: built while adding project-local `.ydk/verifications/{dotnet-build,dotnet-format,dotnet-test}`
to ole-extractor (a C#/.NET project). This doc distills what should move into the main `ydk`
repo (`C:\Users\yoava\Projects\ydk`) so the next .NET project doesn't reinvent this.

Audience: whoever picks up the upstream work. Skip the preamble, go straight to diffs.

## 1. Ship three global plugins, not one bundle

Mirror `verifications/lint-ruff`, `types-ty`, `python-quality` (bundle = union of the two).
Do the same for .NET:

- `src/ydk/verifications/dotnet-build/` — `dotnet build`, trigger `git:pre-push`
- `src/ydk/verifications/dotnet-format/` — `dotnet format --verify-no-changes`, trigger `git:pre-push`
- `src/ydk/verifications/dotnet-test/` — `dotnet test`, trigger `git:pre-push`

All three ended up on `git:pre-push`, not `git:pre-commit` — see §7. This was corrected after
testing against a real SDK install; an earlier draft had build/format on pre-commit, which turned
out to be actively harmful (see below).
- `src/ydk/verifications/dotnet-quality/` — thin bundle plugin that runs build+format (test stays
  separate since it's pre-push and slower, matching how `python-quality` excludes `tests-pytest`)

Port the three `check.py`/`manifest.yaml` pairs from ole-extractor's `.ydk/verifications/` almost
verbatim — they're already fail-open and tested against a real project. Don't try to collapse them
into one script with subcommands; the plugin-loading contract has no shared-library mechanism
(each plugin dir is loaded standalone), so `python-quality`-style duplication across `dotnet-build`/
`dotnet-format`/`dotnet-test` is the existing convention, not a shortcut.

**Effort: quick win.** This is copy-paste-and-generalize, half a day including tests.

## 2. Add a `dotnet` stack to `stacks.py`

```python
"dotnet": {
    "verifications": [
        "dotnet-build",
        "dotnet-format",
        "dotnet-test",
    ],
    # no "templates" entry yet — no catalog scaffold exists to point at.
    # add one only once a reference C# project template exists.
},
```

No `config_overrides` needed initially — nothing in `config.yaml` today is .NET-specific
(no `spec_check.thresholds` tuning was needed for ole-extractor). Leave the key out rather than
add a speculative override; add overrides later if a real need shows up (e.g. dotnet builds take
longer than Python lint, so a project might want to loosen `execution.task_timeout_minutes`, but
that's a global execution setting, not a stack concern).

**Effort: quick win.** ~10 lines, follows the existing `STACKS` dict pattern exactly.

## 3. Centralize the SDK-vs-muxer detection — this is the real gotcha

`dotnet --list-sdks` returning an **empty but zero-exit-code** result is the crux of making these
plugins fail open correctly on Windows. `shutil.which("dotnet")` alone is not enough:

- Windows can ship a bare `dotnet.exe` muxer (via `dotnet` app-execution-alias-like install-on-first-use,
  or a leftover VS Build Tools install) with **no SDK underneath it**.
  `dotnet build`/`test`/`format` then fail with `No .NET SDKs were found.` — a real failure, not
  the "no .NET project here" signal these plugins want to fail open on.
- The check is: run `dotnet --list-sdks` (15s timeout), and treat it as "no SDK" unless
  `returncode == 0 and stdout.strip()` is non-empty. Both conditions matter — a non-zero exit with
  output, or a zero exit with empty output, both mean "no usable SDK."

This exact ~15-line `_has_sdk()` helper is duplicated verbatim across all three ole-extractor
plugins today. If YDK gains a second Windows-specific runtime-detection need in the future, this is
the first candidate for a shared internal utility (e.g. `ydk.core.dotnet_probe` used only by these
three check.py files at codegen/copy time, not a plugin-loadable dependency) — but don't build that
abstraction speculatively for a single consumer. Worth a code comment pointing future implementers
at this exact failure mode either way; it's easy to miss in a fresh implementation and easy to
"fix" wrong (e.g. by just checking `shutil.which("dotnet")`, which is what most naive implementations
do and what silently produces false failures on machines with the bare muxer, which is common in
CI base images and OEM Windows installs).

**Effort: no extra effort if plugins are ported as-is (item 1) — flagging so nobody "cleans up"
the duplication into a `shutil.which`-only check during a refactor.**

## 4. Target-discovery edge cases actually hit (and the fix already applied)

Discovery logic (shared shape across all three plugins): prefer `.sln`/`.slnx`, else fall back to
`.csproj`, always skipping `bin/obj/.git/.ydk/.vs/node_modules`.

- **Multiple `.sln`/`.csproj` matches — non-determinism.** `Path.rglob()` order is filesystem-
  dependent, not alphabetical. On first pass this meant re-running the same plugin against the
  same tree could pick a different `.sln` file each time (order flips across some Windows/NTFS
  directory-entry orderings). Fixed in ole-extractor's copies by wrapping every candidate list in
  `sorted(...)` before indexing `[0]`. **Port this fix upstream — don't reintroduce it.** This
  matters more than it looks: `VerificationCache` hashes source files, not the resolved target
  path, so a flaky target choice can produce cache hits/misses that don't correlate with what
  actually got built.
- **No `.sln` at all, multiple loose `.csproj` files (monorepo-style).** Current heuristic — first
  `.csproj` alphabetically — is a coin flip in a real monorepo with several independent projects.
  A general implementation should probably: (a) support an explicit override in
  `.ydk/config.yaml` (`dotnet.build_target: path/to/x.csproj`), and (b) fall back to building
  *all* discovered `.csproj` files rather than just the first, when there's no `.sln` to say
  "these belong together." ole-extractor didn't need this (single `.sln`), so it's untested territory
  — flag as a design decision for whoever implements it generally, not a copy-paste fix.
- **Test-project naming beyond `*Test*`/`*Tests*`.** The `dotnet-test` heuristic (`"Test" in stem
  or "Tests" in stem`) catches xUnit's common `Foo.Tests.csproj` convention fine (substring match).
  It will also produce false positives on any non-test project whose name happens to contain
  "Test" (e.g. a hypothetical `LoadTestHarness.csproj` that isn't itself a test project but a
  runner). Not hit in ole-extractor (only one test project), but a general implementation serving
  arbitrary repos should probably also check for a `<IsTestProject>true</IsTestProject>` or
  `Microsoft.NET.Test.Sdk` package reference inside the `.csproj` XML rather than relying purely on
  filename — more robust, moderate extra parsing cost.
- **`.slnx` (new XML solution format) is NOT supported by the .NET 8 SDK CLI — confirmed, not
  theoretical.** Original draft of this doc (written before a real SDK was installed) guessed at
  this and suggested probing `dotnet --version` and warning. After installing the actual .NET 8
  SDK (8.0.424) and running against ole-extractor's real `ExtractorOle.slnx`, the failure mode is
  worse than a warning would fix: `dotnet build/format/test <file>.slnx` fails immediately with
  `MSB4068: The element <Solution> is unrecognized, or not supported in this context` — a raw
  MSBuild parse error, not a clean "unsupported format" message, and it fires before any real
  build/format/test work happens. The fix applied: **don't attempt `.slnx` at all** — target
  discovery now only considers `.sln`, falling through to `.csproj` if no `.sln` exists. No
  version-probing needed; `.slnx` is simply excluded from every discovery function's glob patterns.
  Revisit only once a target SDK version with confirmed `.slnx` CLI support is common (not the case
  as of .NET 8/9 GA at time of writing).

**Effort: moderate.** The sorted-list fix is free (already done, just port it). The
multi-csproj-without-sln and XML-based test-project detection are each a half-day of real design +
test-writing against synthetic repo layouts, not urgent for a single-solution project like
ole-extractor but real for anyone with a monorepo.

## 5. `tdd-guard` is Python-only — known gap, not fixed here

`src/ydk/verifications/tdd-guard/check.py` hardcodes:
- test-file detection: `basename.startswith("test_") or basename.endswith("_test.py")`
- guarded source prefixes: `("src/", "app/")`
- always-allowed prefixes: `("tests/", "docs/", ".ydk/", ".claude/", "scripts/")`

None of this matches C# conventions: xUnit/NUnit/MSTest tests are typically `FooTests.cs` (suffix,
not prefix, no underscore) living in a `Tests/` project (capital T, sibling to `src/`, not nested
under it), often building to `*.Tests.csproj`. As shipped, `tdd-guard` either won't recognize C#
test files at all (if enabled on a dotnet stack, it would block every source edit thinking no test
was written) or has to stay unlisted in the `dotnet` stack's `verifications` — which is what item 2
above already does implicitly by omitting `tdd-guard`.

**Not implemented as part of this pass** — flagging only. If someone wants TDD-guard on .NET
projects, it needs: a language-pluggable file-pattern config (test suffix vs. prefix, source vs.
test directory names) rather than another hardcoded Python hardcoding pass. That's a real design
question (config-driven patterns vs. a `language: dotnet` variant plugin) worth its own ticket,
not a bolt-on.

**Effort: bigger lift.** Touches the guard's core matching logic and needs a config schema
decision, not just new constants.

**Update (ydk-side review):** this repo already ships `python-tdd-guard` as a separate plugin from
the language-agnostic `tdd-guard` (both under `src/ydk/verifications/`), proving the "variant
plugin per language" shape works today with zero core changes — same pattern `python-quality` uses
for bundling. A `dotnet-tdd-guard` plugin (suffix `*Tests.cs`, `Tests/` project dir) can ship the
same way `python-tdd-guard` did. The config-driven abstraction this section calls for is still
worth doing once a third language shows up (rule of three) — not before.

## 7. Whole-target build/test checks can permanently block ALL pushes on a pre-existing broken baseline

This is a generalizable structural gap, not a .NET-specific one, but it was discovered here and
should be flagged upstream regardless of what a `dotnet` stack ships with.

`ydk verify run`'s `context` dict for a `pre-commit`/`pre-push` trigger never includes
`changed_files` unless a caller (e.g. `ydk task done`, or a `--name`-scoped manual run in some
paths) explicitly threads it through — see `src/ydk/cli/verify_cmd.py`'s `run()`: the default
`context` is just `{"project_root": ...}`. Plugins like `lint-ruff`/`tests-pytest` cope by falling
back to scanning `src/`/`app/`/`tests/` when `changed_files` is absent, which is harmless for a
per-file linter. It is **not** harmless for a whole-solution build/test check: `dotnet build` (and
`format`/`test`) always evaluates the *entire* discovered target, regardless of what the current
commit/push actually touched.

Concretely, in ole-extractor: `ExtractorOLE.csproj` currently targets `net10.0` (pre-existing,
predates this work — a separate task, `T-eeb6684b`, exists specifically to downgrade it to
`net8.0`). Once `dotnet-build`/`dotnet-format` were wired to a real SDK, they correctly, and
*unconditionally*, fail on **every single push**, including ones that touch nothing but this very
`.ydk/verifications/` plugin work — because the check has no concept of "this failure predates my
change." Placing the checks on `git:pre-push` instead of `git:pre-commit` (§1) reduces how often
this bites (local iteration during TDD isn't blocked), but doesn't eliminate it — it still blocks
every *push* project-wide until the baseline is fixed, unrelated work included. In ole-extractor's
case this was worked around the same way an earlier, unrelated gap was already worked around in
this exact repo (`.ydk/hooks/pre-push`'s `IGNORE_LIST`, previously used for `pr-body-validation`
and `tests`): added `dotnet-build`/`dotnet-format` to that list with a comment to remove once
`T-eeb6684b` merges. That's a per-project, hand-maintained, easy-to-forget patch — not a real fix.

A real fix belongs in `ydk-core`, and is one of two shapes:
- **Baseline-diffing**: cache the verification failure output/hash from the last known-good state
  on the target branch, and only treat a check as newly-failing (blocking) if the failure differs
  from a failure already present on the branch being pushed *to* (i.e. "you didn't make it worse").
  This is the more correct fix but nontrivial — needs a notion of "the failure that already existed
  upstream" per plugin.
- **`changed_files`-aware plugins for pre-push, not just pre-commit**: thread `changed_files` (diff
  against the push target) into the `pre-push` trigger context too, and have `dotnet-build`/
  `dotnet-format`/`dotnet-test` skip (not fail) when no `.cs`/`.csproj`/`.sln` file is among the
  changed files. Simpler than baseline-diffing, but weaker: it means a push that touches zero C#
  files sails through even if the solution is currently unbuildable for unrelated reasons — probably
  an acceptable tradeoff for a fast local gate, less acceptable as the *only* gate before merge (a
  separate CI-level "always build everything" check would still be needed for that).

**Effort: real design work, not a quick win** — this is a `ydk-core` verifier-contract change, not
a per-plugin fix. Worth a dedicated ticket; don't bundle into the `dotnet` stack PR.

## 8. Priority summary

| Item | Effort | Priority |
|---|---|---|
| Port 3 plugins as global verifications (§1) | quick win (~half day) | Do first |
| `dotnet` stack entry (§2) | quick win (~1 hour) | Do with §1 |
| Keep/port the `sorted()` determinism fix (§4) | free (already written) | Do with §1, don't skip |
| Document the muxer-vs-SDK gotcha inline (§3) | free | Do with §1 |
| Exclude `.slnx` from target discovery entirely (§4) | free (already written) | Do with §1, don't skip |
| `dotnet-tdd-guard` plugin (§5) | small (mirrors `python-tdd-guard`) | Do with §1 |
| Monorepo multi-csproj / XML-based test detection (§4) | moderate (~1 day) | Later, when a real multi-project repo needs it |
| Baseline-diffing or `changed_files`-on-pre-push for whole-target checks (§7) | real design work | Own ticket — affects every compiled-language stack, not just .NET |

## Source material

The three plugins referenced throughout live in `ole-extractor` at `.ydk/verifications/dotnet-build/`,
`.ydk/verifications/dotnet-format/`, `.ydk/verifications/dotnet-test/` — copy from there, not from
scratch.

Ignition pack / catalog template / component-schema mapping for full dotnet codegen support is
explicitly out of scope for this doc — needs its own ADR once a reference C# project shape is
chosen. Don't block the verification-plugin work on it.
