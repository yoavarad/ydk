# Change Management

## UP-1: The Universal Principle

**Every change goes through a PR with explicit human approval.** No direct pushes to main. No auto-merges. No exceptions regardless of size. Code, specs, docs, config — everything.

This is the foundation of trust in ODK. If something landed in main, a human approved it.

## Why This Exists

Without UP-1:
- Agents push broken code directly to main
- Specs change without anyone noticing
- Config drifts without audit trail
- There's no point of review before code reaches production

With UP-1:
- Every change is reviewable
- The human sees proof artifacts before approving
- Git history is clean and traceable
- Rollback is always possible (revert the PR)

## The PR Flow

```
Feature branch → commits → push → PR → human reviews → approves → merge
```

### For code changes (Stage 03):

```
odk task start T-a1b2c3d4
  → creates branch: task/T-a1b2c3d4-order-validation
  → creates worktree: .odk/worktrees/T-a1b2c3d4/

Agent works in worktree...
  → commits with conventional messages (commit-msg hook validates format)

odk task done T-a1b2c3d4
  → runs ALL verifications
  → pushes branch
  → creates PR "Closes #T-a1b2c3d4"
  → posts proof to issue

Human reviews PR
  → sees proof table (lint, types, tests, spec-align)
  → reviews diff and proof artifacts
  → reviews diff
  → approves → merge → task closes
```

### For spec changes (Stage 01):

```
Agent brainstorms with human...
  → writes narrative files
  → creates component manifests
  → writes ADRs
  → updates project-rules.md

odk component validate         → Layer A linker validates references
odk spec verify --all-files     → AI evaluation passes (18 criteria including C17 density, C18 leakage)

Agent creates PR with narratives + component manifests + ADRs
  → Human reviews spec content
  → Approves → merge → specs are now source of truth
```

### For config changes:

```
odk config set spec_check.thresholds.completeness 9
  → modifies .odk/config.yaml
  → commit + push + PR
```

Even config changes go through PRs. No direct edits to main.

## Spec Evolution System

For lightweight spec modifications that don't warrant a full brainstorming cycle, ODK provides an OpenSpec-inspired delta spec system:

### Proposing Changes

```bash
odk change propose
# Interactive: describe the change, which spec sections are affected
# Creates a delta spec in docs/changes/<id>.md
```

Delta specs live in `docs/changes/` and describe:
- What is being changed and why
- Which narrative sections and component manifests are affected
- The proposed modifications
- Impact assessment (which tasks or stories are affected)

### Managing Changes

```bash
odk change list                    # List all proposed changes
odk change status <id>             # Check status of a specific change
odk change diff <id>               # Show what the change modifies (before/after)
odk change archive <id>            # Move completed change to docs/changes/archive/
```

### Change Lifecycle

```
odk change propose
  → creates docs/changes/<id>.md with proposed modifications
  → PR created for the change proposal

Human reviews and approves the change proposal
  → Agent applies the changes to narratives and component manifests
  → odk spec verify validates the updated specs
  → PR created with applied changes
  → Human reviews and approves

odk change archive <id>
  → moves docs/changes/<id>.md to docs/changes/archive/
  → change is complete
```

### When to Use Spec Evolution vs Full Brainstorming

| Situation | Approach |
|---|---|
| New system | Full brainstorming (Stage 01) |
| Major new feature | Full brainstorming (Stage 01, Major Feature mode) |
| Small behavior change | Full brainstorming (Stage 01, Small Change mode) OR spec evolution |
| Fix a spec error | Spec evolution (`odk change propose`) |
| Update an API contract | Spec evolution (`odk change propose`) |
| Add a missing error scenario | Spec evolution (`odk change propose`) |
| Change a technology choice | Full brainstorming (requires ADR + trade-off analysis) |

## Conventional Commits

All commit messages follow conventional commit format. Enforced by commit-msg hook (installed by `odk init`).

**Format:** `<type>(<scope>): <description>`

**Types:**
- `feat` — new feature
- `fix` — bug fix
- `docs` — documentation changes
- `refactor` — code restructuring without behavior change
- `test` — adding/modifying tests
- `chore` — tooling, config, dependencies

**Examples:**
```
feat(orders): implement order validation rules
fix(auth): handle expired JWT refresh tokens
docs(specs): add WebSocket streaming spec
test(orders): add E2E tests for cancel order
refactor(services): extract price calculation to separate module
chore(deps): upgrade SQLAlchemy to 2.1
```

The commit-msg hook validates format at commit time and rejects non-conforming messages immediately.

## Branch Naming

**Format:** `task/<task-id>-<short-description>`

**Examples:**
```
task/T-a1b2c3d4-order-validation
task/T-e5f6g7h8-unit-tests-validation
task/14-todo-model
```

Created automatically by `odk task start`. Never created manually.

## Spec Amendments

When the spec needs to change (discovered during implementation, new requirement):

1. **Lightweight change**: Use spec evolution — `odk change propose`, apply changes, PR
2. **Significant change**: Agent creates a new brainstorming session (Stage 01, Small Change or Major Feature mode)
   - Narrative files updated
   - Component manifests updated
   - `odk component validate` validates references
   - `odk spec verify` validates the amended specs
   - PR created with the spec diff
   - Human reviews and approves
3. Downstream tasks that reference amended spec sections or component manifests get flagged

Agents MUST NOT modify specs directly during implementation. Spec changes always go through either the spec evolution system or the brainstorming process.

## ADRs

Architecture Decision Records capture WHY decisions were made. Written immediately during brainstorming and execution — not deferred.

**Format:**
```markdown
# ADR-NNN: Decision Title

## Status
Accepted | Superseded by ADR-XXX

## Context
What situation prompted this decision?

## Decision
What was decided and why?

## Alternatives Considered
What else was considered and why rejected?

## Consequences
What changes as a result?
```

ADRs are append-only — superseded decisions are marked, never deleted. Future agents read ADRs to understand WHY the system is the way it is.

## What Goes Through a PR

| Change type | Must PR? | Verification before PR |
|---|---|---|
| Application code | Yes | Full verification (all layers) |
| Test code | Yes | Tests must pass |
| Narrative spec files | Yes | `odk spec verify` + `odk component validate` |
| Component manifests | Yes | `odk component validate` |
| ADRs | Yes | None (human reviews content) |
| project-rules.md | Yes | None (human reviews content) |
| .odk/config.yaml | Yes | `odk config validate` |
| Delta specs (docs/changes/) | Yes | Human reviews change proposal |
| Generated files | No — regenerated, not hand-edited | N/A |
| .odk/memory/ | No — derived index, gitignored | N/A |
| .odk/proofs/ | No — evidence files, gitignored | N/A |
| .odk/cache/ | No — verification cache, gitignored | N/A |
