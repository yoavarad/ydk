## v1.7.0 (2026-10-25)

### Feat

- **release**: add ydk release command
- **ignite**: add --only retrofit mode and dotnet upgrade guide
- **task**: add --from batch.yaml to validate-dag and component-coverage
- **cli**: add ydk upgrade (uv tool upgrade + skills re-sync)
- **catalog**: analyzer enforcement in dotnet-webapi-clean templates
- **release**: generate CHANGELOG.md and refresh uv.lock on cz bump
- **skills**: bundle skills in wheel and add ydk skills sync/status
- **catalog**: vendor csharp-development-best-practices skill into dotnet repos
- **review**: dotnet code-review checklist for dotnet-stack projects
- **ignite**: warn when go deps raise the go.mod go directive; add go_version answer
- **ignite**: pass pack init answers via --answer and ignition.init_answers

### Fix

- **release**: roll back failed releases, avoid uv re-sync, allow release/vX.Y.Z
- **verify**: report self-skips as SKIP across bundled plugins
- **verify**: report plugin self-skips as SKIP, not PASS
- **cli**: resolve uv tool bin for upgrade sync and add Windows locked-exe guidance
- **task**: address review on create-batch normalization
- **task**: normalize string-form refs and acceptance in create-batch
- **task**: validate component_refs and story refs in create-batch
- **task**: GitHub check_dependencies ignores non-blocking dependency types
- **todo**: auto-assign matches component_refs intersection then path heuristic
- **task**: resolve spec_refs consistently via project root then spec_location
- **stack-profile**: add dotnet LanguageProfile
- **todo**: record component_refs on TODOs during ignition reconcile
- **catalog**: go-http-service deploy.sh select helm rollback flag by Helm major version
- **task**: normalize epic/story IDs in validate-dag hierarchy check
- **catalog**: go-http-service Dockerfile keeps CA roots out of /etc/ssl/certs
- **verify**: support Go X/... patterns in go-test coverage_packages and warn on zero matches
- **component**: upgrade path for stale .ydk/schemas and warn on undeclared manifest fields
- **todo**: record enclosing Go func/receiver for Go TODO markers
- **ci**: ydk ci init updates unmodified generated files after config changes
- **ignite**: write generated files and init hook scripts with LF on all platforms
- **verify**: go-test race auto default skips -race without cgo/C compiler
- **core**: read/write component manifests and verification cache as UTF-8
- **init**: ensure .gitignore contains .ydk/cache/

## v1.6.0 (2026-10-16)

### Feat

- **catalog**: explicit ext binding and adapter wiring in go-http-service
- **catalog**: pluggable ext technologies for go-http-service
- **catalog**: add env phase (Makefile, POSIX scripts, kind/Strimzi) to go-http-service pack
- **ci**: go stack + make-wrapper GitHub workflow and GitLab CI generation
- **catalog**: container + Helm/OpenShift ops phase for go-http-service pack
- **doctor**: stack-aware tool checks (go, gofmt, helm, kubectl, kind, docker)
- **init**: register go stack and fail cleanly on unknown stacks
- **test**: generate Go table-test stubs from ydk:test manifests
- **catalog**: add go-http-service ignition pack
- **test**: coverage understands ydk:test manifests and Go/sh tests
- **verify**: add go-quality plugins (gofmt, go vet, go test -race coverage gate, vendor check)
- **guard**: configurable source/test patterns in tdd-guard
- **verify**: generic command plugin via manifest command
- **ignite**: per-language post-generation steps for Go packs
- **guard**: tdd-guard-cmd recognizes configurable test commands
- **todo**: per-language TODO markers (Go panic, // comments) in ignition and todo_manager
- **verify**: add helm-lint plugin (helm lint + values.schema.json validation)

### Fix

- **catalog**: drop -cover from go-http-service test script
- **verify**: scope tests-pytest to python test files only
- **test**: hash suffix when Go manifest base is sanitized
- **test**: unique fallback filename for non-ASCII/symbol Go test manifests
- **ignite**: require matching identity for line-only TODO reconcile
- **ignite**: reconcile moved TODO markers on re-ignite
- **test**: preserve _/. namespace dirs in Go test output paths
- **verify**: catch multi-line and any-receiver Go skip calls
- **core**: bound find_project_root walk outside git repos
- **test**: Go stub generate honors stdout default and CamelCase names
- **ignite**: warn on conflicting duplicate env-var definitions
- **test**: scope Go table lookup to the test function; recognize selector ranges and var tables
- **test**: scope table-driven missing-case detection to the case table
- **init**: keep tests/ stage-gated and exempt test/ for go stack
- **init**: drop python-only guard-no-mock-internals from go stack
- **task**: scope Go skip check to added lines, total go coverage, declared PR summaries
- **task**: stack-aware checks in task done, T-FINAL, PR summary and auto-repair
- **test**: harden Go stub generator and align with coverage checker
- **catalog**: close go-http-service review leftovers
- **guard**: derive root from normalized cwd so backslash cwd works on POSIX
- **guard**: configurable stage-gate dirs, Go nolint detection, Windows paths
- **guard**: exempt vendor/ from tdd-guard unconditionally
- **task**: configurable screenshot proof ref patterns (proof.screenshot_ref_patterns)

### Refactor

- **test**: drop unused check_path_collisions helper

## v1.5.1 (2026-10-12)

### Feat

- **verify**: add verification.dotnet.target config key for dotnet plugins
- **ci**: ydk-spec-integrity.yml template with config-driven paths filter
- **ci**: ydk-sync.yml post-merge task and issue sync template
- **ci**: fallback ci.yml running ydk verify run for other stacks (#315)
- **ci**: add ydk-pr-checks.yml template (branch name + cz check) (#305)
- **ci**: add ydk-delete-merged-branch.yml template (#303)
- **ci**: python stack ci.yml template + stack selection
- **ci**: add ydk-pr-body.yml workflow template
- **verify**: add pr-body command sharing task done validation
- **task**: move linked-issue retire logic into package as ydk task sync-issues
- **verify**: repeatable --skip-plugin on verify run
- **task**: block task start on completed epics without a retro
- **task**: add ydk task migrate --to github
- **memory**: add epic retrospectives via --epic, mark retro-done (#248)
- **init**: show ANTHROPIC_API_KEY setup instructions
- **cli**: add ydk task epics/stories list commands
- **task**: deterministic merge driver for YDK bookkeeping files
- **task**: auto-close stories and epics when their last task closes
- **skills**: add gh-issue-to-tasks skill converting GitHub issues into YDK tasks

### Fix

- **verify**: diff changed files against task base_branch merge-base, not main
- **test**: scope hook bash/shim to session fixture, walk up to Git Bash, quote shim path
- **test**: run check_task_complete hook tests with a bash that can read the script on Windows
- **task**: address review - default-branch diff base, hermetic tests, cache
- **task**: resolve repo default branch instead of hardcoded main; add task quick --base
- **verify**: make check_status and issue comment honor skipped plugins
- **verify**: record SKIPPED in report JSON and label skipped in check counts
- **verify**: render skipped plugins as SKIPPED with reason in proof and PR body
- **verify**: harden dotnet.target validation and tests
- **docs**: derive docs generate command list from live Typer app (#368)
- **docs**: make docs generate output deterministic across platforms
- **ci**: pin Python version in generated ci-python.yml
- **ci**: pin Python 3.13 via .python-version
- **github**: task ready excludes in-progress, in-review and blocked tasks
- **task**: task close and sync prune active-task.json entries
- **test**: stop set_config_value mutating shared DEFAULT_CONFIG (#330)
- **verify**: key verification cache on actual plugin input
- **verify**: grade spec-alignment and ai-code-review against task scope
- **github**: guard empty JSON stdout from gh/glab and decode _gh.py as UTF-8
- **cli**: decode text subprocess output as utf-8 with errors=replace
- **test**: use portable commands in test_proof_capture instead of echo
- **verify**: configurable verification.pr_body.ui_exclude globs for pr-body UI detection
- **init**: PR template sections match pr-body-validation
- **component**: validate honors project.spec_location (#316)
- **pr**: point PR body footer link to yoavarad/ydk
- **verify**: annotate every FAIL line in pr-body CI output
- **sync-issues**: emit self-documenting JSON object {retired: [...]}
- **task**: harden sync-issues json errors, dedupe retire logic
- **verify**: list skipped plugins in output and fix pre-push hook call
- **pr-template**: read proof/summary files as utf-8
- **hooks**: make pre-push exit-code propagation explicit
- **hooks**: call ydk CLI from commit-msg/pre-push instead of resolving python
- **rollup**: close stories/epics whose tasks are all done during task sync
- **memory**: mock messages.parse in epic retrospective test
- **verify**: ai-code-review and spec-alignment call anthropic SDK directly
- **llm**: SDK-default credential resolution and typed Claude API error handling
- **task**: stage advance must also treat in-review tasks as still-open
- **task**: advance stage 03->04 after close/sync, not just done
- **core**: route ydk quick through task repository for remote=github
- **github**: persist dependency type and gate readiness on blocking types only
- **github**: archive-done posts comment + archived label instead of overwriting issue body (#236)
- **gh**: unify required-label list and add doctor gh health checks
- **github**: map task list --status to correct gh state/labels
- **github**: parse and persist gates, tdd_stage, session_id; reject unknown frontmatter keys (#234)
- **github**: strict task ID parsing with shared batch-mapping resolver
- **github**: link stories to epics via body field and round-trip epic/story refs
- **core**: harden base_branch normalization and document active-task.json
- **task**: make ydk task sync reconcile QD-* quick tasks
- **verifications**: stop passing temperature to AI review models
- **cli**: create-batch accepts existing task IDs in depends_on
- **ci**: move ty generators exclude to pyproject for Windows
- **verifications**: plugin crash must not report PASS
- **catalog**: resolve inflect and .types unresolved imports in generators
- **catalog**: type method_names as list[str] in unit_test_bodies generator
- **task**: support quick task completion

### Refactor

- **hooks**: drop dead-code defensive branch in pre_push
- **llm**: structured outputs; drop temperature and forced tool_choice

### Perf

- **skills**: cut orchestrate-ready-tasks token usage via per-role model/effort

## v1.3.0 (2026-09-20)

### Feat

- **cli**: hint ydk task close after task done
- **task**: add --delivered-by and --reason flags to task close (#149)
- **catalog**: add dotnet-webapi-clean sample components and pack structural tests (#135)
- **catalog**: add dotnet-webapi-clean test-stub generators (fakes, unit/endpoint/entity tests) (#123)
- **catalog**: add dotnet-webapi-clean baseline solution/project scaffold generators (#120)
- **catalog**: add dotnet-webapi-clean Application-layer generators (#119)
- **dotnet-webapi-clean**: add domain entity and EF Core infra generators (#118)
- **stacks**: wire dotnet stack entry and CLI help text (#117)
- **ignition**: scan .cs files for NotImplementedException TODOs (#112)
- **catalog**: scaffold dotnet-webapi-clean pack metadata and directory skeleton (#111)
- **task**: add bulk task/PR status reconciliation (ydk task sync) (#96)
- **task**: add task close to reconcile status from PR merge state (#86)

### Fix

- **cli**: make task close help tests robust to forced ANSI
- **repositories**: pass explicit --limit to gh issue list and paginate glab lists (#148)
- **core**: normalize base_branch before passing to gh pr create (#140)
- **task**: make active-task.json cleanup robust to _create_pr failure (#139)
- **catalog**: wire generated Program.cs to DI and endpoint registration (#137)
- **task**: scope active-task.json per task_id instead of one global slot (#136)
- **catalog**: align dotnet-webapi-clean generator paths and namespaces (#129)
- **cli**: split comma-separated --depends-on values before parsing (#128)
- **task**: auto-detect merged PRs in local list_ready (#121)
- **io**: use explicit utf-8 encoding for logs, stdout, and subprocess I/O (#97)
- **quickdev**: derive branch prefix from commit type and ASCII-only slugify (#93)
- **task-cmd**: raise gh pr list limit and generalize branch matching in _find_task_pr (#92)
- **pr-template**: restore Closes #task_id reference in generated PR body (#91)
- **task-repo**: read task status from frontmatter, not manifest cache (#85)
- **verifications**: load .env for verification plugins (#79)

## v1.1.0 (2026-08-30)

### Feat

- **verifications**: skip dotnet checks when no .NET files changed (#76)
- **stacks**: add dotnet stack to STACKS registry
- **verifications**: add dotnet-quality bundle plugin
- **verifications**: add dotnet-test plugin
- **verifications**: add dotnet-format plugin
- **verifications**: add dotnet-build plugin
- **cli**: thread changed_files into pre-push verify context
- **verifications**: add dotnet-tdd-guard plugin
- **core**: add canonical LLMProvider abstraction backed by Anthropic
- initial public release of ODK skill

### Fix

- **config**: gitignore .env to prevent accidental secret commits
- **core**: truncate PR body proof output and stop silent PR-create fallback
- **task-lifecycle**: call update_status() in done() to match start()/block()
- **verifications**: pr-body-validation crash on null changed_files
- **core**: remove Bedrock/boto3 references from LLM completion paths
- **core**: resolve task worktree root for verification, not cwd
- **cli**: normalize hook paths for git-bash on Windows
- **verifications**: stop pre-commit hook from failing on clean Windows checkouts
- **core**: pass PR body via --body-file, not inline --body
- **core**: pass PR body via --body-file, not inline --body
- **core**: pass PR body via --body-file, not inline --body
- **core**: run pr-body-validation as a final gate, not the pre-body batch
- **tests**: guard pytest import behind TYPE_CHECKING (ruff TC002)
- **core**: align llm_provider's Anthropic client with api_key_env convention
- **tests**: resolve remaining pre-existing Windows test failures
- **core**: wire api_key_env config, drop dead AWS_PROFILE mutation, fix stale Strands docs
- **hooks**: allow manual PR in stage 01 (no task ID yet)
- **hooks**: allow manual PR in stage 01 (no task ID yet)
- **hooks**: degrade gracefully on Windows and non-Python projects
- **core**: support file locking on Windows in WatchManager

### Refactor

- **config**: delete AwsConfig, migrate remaining Bedrock call sites to LLMProvider
- **cli**: route analyze-complexity through canonical LLM provider
- **core**: replace Bedrock Titan embeddings with local chromadb function
- **verifications**: swap BedrockModel for AnthropicModel
- **core**: replace AWS Bedrock with direct Anthropic API in reviewer subsystem
- rename odk to ydk, oz to yoav (fork of ODK by Oz Altagar)
