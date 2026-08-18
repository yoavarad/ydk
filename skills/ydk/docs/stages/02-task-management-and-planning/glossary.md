# Stage 02: Task Management & Planning — Glossary

## Release

A shipped milestone tied to a git tag. Groups completed epics. Represented as a GitHub/GitLab Milestone with a target date.

## Epic

A large initiative grouping related stories. Represented as a GitHub/GitLab Issue. Example: "Order Management."
DO NOT USE: feature set, initiative, workstream.

## Story

A deliverable piece of user value with acceptance criteria. GitHub/GitLab Issue labeled `story`. References spec sections by `filename.md#section`.
DO NOT USE: user story, requirement, feature.

## Task

The atomic unit of work. One agent, one session, one PR. GitHub/GitLab Issue labeled `task`. Links to parent story. Has `component_refs` (what to implement) and `spec_refs` (what narrative to read). ID format depends on backend (see **Task ID Format** below).
DO NOT USE: subtask, ticket, work item.

## Task ID Format

Task ID format depends on the configured backend:

- **Local backend** (`remote: local`): IDs are sequential `T-NNN` (e.g., `T-001`, `T-042`). The numeric portion is auto-incremented from the manifest.
- **GitHub backend** (`remote: github`): IDs are GitHub issue numbers (e.g., `42`, `#684`). These are the native issue numbers assigned by GitHub.

The DAG validator, dependency references, and all CLI commands work with both formats. When referencing dependencies, use the ID format matching your backend.

## component_refs

A task field listing which component manifests to implement. Example: `[ydk:entity:orders/Order, ydk:route:orders/create]`. These tell the agent WHAT to build.

## spec_refs

A task field listing which narrative files to read for context. Example: `[orders.md]`. These are whole file paths — not section anchors. They tell the agent WHERE to find the design rationale.

## Sprint

A time-boxed iteration with a goal, containing stories from the backlog. Represented as a GitHub/GitLab Milestone.
DO NOT USE: iteration, cycle.

## DAG (Directed Acyclic Graph)

The task dependency graph. Models which tasks block which. Validated deterministically via topological sort (Kahn's algorithm). Catches cycles, identifies parallel sets, finds critical path.

## Dependency Types

8 types of task-to-task relationships:

| Type | Creates execution edge? | Meaning |
|---|---|---|
| `blocks` | Yes | Target cannot start until source completes |
| `conditional-blocks` | Yes | Target cannot start unless source completes AND condition met |
| `waits-for` | Yes | Target cannot start until source's external gate clears |
| `validates` | No | Source validates target's output (testing relationship) |
| `caused-by` | No | Source was discovered because of target |
| `discovered-from` | No | Source was discovered during target's execution |
| `supersedes` | No | Source replaces target |
| `related` | No | Informational link |

Only `blocks`, `conditional-blocks`, and `waits-for` create execution edges in the DAG. The other 5 are informational — they help with traceability but don't affect scheduling.

## Gate

An external blocking condition on a task. A task with an unresolved gate cannot be started even if all its dependency tasks are complete. Types:
- **pr-merged** — waits for a specific PR to be merged
- **ci-passed** — waits for a CI pipeline to pass
- **timer** — waits until a specific time
- **human** — waits for explicit human action

Added via `ydk task add-gate <id> --type <type>`.

## Complexity Score

An LLM-scored value (1-10) for each task, estimating implementation difficulty. Tasks scoring above the configured threshold (default: 7) are flagged for splitting. Run via `ydk task analyze-complexity`.

## Coverage Check

Deterministic validation that every spec section (within scope of current change) maps to at least one story. Run via `ydk task coverage`.

## Wave

A set of tasks with zero pending dependencies that can run simultaneously. Computed from the DAG via topological sort.

## Critical Path

The longest chain of sequential dependencies in the DAG. Determines the minimum total duration — delays here delay everything.

## Fan-Out

A task that blocks many others. High fan-out tasks should be prioritized.

## Buffer Zone

Sprint health tracking using critical chain buffer management. Measures how much of the sprint's buffer has been consumed. Sprint health tracking shows:
- **Green** — on track, buffer healthy
- **Yellow** — consuming buffer, needs attention
- **Red** — buffer exhausted, sprint at risk

## Compaction

Compressing completed task data to reduce context window usage. `ydk task archive-done` compresses individual done tasks; `--all-done` compresses all completed tasks at once. Archived tasks retain their IDs and relationships but shed verbose descriptions.

## Ready

The set of tasks that can be started right now — all dependencies resolved, no unresolved gates, not yet claimed. `ydk task ready` lists them ranked by priority (considering critical path position, fan-out, and complexity).

## Resource Scheduling

`ydk task plan-waves --agents N` produces a critical chain schedule respecting resource constraints (number of available agents). Reads tasks from the repository (no file argument). Identifies buffer sizes and expected completion dates.

## Batch YAML

A YAML file with top-level `epics:`, `stories:`, and `tasks:` sections used by `ydk task create-batch`. Each entity has an `id` field for cross-referencing within the file. Task `depends_on` entries use these placeholder IDs, which are resolved to real GitHub issue numbers in a second pass after all issues are created. Labels (`epic`, `story`, `task`, etc.) are auto-created before batch processing.

## Component Coverage

`ydk task component-coverage` checks that every component manifest in `.ydk/components/` is referenced by at least one task's `component_refs`. Supports `--exclude` glob patterns (e.g., `ydk:page:*`) and `--strict` mode (exit code 1 on uncovered components).

## Coverage Exclusions

Glob patterns configured in `task_management.coverage_exclude` that are skipped during `ydk task coverage`. Used to exclude reference documents (glossary, scope, etc.) that describe context but do not require dedicated story coverage.

## Dry-Run

The `--dry-run` flag on `ydk task create`, `ydk task create-story`, and `ydk task create-batch`. Validates all inputs (YAML structure, dependency references, component refs, spec refs) and shows what would be created, without calling the GitHub/GitLab API. Useful for checking batch YAML correctness before committing to issue creation.

## Critical Path (Dependency-Only)

The longest chain of sequential dependencies in the DAG, ignoring resource limits. Shown by `ydk task validate-dag`. Determines minimum project duration assuming unlimited agents.

## Critical Chain (Resource-Constrained)

The longest chain accounting for agent availability. Shown by `ydk task plan-waves --agents N`. Delays here delay everything when agents are limited.

## Blocked-by-code

Task status: a technical issue prevents progress. Label the issue, explain what's wrong, suggest resolution.

## Blocked-by-decision

Task status: needs human input. Label the issue, present options with recommendation, wait for human.
