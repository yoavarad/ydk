# ODK Configuration Reference

## Overview

All ODK settings live in `.odk/config.yaml` in the project root. The config is Pydantic-validated — unknown fields are rejected, type mismatches produce clear errors.

**All config changes MUST go through the config management script.** Do NOT edit `.odk/config.yaml` directly.

```bash
# View current config
odk config show

# Set a value
odk config set spec_check.timeout 90

# Get a value
odk config get spec_check.model

# Validate config
odk config validate

# Initialize default config
odk init
```

## Full Schema

```yaml
# .odk/config.yaml

# ─── Project ───────────────────────────────────────────
project:
  name: string                    # required — project name
  spec_location: string           # default: "docs/specs"
  adrs_location: string           # default: "docs/adrs"
  research_location: string       # default: "docs/research"
  remote: enum                    # default: "github" — "github" | "gitlab"

# ─── Hooks ─────────────────────────────────────────────
hooks:
  pre_commit:
    enabled: bool                 # default: true — install pre-commit hook
  commit_msg:
    enabled: bool                 # default: true — install commit-msg hook (conventional commits)
  pre_push:
    enabled: bool                 # default: true — install pre-push hook
    spec_check: bool              # default: false — run spec check on push when spec files changed
    task_check: bool              # default: false — validate task graph on push

# ─── Components (Stage 01) ────────────────────────────
components:
  schemas_location: string        # default: ".odk/schemas"
  components_location: string     # default: ".odk/components"
  linker:
    layer_a: bool                 # default: true — deterministic reference validation
    layer_b: bool                 # default: true — LLM unlinked concept scanner

# ─── Spec Quality Check (Stage 01) ────────────────────
ai:
  provider: string                # default: "bedrock" — currently only "bedrock"
  model_tiers:
    smart: string                 # default: "us.anthropic.claude-sonnet-4-20250514-v1:0"
    fast: string                  # default: "us.anthropic.claude-sonnet-4-20250514-v1:0"
    reasoning: string             # default: "us.anthropic.claude-opus-4-6-v1"

# ─── Spec Reviewers ──────────────────────────────
# .odk/spec-reviewers/ — YAML configs for each reviewer (N01-N10),
# copied from src/odk/spec_reviewers/ on `odk init`. Each YAML has:
# id, name, group, threshold, model_tier, tools, system_prompt.

# ─── Spec Quality Check (Stage 01) ────────────────
spec_check:
  timeout: int                    # default: 60 — seconds per reviewer
  global_timeout: int             # default: 120 — seconds total
  concurrency: int                # default: 10 — max parallel Bedrock calls
  results_path: string            # default: ".odk/spec-check-results.json"
  thresholds:
    completeness: int             # default: 8 — score 0-10
    clarity: int                  # default: 8
    architecture: int             # default: 8
    robustness: int               # default: 7
  custom:                         # project-specific criteria
    - id: string                  # required
      rubric: string              # required
      name: string                # required
      prompt: string              # required
      threshold: int              # required — score 0-10

# ─── Task Management (Stage 02) ───────────────────────
task_management:
  dag_validation: bool            # default: true
  coverage_check: bool            # default: true
  coverage_exclude: list[string]  # default: [] — glob patterns to skip in coverage check (e.g. "glossary.md", "scope.md")
  id_format: string               # default: "hash" — "hash" (T-a1b2c3d4) | "sequential" (T-001)
  complexity_threshold: int       # default: 7 — tasks above this score are flagged for splitting
  buffer:
    green_threshold: float        # default: 0.33 — buffer consumed below this = green
    yellow_threshold: float       # default: 0.66 — buffer consumed below this = yellow, above = red

# ─── Scaffolding (Stage 03) ───────────────────────────
scaffolding:
  template_location: string       # default: ".odk/templates"
  generated_header: bool          # default: true

# ─── Memory (Stage 04) ────────────────────────────────
memory:
  embedding_model: string         # default: "cohere.embed-english-v3"
  auto_bootstrap: bool            # default: true
  auto_extract: bool              # default: true
  auto_capture: bool              # default: true
  chroma_path: string             # default: ".odk/memory/chroma"
  research_expiry_days: int       # default: 90
  search_mode: string             # default: "hybrid" — "hybrid" | "vector" | "keyword"
  scoring:
    category_weight: float        # default: 0.50
    provenance_weight: float      # default: 0.15
    recency_weight: float         # default: 0.25
    access_weight: float          # default: 0.10
    recency_half_life_days: int   # default: 30
  contradiction_threshold: float  # default: 0.85 — similarity threshold for contradiction detection
  consolidation_threshold: float  # default: 0.90 — similarity threshold for memory consolidation

# ─── Catalog ──────────────────────────────────────────
catalog:
  backend: string                 # default: "local" — catalog backend ("local")
  local_path: string              # default: "~/.odk/catalog" — path to local catalog store
  chroma_path: string             # default: "~/.odk/catalog/chroma" — ChromaDB index for semantic search

# ─── TODO Management ─────────────────────────────────
todo:
  registry_path: string           # default: ".odk/todos.yaml" — path to TODO registry
  auto_check_on_done: bool        # default: true — check TODO resolution in `odk task done`

# ─── Ignition ─────────────────────────────────────────
ignition:
  hash_store: string              # default: ".odk/ignition-hashes.json" — idempotency hash tracking
  post_checks:
    syntax: bool                  # default: true — run Python syntax check after generation
    circular_imports: bool        # default: true — detect circular imports after generation
    ruff_format: bool             # default: true — run ruff format after generation

# ─── AWS ───────────────────────────────────────────────
aws:
  profile: string                    # default: "" — AWS profile name for Bedrock
  region: string                     # default: "us-east-1"

# ─── Verification ─────────────────────────────────────
verification:
  enabled: list[string]              # default: [] — empty means all plugins run
                                     # Set by --stack during odk init
  cache:
    enabled: bool                    # default: true — content-hash based verification caching
    location: string                 # default: ".odk/cache/verify"

# ─── Execution (Stage 03) ─────────────────────────────
execution:
  max_parallel_agents: int        # default: 5
  task_timeout_minutes: int       # default: 30
  worktree_isolation: bool        # default: true

# ─── Watch System ─────────────────────────────────────
watch:
  poll_interval_seconds: int      # default: 30 — launchd plist polling frequency
  sessions_file: string           # default: ".odk/sessions.yaml" — session tracking file
```

## Field Reference

### project

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | *required* | Project name. Used in display and issue labels. |
| `spec_location` | string | `"docs/specs"` | Path to narrative spec directory, relative to project root. |
| `adrs_location` | string | `"docs/adrs"` | Path to ADR directory. |
| `research_location` | string | `"docs/research"` | Path to research cache. |
| `remote` | `"github"` \| `"gitlab"` | `"github"` | Remote provider. Determines CLI (`gh` vs `glab`). |

### hooks

All hooks enabled by default after `odk init`. Pre-push spec/task checks disabled by default.

| Field | Type | Default | Description |
|---|---|---|---|
| `pre_commit.enabled` | bool | `true` | Install pre-commit hook (lint, types, format). |
| `commit_msg.enabled` | bool | `true` | Install commit-msg hook (conventional commit validation). |
| `pre_push.enabled` | bool | `true` | Install pre-push hook (full verification). |
| `pre_push.spec_check` | bool | `false` | Run spec quality check on push when spec files changed. |
| `pre_push.task_check` | bool | `false` | Validate task graph on push. |

### components

| Field | Type | Default | Description |
|---|---|---|---|
| `schemas_location` | string | `".odk/schemas"` | Path to component schema definitions. |
| `components_location` | string | `".odk/components"` | Path to component manifest files. |
| `linker.layer_a` | bool | `true` | Enable deterministic `[odk:...]` reference validation. |
| `linker.layer_b` | bool | `true` | Enable LLM-based unlinked concept detection. |

### ai

| Field | Type | Default | Description |
|---|---|---|---|
| `provider` | string | `"bedrock"` | AI provider. Currently only "bedrock" is supported. |
| `model_tiers.smart` | string | `"us.anthropic.claude-sonnet-4-20250514-v1:0"` | Model for `smart` tier reviewers. |
| `model_tiers.fast` | string | `"us.anthropic.claude-sonnet-4-20250514-v1:0"` | Model for `fast` tier reviewers. |
| `model_tiers.reasoning` | string | `"us.anthropic.claude-opus-4-6-v1"` | Model for `reasoning` tier (complex analysis). |

### spec_check

| Field | Type | Default | Description |
|---|---|---|---|
| `timeout` | int | `60` | Seconds per reviewer. Timed out = score 0. |
| `global_timeout` | int | `120` | Seconds for entire check. |
| `concurrency` | int | `10` | Max concurrent Bedrock calls (ThreadPoolExecutor). |
| `results_path` | string | `".odk/spec-check-results.json"` | Where to save JSON results. |
| `thresholds.*` | int (0-10) | varies | Minimum score per rubric group. |
| `custom` | list | `[]` | Project-specific quality criteria. |

### task_management

| Field | Type | Default | Description |
|---|---|---|---|
| `dag_validation` | bool | `true` | Validate task dependency graph. |
| `coverage_check` | bool | `true` | Verify spec-to-story coverage. |
| `coverage_exclude` | list[string] | `[]` | Glob patterns for spec sections to skip in coverage check (e.g., `["glossary.md", "scope.md"]`). |
| `id_format` | string | `"hash"` | Task ID format: `"hash"` (T-a1b2c3d4) or `"sequential"` (T-001). |
| `complexity_threshold` | int | `7` | Tasks above this complexity score are flagged for splitting. |
| `buffer.green_threshold` | float | `0.33` | Buffer consumed below this = green (healthy). |
| `buffer.yellow_threshold` | float | `0.66` | Buffer consumed below this = yellow (watch), above = red (at risk). |

### memory

| Field | Type | Default | Description |
|---|---|---|---|
| `embedding_model` | string | `"cohere.embed-english-v3"` | Bedrock embedding model for vector search. |
| `auto_bootstrap` | bool | `true` | Automatically bootstrap context on `odk task start`. |
| `auto_extract` | bool | `true` | Automatically extract learnings on `odk task done`. |
| `auto_capture` | bool | `true` | Capture session for later extraction. |
| `chroma_path` | string | `".odk/memory/chroma"` | ChromaDB storage path. |
| `research_expiry_days` | int | `90` | Days before research files are flagged as stale. |
| `search_mode` | string | `"hybrid"` | Default search mode: hybrid, vector, or keyword. |
| `scoring.*` | float | varies | Memory scoring weights (must sum to 1.0). |
| `scoring.recency_half_life_days` | int | `30` | Half-life for recency decay in days. |
| `contradiction_threshold` | float | `0.85` | Similarity threshold for contradiction detection. |
| `consolidation_threshold` | float | `0.90` | Similarity threshold for memory consolidation. |

### catalog

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | string | `"local"` | Catalog backend. Currently only "local" is supported. |
| `local_path` | string | `"~/.odk/catalog"` | Path to local catalog store. |
| `chroma_path` | string | `"~/.odk/catalog/chroma"` | ChromaDB index for semantic search of catalog items. |

### todo

| Field | Type | Default | Description |
|---|---|---|---|
| `registry_path` | string | `".odk/todos.yaml"` | Path to the TODO registry file, relative to project root. |
| `auto_check_on_done` | bool | `true` | Automatically verify all assigned TODOs are resolved when running `odk task done`. |

### ignition

| Field | Type | Default | Description |
|---|---|---|---|
| `hash_store` | string | `".odk/ignition-hashes.json"` | Path to the idempotency hash store. Tracks file content hashes to skip unchanged files on re-runs. |
| `post_checks.syntax` | bool | `true` | Run Python syntax check on all generated files. |
| `post_checks.circular_imports` | bool | `true` | Detect circular import cycles in generated code. |
| `post_checks.ruff_format` | bool | `true` | Run `ruff format` on generated files. |

### verification

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | list[string] | `[]` | Plugin allowlist. Empty = all plugins run. |
| `cache.enabled` | bool | `true` | Enable content-hash based verification caching. |
| `cache.location` | string | `".odk/cache/verify"` | Where to store verification cache. |

### execution

| Field | Type | Default | Description |
|---|---|---|---|
| `max_parallel_agents` | int | `5` | Max concurrent subagents. |
| `task_timeout_minutes` | int | `30` | Time-box per task. |
| `worktree_isolation` | bool | `true` | Use git worktrees for agent isolation. |

### watch

| Field | Type | Default | Description |
|---|---|---|---|
| `poll_interval_seconds` | int | `30` | How often the launchd plist triggers `odk watch poll`. |
| `sessions_file` | string | `".odk/sessions.yaml"` | Path to the session tracking file. |

## Session Tracking File

Active agent sessions are tracked in `.odk/sessions.yaml`. The watch system reads this file to determine which Claude Code session to resume when a new review comment arrives.

```yaml
# .odk/sessions.yaml
sessions:
  T-a1b2c3d4:
    branch: task/T-a1b2c3d4-order-validation
    pr_number: 47
    worktree: .odk/worktrees/T-a1b2c3d4
    status: in-review          # in-progress | in-review | done
    started_at: "2026-04-28T10:00:00Z"
    last_poll: "2026-04-28T14:30:00Z"
  T-e5f6g7h8:
    branch: task/T-e5f6g7h8-auth-middleware
    pr_number: 48
    worktree: .odk/worktrees/T-e5f6g7h8
    status: in-progress
    started_at: "2026-04-28T11:00:00Z"
    last_poll: null
```

**Fields:**
- `branch` — the git branch for this task
- `pr_number` — the GitHub PR number (set after `odk task done`)
- `worktree` — path to the worktree directory
- `status` — current task status: `in-progress` (being worked on), `in-review` (PR created, awaiting review), `done` (merged)
- `started_at` — ISO 8601 timestamp of when the session started
- `last_poll` — ISO 8601 timestamp of the last time the watch system checked this session's PR for comments

The watch system uses a lock file (`.odk/watch.lock`) to prevent concurrent polls. If a poll is already in progress, subsequent invocations exit immediately.

## Example

```yaml
project:
  name: sample-app
  spec_location: docs/specs
  remote: github

hooks:
  pre_commit:
    enabled: true
  commit_msg:
    enabled: true
  pre_push:
    enabled: true
    spec_check: true

components:
  linker:
    layer_a: true
    layer_b: true

ai:
  provider: bedrock
  model_tiers:
    smart: us.anthropic.claude-sonnet-4-20250514-v1:0
    fast: us.anthropic.claude-sonnet-4-20250514-v1:0
    reasoning: us.anthropic.claude-opus-4-6-v1

spec_check:
  thresholds:
    completeness: 9
    robustness: 8
  custom:
    - id: trading_accuracy
      rubric: domain
      name: "Trading Domain Accuracy"
      prompt: |
        Evaluate trading concept correctness: order lifecycle,
        position tracking, P&L calculation, decimal precision.
      threshold: 8

task_management:
  complexity_threshold: 6
  coverage_exclude:
    - "glossary.md"
    - "scope.md"
  buffer:
    green_threshold: 0.25
    yellow_threshold: 0.50

memory:
  search_mode: hybrid
  scoring:
    recency_half_life_days: 14    # Faster decay for fast-moving project
  contradiction_threshold: 0.80

catalog:
  backend: local
  local_path: ~/.odk/catalog

todo:
  auto_check_on_done: true

ignition:
  post_checks:
    syntax: true
    circular_imports: true
    ruff_format: true

verification:
  cache:
    enabled: true

execution:
  max_parallel_agents: 3
  task_timeout_minutes: 45
```
