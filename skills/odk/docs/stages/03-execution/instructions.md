# Execution

## Overview

Implement tasks autonomously using proof-based development. Each task follows a defined lifecycle: understand → plan → scaffold → implement (TDD) → verify → review → PR. The human's only mandatory intervention is approving the PR.

## Parameters

- **task_id** (required): The task to implement (e.g., "T-a1b2c3d4" or GitHub Issue number)
- **project_root** (required): Detected automatically from `.odk/` location

## Steps

### 1. Start the Task

Claim the task, create an isolated workspace, and explore what's needed.

**Constraints:**
- You MUST run `odk task start <task_id>` before any other work
- This creates a git worktree + feature branch automatically
- You MUST NOT proceed if dependencies are unresolved or gates are not cleared (ODK checks this)
- You MUST work in the worktree, not the main working directory
- You MAY use `--base <branch>` to branch from a specific base (default: HEAD)
- You MAY use `--force` to restart a stale task (re-create worktree)

**What `odk task start` does:**
1. Checks all blocking dependencies are resolved (merged) and all gates are cleared
2. Creates branch `task/<id>-<description>` from `--base` (default: HEAD; branch names sanitized: colons, slashes, dots stripped; only `[a-z0-9-]` kept)
3. Creates worktree at `.odk/worktrees/<id>/`
4. Claims the task (assigns to you, labels `in-progress`)
5. Reads `component_refs` and `spec_refs` from the task
6. Posts exploration summary to the task issue

**After it runs, explore the codebase (read `aspects/git-workflow.md`):**

**Phase 1 — Orientation:**
- Read `docs/project-rules.md` for conventions and gotchas
- Read relevant ADRs for architectural decisions
- Understand the directory structure

**Phase 2 — Spec Anchoring:**
- Read every narrative section listed in the task's `spec_refs`
- Read every component manifest listed in the task's `component_refs`
- Read the glossary for correct terminology
- Read cross-cutting concerns (error format, pagination, timestamps)

**Phase 3 — Code Discovery:**
- Find existing code that follows a similar pattern (your reference)
- Identify which files you'll create vs modify
- Check interfaces your code must match

**Phase 4 — Dependency Verification:**
- Confirm prerequisite tasks' code actually exists in the codebase
- If anything is missing: `odk task block <id> --reason code --detail "..."`

ODK posts the exploration summary to the task issue automatically. You continue immediately — no gate.

**Example:**

```bash
odk task start T-a1b2c3d4
# Creates worktree at .odk/worktrees/T-a1b2c3d4/
# Loaded component_refs: [odk:entity:orders/Order]
# Loaded spec_refs: [orders.md#entities, overview.md#cross-cutting]
# Posts to issue: "Exploration complete. Loaded odk:entity:orders/Order manifest..."

# Branch from a specific base:
odk task start T-a1b2c3d4 --base feature/api-v2

# Restart a stale task:
odk task start T-a1b2c3d4 --force
```

### 2. Plan the Approach

Write a concrete implementation plan anchored to specific files, functions, and test cases.

**Constraints:**
- You MUST plan before writing code
- The plan MUST list specific files to create/modify
- The plan MUST reference `component_refs` for what to implement
- The plan MUST list specific test cases (these become the TDD targets)
- The plan MUST map acceptance criteria to test cases
- You MUST run `odk task comment <id>` to post the plan to the issue

**Plan format:**
- Component manifests being implemented (from `component_refs`)
- Files to create (with function signatures)
- Files to modify (what changes)
- Test cases (all of them — these get written first in TDD)
- TDD sequence (what order to write tests → implement)
- Acceptance criteria mapping (which test proves which criterion)

**Example:**

```bash
odk task comment T-a1b2c3d4 "PLAN:
Implementing: odk:entity:orders/Order
1. Create tests/unit/domain/validation/test_order_validator.py (11 tests)
2. Create src/domain/validation/order_validator.py
   - validate_place_order(order, balance, symbols) → None or raises
   - validate_cancel_order(order) → None or raises
3. TDD: write all 11 tests → implement validate_place → implement validate_cancel
4. AC mapping: insufficient_balance → test_insufficient_balance_returns_422
"
```

### 3. Scaffold (if applicable)

If the task involves generating boilerplate, use templates before hand-writing code. Read `aspects/scaffolding.md` for details.

**Implementation with Scaffolding:**

1. Check if a scaffold applies: `odk scaffold list`
2. If yes, scaffold first: `odk scaffold apply <template> --from <component-id>`
3. Review generated code, fill in business logic
4. Write tests (scaffold may generate test stubs too)
5. Run verification

**Constraints:**
- You SHOULD check `odk scaffold list` for available templates
- If a template matches this task's pattern, You MUST use it
- You MAY use `odk scaffold apply <name> --from <component_ref>` to generate code directly from a component manifest
- You MAY use `odk scaffold apply <name> --map <mapping>` to map manifest fields to template variables
- You MUST NOT modify generated files (they have GENERATED headers)
- You SHOULD create a new template if you notice a repeating pattern (3+ occurrences)

**Example:**

```bash
odk scaffold list
odk scaffold apply fastapi-route --from odk:route:orders/create
# Or with explicit variable mapping:
odk scaffold apply fastapi-route --var entity_name=Order --var entity_snake=order
```

If no template applies, skip this step and hand-write everything.

### 4. Implement TODOs (TDD)

Write code using strict Red-Green-Refactor cycles. When the task has assigned TODOs (from ignition), implement the business logic that replaces each `NotImplementedError` placeholder. Read `aspects/testing-strategy.md` for the full testing protocol.

**TDD is now enforced by the guard system** — the `tdd-guard` (installed via `odk init`) blocks writes to source files (`src/`, `app/`) when no corresponding test exists. The TDD state machine (`red → green → refactor → red`) is tracked in `.odk/tdd-state.json` and resets on `git commit`. You cannot bypass this guard.

**Constraints:**
- You MUST write tests FIRST (Red) — the guard will block source writes otherwise
- You MUST run tests and verify they FAIL before implementing
- You MUST write MINIMUM code to make tests pass (Green)
- You MUST refactor only when tests pass (Refactor)
- You MUST resolve all assigned TODOs by replacing `NotImplementedError` with real business logic
- You MUST run `odk todo show <todo-id>` to understand each TODO's context before implementing
- You MUST post progress updates at key milestones via `odk task comment`
- Unit tests MUST mirror the source structure: `src/X/Y/Z.py` → `tests/unit/X/Y/test_Z.py`
- You MUST NOT use float for financial values — use Decimal
- You MUST NOT mock internal classes — only mock at system boundaries

**The TDD flow:**

```
1. Write ALL test cases (they import code that doesn't exist yet)
2. Run: odk verify tests --level unit
   → All FAIL (ImportError or assertion failures)
   → odk task comment T-a1b2c3d4 "RED: 11 tests written, all failing"

3. Implement first function — minimum to pass some tests
4. Run: odk verify tests --level unit
   → Some PASS
   → odk task comment T-a1b2c3d4 "GREEN: 7/11 passing"

5. Continue implementing until all pass
6. Run: odk verify tests --level unit
   → All PASS
   → odk task comment T-a1b2c3d4 "GREEN: 11/11 passing"

7. Refactor if needed → run tests → still pass
```

**Milestones to post:**

| When | What to post |
|---|---|
| Tests written | `odk task comment T-a1b2c3d4 "RED: 11 tests written, all failing"` |
| First green | `odk task comment T-a1b2c3d4 "GREEN: 5/11 passing"` |
| All green | `odk task comment T-a1b2c3d4 "GREEN: 11/11 passing"` |

### 5. Verify

Run all verification checks. Read `aspects/verification.md` for the plugin system and `aspects/spec-alignment.md` for drift detection.

**Constraints:**
- You MUST run `odk verify run --trigger pre-push` before completing the task
- ALL checks MUST pass — no exceptions
- If a check fails, You MUST fix the issue and re-run
- You MUST NOT bypass or skip any verification
- You SHOULD run `odk verify run --trigger pre-commit` frequently during development for fast feedback
- You MAY use `odk verify run --auto-fix` to auto-fix lint issues before checking
- You MAY use `odk verify run --retry N --repair` for auto-repair loop on stubborn issues
- You MAY review changes with `git diff` for structured review before final verification

**What runs:**

**`git:pre-commit` trigger (fast):** Lint + type checking
**`git:pre-push` trigger (thorough):** All tests (unit + integration + E2E) + deterministic enforcements + AI spec alignment + AI code review

**Verification caching:** Results are cached by content hash. If files haven't changed, cached results are reused. Use `--no-cache` to force re-run. Use `odk verify clear-cache` to purge the cache.

**If verification fails:**

```
odk verify run --trigger pre-push
# ✗ spec-alignment: interface_compliance 6/10
#   "Error response uses {detail:str} instead of RFC 7807"

# Fix the issue
# Re-run (or use auto-repair):
odk verify run --trigger pre-push --retry 2 --repair
# ✓ All checks passed
```

### 6. Review (External)

AI review agents examine your code independently. Read `aspects/code-review.md` for the review process.

**Constraints:**
- Review is part of `odk verify run --trigger pre-push` (Layer 3) — it runs automatically
- Reviews are external agents (not self-review) to avoid bias
- Critical findings MUST be fixed before proceeding
- Warning findings SHOULD be addressed
- Info findings MAY be ignored

The review checks:
- Spec compliance (does code match the spec and component manifests?)
- Security (injection, auth bypass, data exposure?)
- Code quality (naming, structure, patterns, test quality?)

**Review tip:** Before the final review, you MAY review changes with `git diff` to verify all changes are organized and coherent.

### 7. Capture Knowledge

Before completing, capture anything learned during implementation.

**Constraints:**
- If you discovered a gotcha: You MUST add it to `docs/project-rules.md`
- If you made an architectural decision: You MUST write an ADR
- If you researched an external technology: You MUST cache it in `docs/research/`
- If you discovered work not in the spec: You MUST run `odk task add-subtask <parent-id>`

**Example:**

```bash
# Discovered that Binance returns 418 (not just 429) for rate limiting
# Add to project rules:
echo "- Binance returns HTTP 418 (IP banned) in addition to 429 (rate limited)" >> docs/project-rules.md

# Discovered a new subtask is needed:
odk task add-subtask T-a1b2c3d4 --title "Handle Binance 418 ban response" --body "Discovered during T-a1b2c3d4..."
```

### 8. Complete the Task

Run `odk task done` to finalize: verify everything, create PR, post proof.

**Constraints:**
- You MUST run `odk task done <task_id>` — this is the only way to complete a task
- ODK runs ALL verifications (all triggers)
- ODK creates the feature branch commit, pushes, and creates the PR
- ODK posts verification proof to the task issue
- ODK includes proof in the PR description
- If verification fails, `odk task done` exits with error — fix and re-run
- You MUST NOT create PRs manually
- You MAY use `odk verify run --pr <URL>` to post verification results to an existing PR

**What `odk task done` does:**
1. Checks that all assigned TODOs are resolved (no remaining `NotImplementedError` for assigned TODO IDs)
2. Runs `odk verify run --trigger pre-push` (all layers, all plugins)
3. If any fail → exits with error, prints first 3 lines of failure output per failing check, posts failure to issue
4. If all pass → commits, pushes branch
5. Creates PR with "Closes #<task_id>" and proof in description (assembled from all plugin results in `.odk/proofs/<task>/plugins/<name>.txt`)
6. Prints PR URL on success
7. Posts proof summary to task issue
8. Updates task label to `in-review`
9. `ty` check is scoped to changed files only (won't block on generated code)

**Example:**

```bash
odk task done T-a1b2c3d4
# Running verifications...
# ✓ lint-ruff (0.3s)
# ✓ types-ty (0.5s)
# ✓ tests-pytest (11 passed, 2.1s)
# ✓ python-no-future-annotations (0.1s)
# ✓ spec-alignment (6/6 dimensions, 12.4s)
# ✓ code-review (0 critical, 18.2s)
#
# ALL PASSED (33.6s)
# PR #47 created: https://github.com/repo/pull/47
# Proof saved: .odk/proofs/T-a1b2c3d4/
```

### 9. Human Reviews

The ONLY mandatory human intervention point.

**What happens:**
- Human sees the PR with proof in the description
- Human reviews the diff + proof artifacts
- Human approves → merge → task auto-closes → dependents unblock
- Human requests changes → the watch system detects the comment and resumes the agent session

**After merge:**
- ODK cleans up the worktree and feature branch
- Dependent tasks become unblocked
- The next agent can pick up newly unblocked tasks

### 10. PR Review Feedback Loop

When a human leaves review comments on a PR, the watch system (`odk watch`) detects them and resumes the agent session. The agent then addresses each comment.

**IMPORTANT: ALWAYS create PRs using `odk task done`. Never use `gh pr create` directly.**
`odk task done` captures verification output deterministically and assembles the PR body from proof files. Manual PR creation bypasses all proof capture.

**Constraints:**
- You MUST use `odk task review-comments <task-id>` to fetch the latest PR review comments
- `odk task start` checks for existing PR comments and displays them when resuming work
- You MUST reply to each comment on the PR with the format below
- The `<!-- odk-agent-reply -->` marker MUST be on the first line to prevent the watch system from re-triggering on your own replies

**When addressing PR review comments:**
1. Read the comment carefully
2. Make the change (or verify it's already done)
3. Run verification (`ruff check`, `pytest`)
4. Commit and push
5. Reply to each comment on the PR with this format:

```markdown
<!-- odk-agent-reply -->
> <quoted original comment>

**Addressed.** <what was changed or why no change needed>

Changed files:
- `path/to/file.py` (line N: description)

<details>
<summary>Verification</summary>

<paste actual ruff + pytest output>

</details>

Pushed: `<commit-hash>` on `<branch>`
```

**The autonomous feedback flow:**
1. Agent creates PR via `odk task done`
2. `odk watch install` starts 30-second polling
3. Human leaves PR comment hours later
4. Watch detects comment, reacts 👀, resumes Claude Code session
5. Agent addresses feedback, runs verification, pushes, posts reply with proof
6. Watch skips agent's reply (marker-based filter)
7. Human sees 👀 on their comment and the detailed reply

## Troubleshooting

### Unresolved dependencies
`odk task start` fails because a dependency isn't merged yet. Wait for the upstream task to complete, or check if it's blocked.

### Unresolved gate
`odk task start` fails because a gate (pr-merged, ci-passed, timer, human) isn't cleared. Check the gate status and resolve the external condition.

### Verification fails repeatedly
Read the specific failure output carefully. Try `odk verify run --retry 3 --repair` for auto-repair. Common issues:
- Spec alignment: error response shape doesn't match spec → fix the response format
- Lint: import ordering → run `odk verify run --auto-fix`
- Tests: mocking internal classes → remove the mock, test the real code

### Task takes too long
If you exceed the configured time-box (`execution.task_timeout_minutes`):
- Post progress with what's done and what's remaining
- `odk task block T-a1b2c3d4 --reason code --detail "Task too large, suggest splitting"`

### Discovered spec inconsistency
If the spec contradicts itself or contradicts the existing code:
- `odk task block T-a1b2c3d4 --reason decision --detail "Spec says X but existing code does Y"`
- Do NOT resolve the conflict yourself — the human decides

### Generated file needs modification
If a scaffolded file (with GENERATED header) needs changes:
- The template is wrong, not the generated file
- Update the template, regenerate, then continue
