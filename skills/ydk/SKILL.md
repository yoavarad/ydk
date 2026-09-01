---
name: ydk
description: Use at the start of any project session, when deciding what to do next, or when working on any development lifecycle concern — specs, brainstorming, task planning, sprints, implementation, code review, or process improvement. This is the master skill for AI-assisted development. Use proactively whenever development work is happening.
---

# YDK — Yoav Development Kit

> Fork notice: YDK is a personal fork of ODK — Oz Development Kit, created by [Oz Altagar](https://www.linkedin.com/in/oz-altagar-0a50861b3/). All credit for the original design and workflow goes to him.

## What is YDK?

YDK is a customized AI-assisted development process skill. It exists because the ecosystem is full of generic tools — OpenSpec, Beads, Taskmaster, CCPM, Superpowers — that each solve 60% of the problem with opinions baked in that don't fit every workflow. After evaluating 20+ tools across memory, scaffolding, context management, and orchestration, the conclusion was clear: it's easier and better to build a customized development process that fits exactly, while stealing the good ideas from what already exists.

YDK is that customized process. It's opinionated about quality (specs first, enforcement gates, adversarial review) but flexible about implementation (use any AI agent, any editor, any language).

## How YDK Works

YDK is organized into **stages** — sequential phases of the development lifecycle. Each stage has:

- **overview.md** — what the stage is, when to enter and exit, how it connects to other stages
- **glossary.md** — stage-specific terminology
- **instructions.md** — the SOP (Standard Operating Procedure) with step-by-step instructions using RFC 2119 constraints (MUST, SHOULD, MAY)
- **aspects/** — sub-topics within the stage (not all stages have aspects)

**When entering a stage, you MUST read overview.md and glossary.md first.** These guide you to the specific instructions and aspects you need.

## The Development Lifecycle

```
IDEA
  │
  ▼
Stage 01: Brainstorming & Design ── produce narratives + component manifests + ADRs
  │
  ▼
Stage 01.5: Ignition ── `ydk ignite` generates runnable skeleton with tracked TODOs
  │
  ▼
Stage 02: Task Management & Planning ── decompose into tasks (business logic only) with TODO assignment
  │
  ▼
Stage 03: Execution ── agents implement TODOs with TDD, `ydk task done` auto-checks resolution
  │   Aspects: scaffolding, context, memory, trust,
  │            cost & speed, observability, integration
  │
  ▼
Stage 04: Learning & Improvement ── capture lessons, improve process
```

## Which Stage Am I In?

**No specs exist yet?**
→ Enter Stage 01: `docs/stages/01-brainstorming-and-design/`

**Existing design docs need translation to YDK format (rewrite)?**
→ Enter Stage 01 in Rewrite mode — set `existing_docs` to the docs path. Skip brainstorming Q&A; translate docs directly into narratives + component manifests.

**Specs exist but no runnable skeleton?**
→ Enter Stage 01.5: `docs/stages/01.5-ignition/`

**Skeleton exists but no epics/stories/tasks?**
→ Enter Stage 02: `docs/stages/02-task-management-and-planning/`

**Tasks exist and you need to implement one?**
→ Enter Stage 03: `docs/stages/03-execution/`

**Sprint complete, need to capture lessons?**
→ Enter Stage 04: `docs/stages/04-learning-and-improvement/`

**Need to modify an existing spec?**
→ Re-enter Stage 01 (Major Feature or Small Change mode)

**Need to propose a change to an existing spec without full re-brainstorm?**
→ Use the spec evolution system: `ydk change propose` (see `cross-cutting/change-management.md`)

**Something went wrong during implementation?**
→ Check Stage 02 instructions (Failure Handling section)

**Not sure where to start?**
→ Run `ydk doctor` — it validates your environment and recommends next steps

**Quick fix or tiny change?**
→ Run `ydk task quick "description"` — fast path for small changes that bypasses the full brainstorming cycle

## Entering a Stage

Every time you enter a stage:

1. **Read `overview.md`** — understand what this stage does and its entry/exit criteria
2. **Read `glossary.md`** — learn the terminology for this stage
3. **Read `instructions.md`** — follow the SOP step by step
4. **Read aspect files as directed** — overview.md tells you which aspects are relevant

Do NOT read all stages at once. Read the one you need right now.

## Universal Principles

These apply across ALL stages:

**UP-1: Every change goes through a PR with explicit human approval.** No direct pushes to main. No auto-merges. No exceptions regardless of size. Code, specs, docs — everything.

**ADRs**: Every significant decision gets an ADR in `docs/adrs/`. Written immediately when the decision is made, not deferred. Include: what was decided, why, alternatives considered.

**project-rules.md**: Conventions, preferences, and domain knowledge in `docs/project-rules.md`. Agent-agnostic — any tool can read it. Updated throughout all stages.

**Spec location**: Every repository MUST have a designated spec directory (default `docs/specs/`). Any folder structure with markdown files works. MUST exist before development begins.

## Component Manifest System

Specs are split into two complementary artifact types:

- **Narratives** — markdown storytelling in `docs/specs/`. Human-readable prose describing the system design, flows, and rationale.
- **Component manifests** — structured YAML files in `.ydk/components/`. Machine-readable definitions of every entity, route, error, contract, requirement, NFR, and external dependency.

Every component manifest has a unique ID following the format `ydk:<type>:<namespace>/<name>`. Examples:
- `ydk:entity:orders/Order`
- `ydk:route:orders/create`
- `ydk:error:orders/insufficient-balance`
- `ydk:contract:orders/place-order`
- `ydk:requirement:orders/decimal-precision`
- `ydk:nfr:system/latency-p95`
- `ydk:external-dep:exchange/binance-rest`

**Always use the full ID. Never use shorthands.**

### Schemas

YDK ships with 13 default schemas in `.ydk/schemas/`. These define the structure of each component type (entity, route, error, contract, requirement, nfr, external-dep, etc.). Projects can add custom schemas. Every schema field has a description. Every manifest MUST include a `$schema` field pointing to its schema — no schema = validation error.

### Linking

Narratives reference components using inline links: `[ydk:entity:orders/Order]`, `[ydk:route:orders/create]`. This creates a traceable connection between prose and structured data.

Two validation layers ensure consistency:
- **Layer A (deterministic linker)** — validates that every `[ydk:...]` reference in narratives points to an existing component manifest. Fast, runs as part of `ydk verify`.
- **Layer B (LLM scanner)** — reads narrative prose and identifies concepts that SHOULD be linked to a component but aren't. Catches when the narrative describes "the Order entity" without linking it. Runs during spec check.

### Tasks and Components

Tasks produced in Stage 02 have two kinds of references:
- **`component_refs`** — which component manifests to implement (e.g., `ydk:entity:orders/Order`, `ydk:route:orders/create`)
- **`spec_refs`** — which narrative files to read for context (e.g., `orders.md`)

### Component CLI

```bash
ydk component list                    # List all component manifests
ydk component show <id>               # Show a specific manifest
ydk component create <type> <id>      # Create a new manifest from schema
ydk component validate                # Validate all manifests against schemas
ydk component list-schemas            # List available schemas
ydk component show-schema <type>      # Show a schema definition
ydk component init-schemas            # Initialize .ydk/schemas/ with defaults
```

## YDK CLI — Complete Reference

YDK provides a CLI tool for automation. Install with `uv pip install -e ydk/` from the repo root.

### Initialization & Config

```bash
ydk init --name <project>              # Initialize .ydk/ config, install hooks (pre-commit, commit-msg, pre-push), install guard hooks in .claude/settings.json
ydk config show|get|set|validate       # Config management
```

### Component Manifests

```bash
ydk component list                     # List all component manifests
ydk component show <id>                # Show a specific manifest
ydk component create <type> <id>       # Create a new manifest from schema
ydk component validate                 # Validate all manifests against schemas
ydk component list-schemas             # List available schemas
ydk component show-schema <type>       # Show a schema definition
ydk component init-schemas             # Initialize .ydk/schemas/ with defaults
```

### Catalog

```bash
ydk catalog search <query>                 # Semantic search for ignition packs and components
ydk catalog install <name>                 # Install a catalog item into the project
ydk catalog list                           # List installed catalog items
ydk catalog info <name>                    # Show details of a catalog item
ydk catalog publish <path>                 # Publish a local item to the catalog (validates: skeleton compiles, imports resolve, tests collect, app starts)
ydk catalog uninstall <name>               # Remove an installed catalog item
```

**Built-in catalog items:**
- `ydk-core-schemas` — default component schemas
- `ydk-default-reviewers` — default spec reviewers (N01-N10)
- `python-quality` — ruff, ty, pytest verification plugins
- `hexagonal-architecture` — hexagonal architecture ignition pack

The catalog uses ChromaDB for semantic search. Local backend at `~/.ydk/catalog/`.

### TODO Management

```bash
ydk todo list                              # List all registered TODOs
ydk todo show <id>                         # Show details of a specific TODO (YDK-TODO-NNN)
ydk todo assign <todo-id> <task-id>        # Link a TODO to a task
ydk todo auto-assign [--apply]             # Match TODOs to tasks by file path
ydk todo assign-batch <mapping>            # Bulk assign from YAML or inline
ydk todo done <todo-id>                    # Mark a TODO as resolved
ydk todo coverage                          # Show TODO resolution coverage
```

TODOs are registered during ignition with `YDK-TODO-NNN` IDs. They track `NotImplementedError` placeholders in generated code. `ydk task done` auto-checks that all assigned TODOs are resolved.

### Ignition

```bash
ydk ignite                                 # Generate runnable skeleton from installed ignition pack + components
ydk ignite --dry-run                       # Preview what would be generated without writing files
ydk ignite --force                         # Regenerate even if hashes match (override idempotency)
ydk ignite --skip-verify                   # Bypass spec verification gate (for inherited/brownfield specs)
```

**What ignition does:**
1. Reads installed ignition pack + YDK component manifests
2. Runs generators as subprocesses (generator pack pattern)
3. Tracks file hashes for idempotency — re-running skips unchanged files
4. Detects developer ownership via GENERATED headers (no GENERATED headers in output — all files developer-owned)
5. Registers TODOs for every `NotImplementedError` placeholder
6. Post-generation: syntax check, circular import detection, ruff format
7. Auto-installs runtime dependencies via `uv`
8. **App MUST start after ignition** (e.g., `uvicorn` serves routes)

**Ignition quality:**
- Routes: `response_model`, typed params, DI injection, service calls, error handling
- Services: DI constructor with port injection, CRUD methods fully implemented
- Schemas: Create/Update/Response per entity with `from_attributes`
- Models: `ForeignKey` + `relationship()` + `back_populates`
- External adapters organized by technology (e.g., `yfinance/`, `alpaca/`, `apscheduler/`)

**Phased ignition (fullstack):**
- `manifest.yaml` supports `phases` — sequential generator groups
- Phases can export artifacts (e.g., `openapi.json`)
- Later phases consume artifacts from earlier phases via `YDK_ARTIFACT_*` env vars
- `pack_ref` references other installed packs (no generator duplication)
- Example: `fullstack-fastapi-nextjs` pack composes backend + frontend + infrastructure phases

### Stage 01 — Spec Quality

```bash
ydk spec verify                        # Run all 10 YAML-based reviewers (N01-N10) in parallel
ydk spec verify --all-files            # Check all spec files (not just git-changed)
ydk spec verify --verbose              # Show per-reviewer timing, cache metrics, and DEBUG logs
ydk spec list-criteria                 # List reviewers and their thresholds
```

**Spec Reviewers**: 10 YAML reviewer configs in `src/ydk/spec_reviewers/` (copied to `.ydk/spec-reviewers/` on `ydk init`). Each reviewer has: id, name, threshold, model_tier, inline Python tools, and a detailed system prompt with examples and scoring rubric. Reviewers run as parallel Bedrock Converse API calls with forced structured output (`toolChoice`). Prompt caching shares spec content across reviewers (90% cost savings after first call).

### Stage 02 — Task Management

```bash
ydk task create-epic                   # Create a new epic
ydk task create-story                  # Create a new story under an epic (supports --component-refs, --spec-refs, --acceptance)
ydk task create                        # Create a task under a story (supports --component-refs, --spec-refs, --acceptance, --dry-run)
ydk task create-batch --from batch.yaml  # Batch create epics/stories/tasks from YAML with two-pass dep resolution
ydk task create-batch --from X --dry-run # Validate batch YAML without creating issues
ydk task validate-dag                  # DAG validation — shows "Critical path (dependency-only)"
ydk task plan-waves --agents N         # Resource-constrained schedule — shows "Critical chain (resource-constrained)"
ydk task coverage [--spec-dir X]       # Spec-to-story coverage check (respects coverage_exclude config)
ydk task component-coverage            # Check every component manifest is referenced by a task
ydk task component-coverage --exclude 'ydk:page:*' --strict  # With exclusion patterns and strict exit code
ydk task analyze-complexity            # LLM scores tasks 1-10, flags tasks needing splits
ydk task add-gate <id> --type <type>   # Add external gate (pr-merged, ci-passed, timer, human)
ydk task ready                         # List all actionable tasks ranked by priority
ydk task list --epic E --story S --status open  # Filter tasks by epic, story, status; grouped by status
ydk task archive-done [--all-done]     # Archive completed tasks for context efficiency
ydk task scaffold-batch                # Generate batch YAML from existing TODOs
```

### Guard System (Real-Time Enforcement)

Guards are a standalone Python script at `.claude/hooks/guard.py`, installed by `ydk init`.

**How guards work:**
- Single script `.claude/hooks/guard.py` reads tool context from stdin via `select()`, exits 2 to block
- Installed by `ydk init` alongside `permissions.allow` in `.claude/settings.json` for non-interactive use
- Works with `--allowedTools` for headless sessions (NOT `--dangerously-skip-permissions`)
- Fire on every tool call — no opt-out, no bypass
- Available guards:
  - `tdd-guard` — blocks source file writes when no test has been written first
  - `guard-no-noqa` — blocks adding `# noqa` or `# type: ignore` comments
  - `guard-no-mock-internals` — blocks mocking internal classes (only mock at boundaries)
  - `guard-no-manual-pr` — blocks `gh pr create` (must use `ydk task done`)
  - `guard-no-proof-tamper` — blocks manual editing of `.ydk/proofs/` files
  - `guard-stage-gate` — blocks stage-inappropriate actions (no code during brainstorming, no planning during execution)

**SubagentStop hook:**
- Blocks session end if `.ydk/active-task.json` exists
- Agent must run `ydk task done` before session can end
- Installed by `ydk init`

**Fail-open behavior:**
- Guards fail open — if stdin is empty, JSON is malformed, or state.json is unreadable, the guard allows the action rather than blocking

**TDD Guard details:**
- State machine: red → green → refactor → red
- Tracks state in `.ydk/tdd-state.json`
- Source dirs: `src/` and `app/`
- Resets on `git commit`
- Writing to source files blocked until a corresponding test file exists and fails

**Stage Gate details:**
- Stage tracked in `.ydk/state.json`
- Auto-advances: `init` → 01, `spec-verify` → 01.5, `ignite` → 02, `task-start` → 03
- CLI preconditions: `ignite` requires schemas + pack + spec-verify; `task-start` requires TODOs

### Stage 03 — Execution

```bash
ydk task start <id>                    # Claim task, create worktree (branch names sanitized: colons/slashes/dots stripped), explore
ydk task start <id> --base <branch>    # Branch from specified base (default: HEAD, not always main)
ydk task start <id> --force            # Restart a stale task (re-create worktree)
ydk task comment <id> "msg"            # Post comment to task issue (replaces plan and progress)
ydk task block <id> --reason X         # Mark task as blocked
ydk task done <id>                     # Verify + create PR + post proof (prints pass/fail per plugin, shows PR URL or first 3 lines of failure)
ydk task done <id> --skip-plugin <name>  # Skip a genuinely failing plugin (verified internally)
ydk task close <id>                    # After PR merge: check merge state via gh, transition status to done (status does NOT auto-update on merge — run this to reconcile, or to recover a task stuck at open/in-review)
ydk task add-subtask <id>              # Create discovered subtask linked to parent
ydk task tdd <id> --stage red|green|refactor  # Set TDD phase on task
ydk task quick "description"           # Fast path for small changes
ydk scaffold list|info|apply|create    # Template scaffolding
ydk verify run --trigger pre-commit    # Run pre-commit verifications
ydk verify run --trigger pre-push      # Run all pre-push verifications
ydk verify run --auto-fix              # Run ruff --fix before checking
ydk verify run --retry N               # Auto-repair loop: retry N times with structured error output
ydk verify run --repair                # Auto-repair: fix issues automatically between retries
ydk verify run --pr <URL>              # Post verification results as PR comment
ydk verify run --no-cache              # Bypass verification cache
ydk verify list                        # List available plugins
ydk verify clear-cache                 # Clear the verification content-hash cache
ydk test generate --from <COMPONENT_ID>  # Generate tests from a component manifest
ydk test coverage                      # Show test coverage report for all components
```

**Multi-session orchestration pattern:**
- For full implementations, use one `claude -p` session per task (not one session for everything)
- Context limits make single-session full implementation impossible for large projects
- Pattern: loop over tasks, each gets its own session
- Use `--allowedTools "Bash,Edit,Write,Read,Grep,Glob"` (NOT `--dangerously-skip-permissions`)

### Stage 04 — Memory

```bash
ydk memory index                       # Index project knowledge into ChromaDB
ydk memory search <query>              # Semantic search
ydk memory search <query> --mode hybrid  # Vector + BM25 keyword + RRF fusion (default)
ydk memory search <query> --depth index|summary|full  # Progressive retrieval depth
ydk memory bootstrap <task-id>         # Assemble context for a task
ydk memory extract <task-id>           # Extract learnings from session transcript
ydk memory retrospective --sprint X    # Sprint-level aggregation
ydk memory audit                       # Comprehensive health audit (stale research, duplicates, procedural reports)
ydk memory record-decision <TOPIC>     # Record topic-keyed decision (append-only, latest-wins)
ydk memory decision-history <TOPIC>    # Show all versions of a decision for a topic
ydk memory consolidate                 # Merge duplicate memories
```

### Spec Evolution

```bash
ydk change propose                     # Create a delta spec in docs/changes/
ydk change list                        # List proposed changes
ydk change status <id>                 # Check change status
ydk change archive <id>                # Move completed change to docs/changes/archive/
ydk change diff <id>                   # Show what the change modifies
```

### Watch System

```bash
ydk watch install                      # Install macOS launchd plist, polls every 30 seconds
ydk watch poll                         # Check GitHub PRs for new review comments, react 👀, trigger Claude Code session
ydk watch uninstall                    # Remove the launchd plist
ydk watch status                       # Show installed state, last poll time, active sessions
```

### PR Review Feedback

```bash
ydk task review-comments <id>          # Fetch PR review comments for a task
```

### Visual Companion

```bash
ydk visual start                       # Start browser-based mockup server
ydk visual stop                        # Stop the server
ydk visual push                        # Push current mockup state
ydk visual feedback                    # Collect feedback on mockups
ydk visual screenshot                  # Capture mockup screenshot
ydk visual list                        # List all mockup sessions
```

## Glossary of Key Concepts

### Component Manifest
A structured YAML file in `.ydk/components/` that defines a single entity, route, error, contract, requirement, NFR, or external dependency. Has a unique `ydk:<type>:<namespace>/<name>` ID and a `$schema` reference.

### Narrative
A markdown storytelling file in `docs/specs/` that describes system design in prose. References component manifests via `[ydk:...]` links.

### Layer A (Deterministic Linker)
Validates that all `[ydk:...]` references in narratives point to existing component manifests. Fast, deterministic.

### Layer B (LLM Scanner)
Reads narrative prose and identifies concepts that should be linked to components but aren't. AI-based, runs during spec check.

### Spec Reviewer
A YAML config file in `src/ydk/spec_reviewers/` (or `.ydk/spec-reviewers/` per project) that defines one quality criterion. Has: id (N01-N10), name, group, threshold, model_tier (`smart`, `fast`, or `reasoning`), inline Python tools, and a system prompt with examples and scoring rubric. Runs via Bedrock Converse API with forced structured output.

### Model Tier
A logical name (`smart`, `fast`, `reasoning`) mapped to a Bedrock model ID in `ai.model_tiers` config. Both `smart` and `fast` default to Sonnet 4; `reasoning` defaults to Opus. Reviewers declare a tier, not a model ID.

### Prompt Caching
Bedrock prompt caching that shares spec content across all reviewer calls. The first reviewer pays full input cost; remaining reviewers hit the cache for ~90% cost savings on the spec portion.

### Proof Capture
Deterministic capture of verification command output to `.ydk/proofs/<task-id>/`. Uses full verification report (all plugins) — each plugin's output saved to `.ydk/proofs/<task>/plugins/<name>.txt`. PR body assembled from all plugin results. Screenshot proof required for UI tasks (routes/pages `component_refs`).

### Structured Logging
Rotating file log at `~/.ydk/logs/ydk.log` (10MB, 5 backups). Per-reviewer timing in spec verify output. `--verbose` flag shows DEBUG-level logs.

### Guard System
A standalone Python script at `.claude/hooks/guard.py` that fires on every Claude Code tool call (Edit/Write/Bash) via PreToolUse hooks in `.claude/settings.json`. Uses `select()` for stdin reading, exits 2 to block. Guards block violations before they happen — no remediation needed. Fails open if stdin is empty or JSON is malformed. Installed by `ydk init` alongside `permissions.allow` for non-interactive use. Guards include: `tdd-guard`, `guard-no-noqa`, `guard-no-mock-internals`, `guard-no-manual-pr`, `guard-no-proof-tamper`, `guard-stage-gate`.

### Gate
An external blocking condition on a task. Types: `pr-merged` (waits for a PR), `ci-passed` (waits for CI), `timer` (waits for a time), `human` (waits for human action). Added via `ydk task add-gate`.

### component_refs vs spec_refs
Tasks have two kinds of references: `component_refs` point to component manifests (what to implement), `spec_refs` point to whole narrative files (what to read for context).

### Batch YAML
A YAML file with top-level `epics:`, `stories:`, and `tasks:` sections for `ydk task create-batch`. Each entity has an `id` field used for cross-referencing within the file. Dependencies use placeholder IDs that are resolved to real GitHub issue numbers after all issues are created (two-pass resolution). Labels are auto-created before batch creation.

### Dry-Run
The `--dry-run` flag on `ydk task create`, `ydk task create-story`, and `ydk task create-batch` validates input and shows what would be created without calling the API. Useful for checking batch YAML correctness before committing to issue creation.

### Component Coverage
`ydk task component-coverage` checks that every component manifest in `.ydk/components/` is referenced by at least one task's `component_refs`. Supports `--exclude` glob patterns (e.g., `ydk:page:*`) and `--strict` mode (exit code 1 on uncovered components).

### Coverage Exclusions
The `task_management.coverage_exclude` config field lists glob patterns for spec sections to skip during `ydk task coverage`. Used to exclude reference docs (glossary, scope, etc.) that don't need story coverage.

### Dependency Types
8 types of task dependencies: `blocks`, `validates`, `caused-by`, `conditional-blocks`, `waits-for`, `discovered-from`, `supersedes`, `related`. Only `blocks`, `conditional-blocks`, and `waits-for` create execution edges in the DAG.

### Hash-Based Task IDs
Task IDs use format `T-a1b2c3d4` (hash-based) instead of sequential `T-001`. Collision-free for parallel agent creation.

### Complexity Score
LLM-scored value 1-10 for each task. Tasks scoring above threshold are flagged for splitting. Run via `ydk task analyze-complexity`.

### Buffer Zone
Sprint health tracking using critical chain buffer management. Shows green (on track), yellow (consuming buffer), red (buffer exhausted).

### Compaction
Compressing completed task data to reduce context window usage. `ydk task archive-done` compresses individual done tasks; `--all-done` compresses all completed tasks.

### Verification Cache
Content-hash based caching of verification results. If code hasn't changed, verifications aren't re-run. Bypass with `--no-cache`, clear with `ydk verify clear-cache`.

### Auto-Repair Loop
`ydk verify run --retry N --repair` automatically retries failed verifications, applying fixes between retries using structured error output.

### Spec Evolution
OpenSpec-inspired delta spec system. `ydk change propose` creates proposed modifications in `docs/changes/`. Completed changes archived to `docs/changes/archive/`.

### Visual Companion
Browser-based mockup and annotation tool. `ydk visual start/stop/push/feedback/screenshot/list` for UI design collaboration.

### Quick Dev
Fast path for small changes: `ydk task quick "description"` bypasses full brainstorming for trivial modifications.

### Watch System
Background polling daemon that monitors GitHub PRs for new review comments. `ydk watch install` creates a macOS launchd plist that runs `ydk watch poll` every 30 seconds. When a new comment is detected, the watch reacts with 👀 and resumes a Claude Code session to address the feedback. Uses a lock file to prevent concurrent polls.

### Session Tracking
Active agent sessions are recorded in `.ydk/sessions.yaml`. Each entry maps a task ID to its branch, PR number, worktree path, and session state. The watch system uses this file to resume the correct session when new review comments arrive.

### Agent Reply Marker
The HTML comment `<!-- ydk-agent-reply -->` placed on the first line of every agent reply to a PR review comment. The watch system filters out comments starting with this marker so it does not re-trigger on the agent's own replies, preventing infinite feedback loops.

### Scoring & Decay (Memory)
Memories are ranked by a 4-factor score: category weight (0.50), provenance (0.15), recency (0.25), access frequency (0.10). Recency decays with a 30-day half-life.

### Hybrid Search (Memory)
Default search mode combining vector similarity, BM25 keyword matching, and Reciprocal Rank Fusion (RRF) for result merging.

### Negative Knowledge
Memories with extraction type `abandoned` — approaches that were tried and rejected. Prevents future agents from repeating failed attempts.

### Provenance
Source tracking on memories: `source_type` (user-stated, llm-extracted, agent-discovered, verified) + `verified` flag. Higher provenance = higher score.

### Contradiction Detection
When a new memory contradicts an existing one, the old memory is auto-invalidated. Prevents stale knowledge from persisting.

### Progressive Retrieval
Search with `depth=index|summary|full` controls how much detail is returned. Use `get_memory_details(ids)` for full content of specific memories.

### Temporal Validity
Memories can have `valid_from` and `valid_until` timestamps. Expired memories are auto-filtered from search results.

### Procedural Memory
Tracks which prompts and approaches were effective. `ydk memory audit` includes procedural effectiveness analysis.

### Catalog
A searchable registry of ignition packs, component schemas, verification plugins, and other reusable YDK components. Uses ChromaDB for semantic search. Local backend at `~/.ydk/catalog/`. Ships with 4 built-in items: `ydk-core-schemas`, `ydk-default-reviewers`, `python-quality`, `hexagonal-architecture`.

### Ignition Pack
A catalog item that contains generators for producing a runnable project skeleton from component manifests. Installed via `ydk catalog install`. Each pack defines which component types it can consume and what code it generates.

### TODO (YDK-TODO-NNN)
A tracked placeholder registered during ignition for every `NotImplementedError` in generated code. Each TODO has a unique `YDK-TODO-NNN` ID. TODOs are assigned to tasks via `ydk todo assign` and auto-checked for resolution by `ydk task done`.

### Ignition
The process of generating a runnable project skeleton from an installed ignition pack and component manifests. Run via `ydk ignite`. Produces compilable/runnable code with `NotImplementedError` placeholders for business logic, registered as tracked TODOs.

### Stage 1.5
The ignition stage between brainstorming (Stage 01) and task management (Stage 02). After specs are validated, `ydk ignite` generates a runnable skeleton. Tasks in Stage 02 then focus exclusively on business logic — boilerplate is already generated.

## Cross-Cutting Concerns

Apply across all stages. Read when relevant:

| Concern | File |
|---|---|
| Change management & spec evolution | `docs/cross-cutting/change-management.md` |
| Configuration reference | `docs/cross-cutting/config.md` |
| Research methodology | `docs/cross-cutting/research-methodology.md` |
| Brownfield pipeline | `docs/cross-cutting/brownfield-pipeline.md` |
| Testing strategy | `docs/cross-cutting/testing-strategy.md` |

## Quick Start

1. **New project**: Enter Stage 01 → `ydk catalog search` for packs → brainstorm specs + produce component manifests → run spec-check → PR
2. **Specs ready**: Enter Stage 01.5 → `ydk ignite` → verify skeleton runs + app starts → review TODOs
3. **Skeleton ready**: Enter Stage 02 → decompose with component_refs → `ydk todo assign` TODOs to tasks → validate DAG → plan sprint
4. **Task assigned**: Enter Stage 03 → implement TODOs with TDD (guards auto-enforced) → `ydk task done` shows pass/fail per plugin → PR → review → merge → `ydk task close <id>` to reconcile status to done
5. **Sprint done**: Enter Stage 04 → capture lessons → update ADRs/rules
6. **Quick fix**: `ydk task quick "description"` → fast path for small changes
7. **Not sure**: `ydk doctor` → check environment health and get next steps

**Note:** `ydk init` auto-installs guard hooks in `.claude/settings.json` — TDD enforcement, stage gates, and code quality guards are active from the start. No opt-in required.

## Generator Quality (v0.46+)

The `python-fastapi-hexagonal` pack generates **70% working code** matching production-generator quality:

- **Routes**: `response_model=`, typed params, DI injection via `Depends()`, service delegation, error handling. List endpoints use `list[Response]`. Only complex custom logic is TODO.
- **Services**: DI constructors with port injection, CRUD methods fully implemented (get/list/create/update/delete delegate to repo). Port services receive adapter injection.
- **Schemas**: Create/Update/Response per entity with `from_attributes=True`.
- **Models**: `ForeignKey()` + `relationship()` + `back_populates` from entity manifests.
- **Adapters**: External service adapters by technology (yfinance/, alpaca/, apscheduler/, etc.) with port interface inheritance.
- **DI Wiring**: Service factories inject repos and adapters. Port service factories inject the external adapter.
- **Tests**: Contract tests (Protocol conformance), unit test stubs, integration test stubs, fakes.

**After ignition, the app MUST start** (`uvicorn app.main:app`). This is verified by the publishing gate integration test.
