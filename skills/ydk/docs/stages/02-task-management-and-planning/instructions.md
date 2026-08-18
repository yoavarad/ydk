# Task Management & Planning

## Overview

Decompose specs into the PM hierarchy (Release → Epic → Story → Task), validate dependencies as a DAG, plan sprints, and coordinate agent-driven execution. This SOP covers the complete flow from specs to running sprint.

Tasks now carry `component_refs` (what to implement) and `spec_refs` (what narrative to read), use hash-based IDs (`T-a1b2c3d4`), and support 8 dependency types with gates for external blocking conditions.

## Parameters

- **specs** (required): Path to the project's spec location containing approved narrative files and component manifests
- **remote** (required): GitHub or GitLab — determines CLI used (`gh` or `glab`)
- **sprint_goal** (required): Human-defined goal for the sprint (provided during Step 4)

## Steps

### 1. Release Definition

Define what ships and by when. This forces prioritization — without a target, everything looks equally important.

**Constraints:**
- You MUST create a GitHub/GitLab Milestone with a target date
- You MUST assign epics to the release
- You MUST get human approval on the release scope

**Example:**

> Release: v1.0 — "Core paper trading: register, trade, view portfolio"
> Epics: Order Management, Portfolio Tracking, Auth, Market Data
> Target: 2 weeks

### 2. Epic & Story Creation

Create epics and stories from the specs. Epics group related stories. Stories describe user value with testable acceptance criteria.

**Constraints:**
- You MUST create epics as GitHub/GitLab Issues
- You MUST create stories as Issues labeled `story`
- Every story MUST have testable acceptance criteria (not "works correctly")
- Every story MUST reference spec sections by `filename.md`
- Every story MUST belong to an epic
- Stories SHOULD include `--component-refs` linking to relevant component manifests
- Stories SHOULD include `--spec-refs` linking to narrative files
- You MUST NOT create stories without acceptance criteria

**Individual creation:**

```bash
ydk task create-epic --title "Orders System" --release "v1.0" --spec-refs orders.md
ydk task create-story --title "Place Order" --epic E-abc12345 \
  --spec-refs orders.md --component-refs "ydk:entity:orders/Order,ydk:route:orders/create" \
  --acceptance "Valid order → 201; Insufficient balance → 422"
```

**Batch creation (preferred for full hierarchy):**

Create a YAML file with `epics:`, `stories:`, and `tasks:` sections. Each entity has an `id` field for cross-referencing within the file. Dependencies use placeholder IDs resolved to real GitHub issue numbers via two-pass resolution.

```yaml
# batch.yaml
epics:
  - id: E-orders
    title: "Orders System"
    spec_refs: orders.md

stories:
  - id: S-place-order
    title: "Place Order"
    epic: E-orders
    spec_refs: orders.md
    component_refs: "ydk:entity:orders/Order,ydk:route:orders/create"
    acceptance: "Valid order → 201; Insufficient balance → 422"

tasks:
  - id: T-order-model
    title: "Implement Order model"
    story: S-place-order
    component_refs: "ydk:entity:orders/Order"
    spec_refs: orders.md
    depends_on: []
  - id: T-order-route
    title: "Implement POST /orders route"
    story: S-place-order
    depends_on:
      - "T-order-model:blocks"
```

```bash
# Validate without creating issues
ydk task create-batch --from batch.yaml --dry-run

# Create everything — labels auto-created, deps resolved in second pass
ydk task create-batch --from batch.yaml
```

**Validation during batch creation:**
- All `depends_on` references must point to IDs defined in the same YAML
- All dependency types must be valid (blocks, validates, etc.)
- Self-dependencies are detected and rejected
- `spec_refs` validated against real files
- `component_refs` validated against `.ydk/components/`
- Orphaned tasks/stories (referencing non-existent parents) are flagged

**Example — Story OM-001:**

> ```
> Title: As a user, I can place a buy/sell order
> Epic: Order Management
> Spec refs: orders.md
> Component refs: ydk:entity:orders/Order, ydk:route:orders/create
>
> Acceptance criteria:
> - Valid order → 201 with order ID and PENDING status
> - Insufficient balance → 422 with available vs required amounts
> - Invalid symbol → 400 with validation error
> - All orders visible in order history after creation
> ```

### 3. Coverage Check

Verify every spec section maps to at least one story. Gaps mean spec content that won't be implemented.

**Constraints:**
- You MUST run the coverage check: `ydk task coverage <spec_location>`
- You MUST NOT proceed if coverage check fails
- You SHOULD scope the check to changed spec files for amendments
- You MAY configure `task_management.coverage_exclude` in `.ydk/config.yaml` to skip reference docs (glossary, scope, etc.)
- You SHOULD run `ydk task component-coverage` to verify every component manifest is referenced by a task
- You MAY use `ydk task component-coverage --exclude 'ydk:page:*' --strict` to exclude patterns and enforce exit code

**Example:**

> ```bash
> ydk task coverage docs/specs/
> # Coverage check PASSED — all spec sections have stories.
>
> ydk task component-coverage --strict
> # All 24 components covered by tasks.
>
> # With exclusions for reference-only components:
> ydk task component-coverage --exclude 'ydk:page:*' --exclude 'ydk:glossary:*' --strict
> ```

### 4. Story Decomposition into Tasks

Stories describe user value ("I can place an order"). Tasks describe agent work ("implement the Order SQLAlchemy model"). Decomposition bridges intent and implementation.

This is the core of Stage 02. Decomposition happens in 6 sub-stages — MUST NOT be done in a single LLM call. The 6-stage pipeline forces deep understanding, boundary identification, precise definition, dependency validation, parallelism maximization, and completeness verification as separate thinking steps.

#### 4A. Understand

Read everything before decomposing. Build understanding first.

**Constraints:**
- You MUST read: story + acceptance criteria + all referenced spec sections + relevant component manifests
- For brownfield: You MUST read existing code in affected areas
- You MUST NOT produce tasks yet — understanding first

**Example — OM-001:**

> Agent reads: orders.md, overview.md#cross-cutting, overview.md#testing-strategy, plus component manifests `ydk:entity:orders/Order`, `ydk:route:orders/create`, `ydk:error:orders/insufficient-balance`

#### 4B. Identify Work Units

Find natural boundaries. Each should be one agent, one session, one PR.

**Example — OM-001:**

> 1. Order entity + repository (data layer)
> 2. Order validation rules (domain)
> 3. Place order service (orchestration)
> 4. POST /api/v1/orders route (HTTP)
> 5. Unit tests for validation
> 6. Integration tests for service
> 7. E2E test for endpoint

#### 4C. Assign TODOs to Tasks

After ignition (Stage 01.5), every `NotImplementedError` placeholder is registered as a TODO with an `YDK-TODO-NNN` ID. Link these TODOs to tasks so that `ydk task done` can verify resolution.

**Constraints:**
- You MUST run `ydk todo list` to see all registered TODOs
- You MUST use `ydk todo auto-assign --apply` as the PRIMARY method — it matches TODOs to tasks by file path and component_refs automatically
- For any TODOs not auto-assigned, use `ydk todo assign-batch <mapping>` for bulk assignment from YAML or inline mapping
- Use individual `ydk todo assign <todo-id> <task-id>` only for one-off corrections
- Tasks should focus on business logic only — boilerplate is already generated by ignition
- You MUST NOT create tasks for boilerplate that was already generated (models, route stubs, repository interfaces)
- You SHOULD run `ydk todo coverage` to verify all TODOs are assigned before proceeding
- A single task MAY have multiple TODOs assigned to it if they are closely related
- You MAY use `ydk task scaffold-batch` to generate a batch YAML from existing TODOs as a starting point

**Example:**

> ```bash
> ydk todo list
> # YDK-TODO-001  src/domain/services/order_service.py:23     place_order() business logic
> # YDK-TODO-002  src/domain/services/order_service.py:45     cancel_order() business logic
> # YDK-TODO-003  src/domain/validation/order_validator.py:12  validate_place_order() rules
>
> # PRIMARY: auto-assign by file path matching against task component_refs
> ydk todo auto-assign --apply
> # Assigned 20/23 TODOs automatically
>
> # SECONDARY: bulk assign remaining TODOs
> ydk todo assign-batch "YDK-TODO-021:T-m3n4o5p6,YDK-TODO-022:T-e5f6g7h8"
>
> # ONE-OFF: individual corrections
> ydk todo assign YDK-TODO-023 T-m3n4o5p6
>
> ydk todo coverage
> # TODO coverage: 0/23 resolved, 23/23 assigned (100% assigned)
> ```

#### 4D. Define Each Task

Write precise task descriptions with component_refs and spec_refs. This is the contract with the implementing agent.

**Constraints:**
- Every task MUST have: title, story reference, component_refs, spec_refs, description, acceptance criteria, dependencies (typed), test strategy
- Task IDs are hash-based: `T-a1b2c3d4` (auto-generated)
- `--component-refs` values are validated against real files in `.ydk/components/` at creation time
- `--spec-refs` values are validated against real files at creation time
- `--depends-on` references must point to existing tasks; dependency types are validated
- Multiple dependencies are comma-separated: `--depends-on T-abc:blocks,T-def:validates`
- Self-dependencies are detected and rejected
- Acceptance criteria and test strategy trigger warnings if omitted
- You MAY use `--dry-run` to validate without creating the issue
- You MUST NOT use vague descriptions ("implement the order stuff")
- The description MUST be detailed enough for a fresh agent with no context beyond this task + the spec + the component manifests

**Example — task for Order entity:**

> ```
> Title: Implement Order entity and repository
> Story: #38 (OM-001: Place Order)
> Component refs: [ydk:entity:orders/Order]
> Spec refs: [orders.md#entities, overview.md#cross-cutting]
>
> Description:
> Create Order SQLAlchemy model matching the ydk:entity:orders/Order manifest:
> id (UUID PK), user_id (UUID FK→User), symbol (str max 10), side (enum BUY|SELL),
> order_type (enum MARKET|LIMIT), quantity (Decimal(18,8) >0), price (Decimal(18,2)
> >0 nullable), status (enum PENDING|FILLED|PARTIALLY_FILLED|CANCELLED default
> PENDING), filled_quantity (Decimal(18,8) default 0), filled_avg_price
> (Decimal(18,2) nullable), notes (str max 500 nullable), created_at (datetime
> auto), updated_at (datetime auto), filled_at (datetime nullable).
>
> OrderRepository: create, get_by_id, list_by_user(user_id, page, size),
> update_status. All async. Generate alembic migration.
>
> Acceptance criteria:
> - Model has all fields from component manifest with correct types
> - Repository CRUD works against PostgreSQL
> - Alembic migration applies cleanly
>
> Dependencies: none
> Test strategy: Integration test for repo against testcontainers PG
> ```

#### Scaffolding Awareness (during task definition)

When defining tasks, identify which can use scaffolding:
- Tasks implementing entities → scaffold from `ydk:entity:*` component
- Tasks implementing routes → scaffold from `ydk:route:*` component
- Tasks implementing contracts → scaffold from `ydk:contract:*` component

Add scaffold info to task description:
"Scaffold: `ydk scaffold apply fastapi-route --from ydk:route:orders/create`"

Scaffolded tasks are lower complexity (score 3-5 instead of 7-10) because 60-70% of code is auto-generated.

#### 4E. Model the Dependency Graph

Declare typed dependencies. Then validate deterministically — MUST NOT let the LLM reason about scheduling.

**Constraints:**
- You MUST declare dependencies with their type: `blocks`, `validates`, `caused-by`, `conditional-blocks`, `waits-for`, `discovered-from`, `supersedes`, `related`
- Only `blocks`, `conditional-blocks`, and `waits-for` create execution edges
- You MUST run DAG validation: `ydk task validate-dag`
- You MUST fix any cycles before proceeding
- You SHOULD note the critical path (dependency-only) shown by validate-dag and high fan-out tasks
- You SHOULD run `ydk task plan-waves --agents N` for the resource-constrained critical chain
- You MAY add gates for external blocking conditions: `ydk task add-gate <id> --type pr-merged|ci-passed|timer|human`

**Critical path vs critical chain:**
- `validate-dag` shows the **critical path (dependency-only)** — the longest chain ignoring resource limits
- `plan-waves` shows the **critical chain (resource-constrained)** — accounts for agent availability

**Example — OM-001:**

> ```
> T-a1b2c3d4 (entity + repo)          ← no deps
>   ├── T-e5f6g7h8 (validation)       ← blocks: T-a1b2c3d4
>   │     └── T-i9j0k1l2 (unit)       ← validates: T-e5f6g7h8
>   ├── T-m3n4o5p6 (service)          ← blocks: T-a1b2c3d4, T-e5f6g7h8
>   │     └── T-q7r8s9t0 (integ)      ← validates: T-m3n4o5p6
>   └── T-u1v2w3x4 (route)            ← blocks: T-m3n4o5p6
>         └── T-y5z6a7b8 (E2E)        ← validates: T-u1v2w3x4
> ```
>
> ```bash
> ydk task validate-dag
> # DAG is valid (execution edges only from blocks/conditional-blocks/waits-for).
> # Parallel sets: Wave 1: T-a1b2c3d4 | Wave 2: T-e5f6g7h8 | Wave 3: T-m3n4o5p6,T-i9j0k1l2 | ...
> # Critical path (dependency-only): T-a1b2c3d4 → T-e5f6g7h8 → T-m3n4o5p6 → T-u1v2w3x4 → T-y5z6a7b8
> ```

#### 4F. Maximize Parallelism & Analyze Complexity

Review the DAG — can any sequential dependency be removed? Score task complexity.

**Constraints:**
- You SHOULD accept merge conflicts over unnecessary sequencing
- You MUST NOT create false dependencies out of habit
- You MUST run `ydk task analyze-complexity` to score all tasks 1-10
- Tasks above the complexity threshold (default: 7) MUST be split into smaller tasks
- You SHOULD re-validate the DAG after splitting

**Example:**

> ```bash
> ydk task analyze-complexity
> # T-a1b2c3d4  Order entity + repo        3/10  OK
> # T-e5f6g7h8  Order validation           4/10  OK
> # T-m3n4o5p6  Order service              8/10  SPLIT RECOMMENDED
> # T-u1v2w3x4  Order route                5/10  OK
> ```
>
> T-m3n4o5p6 scores 8 — split into T-m3n4o5p6a (place order logic) and T-m3n4o5p6b (cancel order logic).

#### 4G. Validate Completeness

Every story acceptance criterion must map to at least one task.

**Constraints:**
- You MUST check every acceptance criterion against the task list
- If any criterion has no covering task, You MUST add a task

**Example:**

> | Criterion | Covered by |
> |---|---|
> | Valid order → 201 | T-u1v2w3x4 + T-y5z6a7b8 |
> | Insufficient balance → 422 | T-e5f6g7h8 + T-y5z6a7b8 |
> | Invalid symbol → 400 | T-e5f6g7h8 + T-y5z6a7b8 |
> | Orders visible in history | **GAP** → add new task: list endpoint |

### 5. Sprint Planning

Pull stories from backlog into a sprint milestone.

**Constraints:**
- All tasks for pulled stories MUST be decomposed (Step 4 complete)
- DAG across all sprint tasks MUST be validated
- Sprint goal MUST be stated explicitly
- You SHOULD propose demo-able increments
- You SHOULD run `ydk task plan-waves --agents N` to get a resource-constrained schedule
- Human MUST approve the sprint scope

**Example:**

> ```bash
> ydk task plan-waves --agents 3
> # Sprint 1: "Core order flow — place, view, cancel orders"
> # Stories: OM-001, OM-002, OM-003 | 20 tasks | 5 execution waves
> # Estimated: 3.2 days with 3 agents
> # Buffer: 0.8 days (green)
> # Demo-able: after Sprint 1, a user can register, log in, and trade
> ```

### 6. Execution Loop

Agent-driven continuous loop. Use `ydk task ready` to find actionable tasks.

**Constraints:**
- You MUST query for unblocked tasks using `ydk task ready` (ranks by priority, respects gates)
- You MUST claim tasks before working: `ydk task start <id>`
- You MUST create one PR per task with "Closes #N"
- Human MUST review and approve every PR (UP-1)
- You MUST NOT work on a task whose dependencies are not all closed or whose gates are not all resolved

**Example:**

> ```bash
> ydk task ready
> # Ready tasks (ranked by priority):
> #   1. T-a1b2c3d4  Order entity + repo     [critical path, high fan-out]
> #   2. T-x1y2z3a4  User entity + repo      [critical path]
> #   3. T-b5c6d7e8  Config setup            [no deps]
>
> ydk task start T-a1b2c3d4
> # → Wave 1 starts
> ```

### 7. Failure Handling

Tasks fail. Handle without losing work or blocking downstream.

**Constraints:**
- Blocked by code: You MUST label `blocked-by-code`, explain what's wrong, suggest resolution
- Blocked by decision: You MUST label `blocked-by-decision`, present options with recommendation
- Time-box exceeded: You MUST report progress and suggest splitting
- New work discovered: You MUST create new task issue with `discovered-from` dependency link
- You MUST NOT silently skip a blocked task

**Example — blocked by decision:**

> ```bash
> gh issue edit 42 --add-label blocked-by-decision --remove-label in-progress
> gh issue comment 42 --body "Decision needed: spec says 'validate symbol'
> but doesn't define the supported list. Options: (A) hardcode top 20,
> (B) fetch from Binance at startup. Recommend (B)."
> ```

### 8. Progress Tracking & Buffer Management

Track through GitHub/GitLab native tools + YDK sprint health.

**Constraints:**
- Issue status = task status
- Milestone progress = sprint completion
- You MUST use labels: `blocked-by-code`, `blocked-by-decision`, `story`, `task`, `epic`
- You MUST NOT create external tracking systems
- You SHOULD check sprint health through task list and GitHub/GitLab milestone progress
- Yellow buffer = surface risk to human. Red buffer = sprint scope must be reduced.

**Example:**

> ```bash
> ydk task list --sprint "Sprint 1"
> # Sprint 1: "Core order flow"
> #   12/20 tasks done, 6 in-progress, 2 blocked
>
> # Filter by epic, story, or status (results grouped by status)
> ydk task list --epic E-orders --status open
> ydk task list --story S-place-order
> ydk task list --status in-progress
> ```

### 9. Sprint Completion, Compaction & Unexpected Changes

Capture what happened. Handle changes. Compact completed work.

**Constraints:**
- You MUST record: what shipped, what rolled over, what was discovered, what failed
- You MUST update ADRs with decisions made during execution
- You SHOULD run `ydk task archive-done --all-done` to compress completed tasks for context efficiency
- For urgent work: You MUST surface impact ("Sprint has N days left, recommend deferring X")
- For requirement changes: You MUST go through Stage 01 brainstorming → spec amendment PR (or use `ydk change propose` for lightweight changes)
- Human MUST decide what gets bumped — the system surfaces information, not decisions

**Example:**

> ```bash
> ydk task archive-done --all-done
> # Compacted 12 completed tasks (saved ~8KB of context)
> # Task IDs and relationships preserved, verbose descriptions removed
> ```

## Troubleshooting

### Story has no clear acceptance criteria
Go back to the spec. If the spec doesn't support clear criteria, the spec needs amendment (return to Stage 01).

### DAG validation finds a cycle
Two tasks depend on each other. One of the dependencies is wrong — figure out which task can actually start first and remove the false dependency.

### Coverage check fails
Spec sections without stories. Either create stories for them or confirm they're cross-cutting concerns covered implicitly.

### Agent stuck on a task for too long
Check if the task is too large (`ydk task analyze-complexity` — split it), the spec is ambiguous (amend it), or the agent needs a decision (label `blocked-by-decision`).

### Buffer turns red
Sprint scope is too large for the remaining time. Surface to human with options: (A) drop lowest-priority stories, (B) extend sprint, (C) add agents if independent work exists.

### Task IDs collide
This should not happen with hash-based IDs. If it does, regenerate the colliding task with `ydk task create` — the new hash will be different.
