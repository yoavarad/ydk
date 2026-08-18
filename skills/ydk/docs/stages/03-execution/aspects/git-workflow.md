# Git Workflow

## Branch Strategy

Every task gets its own feature branch. No work happens on main. Ever.

**Branch naming:** `task/<task-id>-<short-description>`
- Example: `task/T-a1b2c3d4-order-validation`
- Enforced by pre-push hook

**Commit messages:** Conventional commits, enforced by both pre-commit hook and commit-msg hook.
- `feat(orders): implement order validation rules`
- `test(orders): add unit tests for balance check`
- `fix(orders): handle PARTIALLY_FILLED state`

## Commit-Message Hook

`ydk init` installs a commit-msg hook that validates every commit message matches conventional commit format:

```
<type>(<scope>): <description>
```

**Types:** feat, fix, refactor, test, docs, chore

The hook runs at commit time and **rejects** non-conforming messages immediately. This is separate from the pre-commit hook (which runs lint/type checks) — the commit-msg hook only validates the message format.

**Example rejection:**
```
$ git commit -m "updated order stuff"
ERROR: Commit message does not match conventional format.
Expected: <type>(<scope>): <description>
Example:  feat(orders): implement order validation rules
```

## Worktree Lifecycle

Every task runs in an isolated git worktree. This means parallel agents each have their own filesystem — no conflicts.

**Created by `ydk task start <id>`:**
1. Creates branch: `task/T-a1b2c3d4-order-validation`
2. Creates worktree: `.ydk/worktrees/T-a1b2c3d4/`
3. Worktree is a full working copy branched from main
4. Agent works entirely within the worktree

**Destroyed after merge:**
1. PR merged → branch deleted on remote
2. `ydk task cleanup <id>` removes local worktree + branch
3. Or automatic cleanup: YDK detects merged branches and cleans

## Hooks

**Pre-commit (fast, < 5 seconds):**
- `ruff format --check` (formatting)
- `ruff check` (linting)
- `ty check` (type checking)

**Commit-msg (instant):**
- Conventional commit message format validation
- Rejects non-conforming messages

**Pre-push (thorough, < 5 minutes):**
- Branch name convention check
- Unit tests
- Deterministic enforcement checks
- Integration tests
- E2E tests
- Spec alignment check (AI-based, parallel)
- AI code review (parallel)

**Hook installation:** `ydk init` installs all three hooks via `git config core.hooksPath .ydk/hooks`. Hooks are shell scripts in `.ydk/hooks/` that call YDK commands.

## The Flow

```
ydk task start T-a1b2c3d4
  → creates branch task/T-a1b2c3d4-order-validation
  → creates worktree .ydk/worktrees/T-a1b2c3d4/
  → agent works in worktree

Agent commits (commit-msg hook validates format, pre-commit hook runs: lint + types)

ydk task done T-a1b2c3d4
  → runs ALL verifications
  → commits final state
  → pushes (pre-push hook runs: tests + enforce + spec-align + review)
  → creates PR "Closes #T-a1b2c3d4"
  → posts proof to issue

Human approves → merge → branch deleted → worktree cleaned
```

## Rules

- You MUST NOT commit directly to main
- You MUST NOT push to main
- You MUST use conventional commit messages (enforced by commit-msg hook)
- You MUST work in the task's worktree, not the main working directory
- You MUST NOT modify files outside the task's scope
