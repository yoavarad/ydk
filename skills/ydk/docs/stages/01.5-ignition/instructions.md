# Ignition (Stage 01.5)

## Overview

Generate a runnable project skeleton from the validated spec. After brainstorming produces narratives and component manifests, ignition transforms them into compilable code with tracked TODO placeholders for business logic. The result is a project that passes syntax checks, import validation, and formatting — but every business-logic function raises `NotImplementedError`. Stage 02 tasks then focus exclusively on implementing those TODOs.

## Prerequisites

- Stage 01 complete: narratives validated, component manifests created, spec quality check passed
- An ignition pack installed via `ydk catalog install <pack-name>` (checked during Step 0 of Stage 01)
- If no pack is installed, ignition will fail — you must install one first

## Steps

### 1. Preview the Generation Plan

Before generating anything, preview what ignition will produce:

**Constraints:**
- You MUST run `ydk ignite --dry-run` before running ignition for real
- You MUST review the file list and confirm it matches the expected project structure
- You MUST verify that all component manifests are consumed by the pack (uncovered components are listed as warnings)

**Example:**

> ```bash
> ydk ignite --dry-run
> # Ignition pack: hexagonal-architecture
> # Components consumed: 12 entities, 8 routes, 5 errors, 3 contracts, 2 external-deps
> # Files to generate: 47
> #   src/domain/models/order.py          (from ydk:entity:orders/Order)
> #   src/domain/models/user.py           (from ydk:entity:auth/User)
> #   src/ports/order_repository.py       (from ydk:contract:orders/order-repo)
> #   src/adapters/api/routes/orders.py   (from ydk:route:orders/create, ydk:route:orders/list)
> #   tests/unit/domain/test_order.py     (test stub)
> #   ...
> # TODOs to register: 23
> # Uncovered components: 0
> ```

### 2. Run Ignition

Generate the skeleton:

**Constraints:**
- You MUST run `ydk ignite` (without `--dry-run`) to generate the skeleton
- You MUST NOT modify generated files that have a `GENERATED` header — they are owned by the generator
- If ignition has been run before, it uses hash tracking for idempotency — unchanged files are skipped
- You MAY use `ydk ignite --force` to regenerate all files, overriding idempotency

**What ignition does:**
1. Reads the installed ignition pack and all component manifests in `.ydk/components/`
2. Runs generators as subprocesses (one per component type, or in phases for fullstack packs)
3. Writes generated files (no GENERATED headers — all files are developer-owned)
4. Registers a `YDK-TODO-NNN` for every `NotImplementedError` placeholder
5. Auto-installs runtime dependencies via `uv`
6. Runs post-generation checks: Python syntax validation, circular import detection, `ruff format`

**Phased ignition (fullstack packs):**
- `manifest.yaml` supports `phases` — sequential generator groups
- Phases can export artifacts (e.g., `openapi.json`) consumed by later phases via `YDK_ARTIFACT_*` env vars
- `pack_ref` references other installed packs (no generator duplication)
- Example: `fullstack-fastapi-nextjs` composes backend → frontend → infrastructure phases

**Example:**

> ```bash
> ydk ignite
> # Ignition pack: hexagonal-architecture
> # Generated: 47 files
> # Registered: 23 TODOs (YDK-TODO-001 through YDK-TODO-023)
> # Post-checks:
> #   Syntax check: PASSED (47/47 files)
> #   Circular imports: PASSED (0 cycles)
> #   Ruff format: PASSED
> ```

### 3. Verify the Skeleton Runs

After generation, verify the skeleton is actually runnable:

**Constraints:**
- You MUST verify the project passes basic quality checks: `ruff check`, `ruff format --check`
- You MUST verify tests can be collected (even though they all fail): `pytest --collect-only`
- You MUST verify the application starts: e.g., `uvicorn myapp:app` serves routes (this is a hard acceptance criterion, not optional)
- Runtime dependencies are auto-installed by ignition via `uv` — if the app doesn't start, the ignition pack has a bug
- You MUST NOT attempt to make tests pass — that is Stage 03 work

**Example:**

> ```bash
> ruff check src/ tests/
> # All checks passed
>
> ruff format --check src/ tests/
> # 47 files already formatted
>
> pytest --collect-only tests/
> # <Module tests/unit/domain/test_order.py>
> #   <Function test_order_creation>   (NotImplementedError expected)
> # collected 23 items
> ```

### 4. Review TODOs

Understand what business logic needs to be implemented:

**Constraints:**
- You MUST run `ydk todo list` to see all registered TODOs
- You MUST review each TODO to understand what business logic it represents
- You SHOULD run `ydk todo coverage` to see overall resolution status (should be 0% at this point)

**Example:**

> ```bash
> ydk todo list
> # YDK-TODO-001  src/domain/services/order_service.py:23     place_order() business logic
> # YDK-TODO-002  src/domain/services/order_service.py:45     cancel_order() business logic
> # YDK-TODO-003  src/domain/validation/order_validator.py:12  validate_place_order() rules
> # YDK-TODO-004  src/adapters/repos/order_repository.py:18   create() implementation
> # ...
> # Total: 23 TODOs, 0 resolved, 0 assigned
>
> ydk todo coverage
> # TODO coverage: 0/23 resolved (0%)
> ```

### 5. Commit and PR

Create a PR with the generated skeleton:

**Constraints:**
- You MUST commit all generated files + the TODO registry
- You MUST create a PR titled "feat: ignition skeleton from <pack-name>"
- You MUST include the TODO list in the PR description
- Human MUST approve before merging (UP-1)

## Troubleshooting

### Ignition fails with "no pack installed"
Run `ydk catalog list` to check installed packs. Install one with `ydk catalog install <name>`.

### Ignition fails with "uncovered components"
The installed pack does not consume all component types in your manifests. Either: (a) create manifests only for types the pack supports, or (b) accept that those components will need manual scaffolding in Stage 03.

### Generated code has import errors
The ignition pack may have assumptions about project structure that do not match your setup. Check `ydk catalog info <pack-name>` for expected directory layout. The post-generation circular import check should catch this.

### Want to regenerate after component changes
Run `ydk ignite` again — hash tracking means only changed files are regenerated. Use `ydk ignite --force` to regenerate everything.

### Developer modified a generated file
If you remove the `GENERATED` header from a file, ignition treats it as developer-owned and will not overwrite it on subsequent runs. This is intentional — once you take ownership, the generator respects that.
