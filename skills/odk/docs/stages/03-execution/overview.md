# Stage 03: Execution — Overview

## What This Stage Does

Agents implement tasks autonomously. Each task goes through a defined lifecycle: understand → plan → scaffold → implement (TDD) → verify → review → PR. The human's only mandatory intervention is approving the PR.

## Why This Stage Matters

This is where code gets written. Without a disciplined execution flow, agents take shortcuts, drift from specs, skip tests, and produce code that looks right but breaks in production. The execution stage enforces proof-based development: every claim is backed by verifiable evidence.

## Core Concept: Proof-Based Development

Every agent action must produce verifiable proof. Not "I wrote tests" — the actual test output. Not "it matches the spec" — the actual spec alignment check result. Not "the UI looks right" — the actual screenshot.

This term is central to ODK's execution philosophy. It's what enables hands-off-keyboard development: the human reviews proofs, not code.

## Entry Criteria

- Tasks exist with dependency graph, `component_refs`, and `spec_refs` (from Stage 02)
- Sprint planned and approved
- All task dependencies resolved (upstream tasks merged)

## Exit Criteria (per task)

- All verifications pass (lint, types, tests, enforcements, spec alignment)
- External AI review completed with no blocking issues
- Proof artifacts collected and posted to task issue
- PR created with proof in description
- Human approved and merged

## The Task Lifecycle

```
odk task start <id>      → Claim + explore + read component_refs + post understanding to issue
odk task comment <id>       → Post implementation plan to issue
                         → Agent writes code (TDD: red → green → refactor)
odk task comment <id>   → Post progress updates throughout
odk verify run           → Run verifications (with --auto-fix, --retry, --repair as needed)
odk task done <id>       → Run ALL verifications → create PR with proof
                         → Human reviews → approves → merge
```

## Git Workflow

- Every task gets its own feature branch + git worktree
- Branch and worktree created automatically by `odk task start`
- Branch naming: `task/<task-id>-<short-description>` (conventional)
- Commit messages: conventional commits (enforced by pre-commit hook)
- Commit message format validated by commit-msg hook (installed by `odk init`)
- Worktree deleted automatically after task is done and PR merged
- NEVER work on main directly

## New Execution Features

### Auto-Fix
`odk verify run --auto-fix` runs `ruff --fix` before checking, automatically resolving common lint issues.

### Auto-Repair Loop
`odk verify run --retry N --repair` retries failed verifications up to N times, applying structured fixes between retries. The repair system parses verification error output and attempts targeted fixes.

### Verification Caching
Verification results are cached by content hash. If code hasn't changed since last verification, results are reused. Bypass with `--no-cache`. Clear cache with `odk verify clear-cache`.

### PR Commenting
`odk verify run --pr <URL>` posts verification results as a comment on the specified PR. Useful for CI integration and visibility.

### Commit-Message Hook
`odk init` installs a commit-msg hook that validates conventional commit format. Rejects commits that don't match `<type>(<scope>): <description>`.

### TDD Phase Tracking
`odk task tdd <id> --stage red|green|refactor` records the current TDD phase on a task for observability.

### Test Generation
`odk test generate --from <COMPONENT_ID>` generates test stubs from a component manifest. `odk test coverage` shows test coverage for all components.

## Aspects

Aspects are sub-topics loaded during execution as needed. The instructions.md tells you when to read each one.

| Aspect | File | When to read |
|---|---|---|
| Scaffolding | `aspects/scaffolding.md` | Task involves generating boilerplate |
| Testing Strategy | `aspects/testing-strategy.md` | Before writing any tests (always) |
| Verification | `aspects/verification.md` | Before running `odk task done` |
| Git Workflow | `aspects/git-workflow.md` | Understanding branch/worktree lifecycle |
| Code Review | `aspects/code-review.md` | Understanding the AI review process |
| Proof System | `aspects/proof-based-development.md` | Understanding proof artifacts |
| Spec Alignment | `aspects/spec-alignment.md` | Understanding drift detection |

## What to Read

1. Read this overview (you're here)
2. Read `glossary.md` for stage-specific terms
3. Read `instructions.md` and follow the steps
4. Read aspect files as directed by instructions.md
