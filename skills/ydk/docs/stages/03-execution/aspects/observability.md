# Observability

## How Progress Is Tracked

Every YDK command that changes task state automatically posts an update to the task issue. These updates are asynchronous — you don't wait for them. You call the command and continue working.

The task issue becomes a timeline of exactly what happened:

```
10:00 — ydk task start T-002
         "Exploration complete. Loaded orders.md#entities, found pattern
          at user_validator.py. 2 files to create, 0 to modify."

10:02 — ydk task comment T-002 "PLAN: 11 tests planned. TDD: write tests → implement validator →
          implement cancel logic. Estimated: 2 files, ~230 lines."

10:05 — ydk task comment T-002 "RED: 11 tests written, all failing"

10:12 — ydk task comment T-002 "GREEN: 7/11 passing"

10:18 — ydk task comment T-002 "GREEN: 11/11 passing"

10:19 — ydk task done T-002
         "All verifications pass. PR #47 created.
          ✓ Lint ✓ Types ✓ Tests (11) ✓ Enforce (3/3)"
```

You can see this timeline by:
- Opening the GitHub/GitLab issue in a browser
- Running `ydk task list` to see sprint status
- Looking at the project board (issues move between columns automatically)

## Sprint-Level Visibility

```bash
ydk task list
```

Shows all tasks in the current sprint:

```
Sprint 1: "Core order flow"

  T-001  Order entity + repo           done
  T-002  Order validation              done
  T-005  Unit tests validation         done
  T-003  Order service                 in-progress
  T-006  Integration tests             in-progress
  T-004  Order route                   open (depends: T-003)
  T-007  E2E tests                     open (depends: T-004)
  T-008  List endpoint                 blocked-by-decision
```

## Status Commands

```bash
ydk task list                 # List tasks in current sprint
ydk task ready                # List actionable tasks ranked by priority
ydk doctor                    # Check YDK environment health
```

## When Updates Are Posted

YDK posts to the task issue at these milestones — no more, no less:

| YDK Command | What gets posted |
|---|---|
| `ydk task start` | Exploration summary (spec refs loaded, files identified, dependencies verified) |
| `ydk task comment` | Implementation plan (files, tests, TDD sequence) |
| `ydk task comment` | Progress message (you provide the message) |
| `ydk task block` | Blocked reason + what's needed from human |
| `ydk task done` | Verification proof summary + PR link |
| `ydk task close` | Nothing posted — reconciles status only (see below) |
| `ydk task add-subtask` | New task created, linked to origin |

Labels are also updated automatically:
- `ydk task start` → adds `in-progress`
- `ydk task block` → adds `blocked-by-code` or `blocked-by-decision`, removes `in-progress`
- `ydk task done` → adds `in-review`, removes `in-progress`
- `ydk task close` → sets `done`, but only if the task's PR is actually merged; otherwise leaves status untouched. This is the only path to `done` — `ydk task done` never sets it directly, so run `ydk task close <id>` after the PR merges.

## What You See Without Any Extra Setup

If you're using GitHub:
- **Issues** show the full timeline of agent activity
- **Project board** (if configured) shows tasks in columns
- **Milestone** shows sprint progress percentage
- **PR** shows verification proof in description

No dashboards to set up. No monitoring tools to install. The platform you already use IS the observability layer.

## When to Check

**Hands-off mode:** Check `ydk task list` whenever you want. If no tasks are blocked, everything is proceeding.

**What needs your attention:**
- Tasks labeled `blocked-by-decision` — an agent needs your input
- Tasks that have been `in-progress` for longer than the configured timeout
- `ydk task list` and GitHub/GitLab issue labels show these

## What NOT to Do

- Don't set up a separate monitoring system — GitHub Issues is enough
- Don't poll continuously — check at natural breakpoints
- Don't interrupt agents with "what's your status?" — the issue timeline tells you
- Don't create observability overhead — 5-7 milestone updates per task is the right frequency
