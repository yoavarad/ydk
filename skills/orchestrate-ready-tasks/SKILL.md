---
name: orchestrate-ready-tasks
description: Spawn parallel orchestrator subagents for YDK ready tasks — each plans/builds/reviews via cavecrew, self-documents for resumability, and can later fix sibling-PR conflicts after a merge.
disable-model-invocation: true
---

# Orchestrate Ready Tasks

Explicit-invocation only (`/orchestrate-ready-tasks`). This skill spawns agents that create git worktrees, commit code, and open PRs — real side effects, not something that should fire on a fuzzy description match.

## Model & effort per role

This skill exists to cut token spend, so every spawn picks the cheapest model/effort that still does the job:

| Role | Agent | Model / effort |
|---|---|---|
| Dispatch (this session) | main thread | session default — no `model` override, just spawns and reads reports |
| Per-task orchestrator | `ydk-orchestrator` | `sonnet` / `medium`; override to `model: opus` for L-tagged tasks (see step 2) |
| Builder | `cavecrew-builder` | always spawn with `model: sonnet` — drop to `haiku` only for a pure rename/typo. Never let it inherit the caller's model silently |
| Investigator | `cavecrew-investigator` | `haiku`, pinned in its own frontmatter — nothing to override |
| Reviewer | `cavecrew-reviewer` | `haiku` for a 1-2 file diff; spawn with `model: sonnet` above that |
| Conflict fixer | `ydk-conflict-fixer` | `sonnet` / `low` |

Install note: `ydk-orchestrator` and `ydk-conflict-fixer` are agent defs, not skill files — see the README's `cp skills/orchestrate-ready-tasks/agents/*.md ~/.claude/agents/` step. If either agent def isn't installed, fall back to `general-purpose` with the same per-call `model: sonnet` override (effort has no per-call override, so it just inherits the session's).

## 1. Pre-flight

1. `git fetch origin`
2. Run `ydk task ready` — this is the fresh candidate list. Zero results prints "No tasks found." and exits clean; that's not an error, just report nothing new to start.
3. Scan `.ydk/proofs/*/orchestrator-progress.md` for any task still `in-progress` (a previous orchestrator ran out of budget and documented state before stopping). These are resumable — treat them as part of the worklist even if they're not in the fresh `ydk task ready` output.

## 2. Build the worklist

Worklist = resumable in-progress tasks (from step 1.3) + fresh ready tasks (from step 1.2).

Cap concurrency at **4** orchestrators running at once. If the worklist has more than 4 items, take the first 4, and report the rest as queued (don't spawn them yet).

**Triage each item S/M/L** from the title/body already in context — no extra reads or calls just to tag it:
- **S** — one-liner or quickdev task, ≤2 files obvious from the description. Spawn one `ydk-orchestrator` that works inline (no cavecrew leaf spawns at all).
- **M** — default. Spawn `ydk-orchestrator` at its default model/effort.
- **L** — multi-file, unclear scope, or touches shared/critical code. Spawn `ydk-orchestrator` with `model: opus`. Effort stays at the def's `medium` — no per-spawn effort override exists, and Opus at medium is the chosen ceiling; a separate high-effort agent def isn't warranted yet.

Carry the tag into the step-4 report.

## 3. Spawn one orchestrator per worklist item

For each item, spawn one `ydk-orchestrator` Agent in parallel, with the per-call `model` override from its S/M/L triage tag. Cap nesting at exactly one level: main thread → orchestrator → cavecrew leaves. Do not let an orchestrator spawn another orchestrator, and note that `cavecrew-builder`/`investigator`/`reviewer` structurally can't spawn subagents either, so the orchestrator role itself can never be one of those types.

Give each orchestrator this procedure:

**If this is a fresh task (from `ydk task ready`):**
- `ydk task start <id> --base origin/main` — always pass `--base origin/main` explicitly. Never rely on the default (branches off current HEAD), which silently picks up whatever the main repo checkout happens to be sitting on — confirmed root cause of a messy PR earlier (stray files from an unrelated checked-out branch mixed into the diff).
- If this raises `ValueError: Task <id> is already in progress` (stale ready-list, or another process already claimed it), **skip it, report one line, move on.** Never pass `--force` automatically — force would blow away another agent's in-flight worktree, which isn't this orchestrator's call to make.

**If this is a resuming task (from the progress-file scan):**
- Read `.ydk/proofs/<id>/orchestrator-progress.md` first for prior state.
- `cd` into the existing worktree at `.ydk/worktrees/<task-id>` (it should already exist — don't re-run `ydk task start`).
- Continue from where the progress file says work left off.

**Every task, fresh or resumed:**
- `cd` into `.ydk/worktrees/<task-id>` for every subsequent git/build/`ydk` command. Never operate from the main repo root — doing so has produced empty PRs in the past (the commands ran against the wrong working tree).
- **Plan**: self-plan for S-tagged tasks. For M/L, spawn `cavecrew-investigator` only when a lookup would otherwise pull large reads into the orchestrator's own context (e.g. "where is X" / "what calls Y" across files it doesn't need to hold in full).
- **Build**: spawn `cavecrew-builder` with an explicit `model: sonnet` override if the change is a surgical 1-2 file edit and keeping the edit's context out of the orchestrator is worth the spawn (drop to `haiku` for a pure rename/typo). Otherwise do it directly — the orchestrator has full tool access, no need to force a scope-mismatched agent or spawn just to spawn.
- **Review**: spawn `cavecrew-reviewer` — `haiku` for a 1-2 file diff, `model: sonnet` above that. If findings are non-trivial, loop back to build and re-review, **capped at 2 rounds**. If still not clean after round 2, stop looping and document the leftover findings in the PR body and the progress file instead — a human reviews from there.
- **Before running `ydk task done <id>`**: explicitly `git add` and commit the real implementation changes. `ydk task done` does **not** auto-commit uncommitted worktree changes before opening/updating the PR — confirmed across 5+ separate runs. Skipping this step ships an empty or near-empty PR while `ydk task done` still reports success.
- Run `ydk task done <id>`.
- Verify the result: `gh pr view <url> --json changedFiles,additions,deletions` and confirm the diff is non-trivial and matches the task's actual scope. Only fetch `--json files` too if the counts alone look wrong (e.g. 0 changed files, or a count that doesn't match the task's scope) — the full file list is the expensive part. If it looks empty or wrong, manually commit/push the real changes onto the PR branch and re-verify — don't just trust the tool's own "success" output.
- Running tests: use `-q --tb=short` and read only the tail of the output (pass/fail summary + first failure), not the full scrollback.
- **Checkpoint after each phase** (plan, build, review) — not "when budget runs low," since an agent can't reliably sense its own remaining budget: write/update `.ydk/proofs/<task-id>/orchestrator-progress.md` with what's done so far and what's next. On stop or if the task ends unfinished, also post `ydk task comment <id> "..."` with the same summary, so a fresh orchestrator can resume cleanly (see step 1.3 / the resuming-task branch above) instead of starting over.

## 4. Report back

One-line summary per task: task id, S/M/L tag, PR URL (or "skipped: already in progress" / "queued: concurrency cap"), and whether it's fresh/resumed/still-in-progress-documented.

## 5. Cleanup sub-flow: sibling-PR conflicts after a merge

This is a documented follow-up, not automatic — no merge-watching, no auto-merging (every merge still needs explicit human approval). Invoke this step when you're told something like "PR X merged, PRs Y and Z now have conflicts."

Root cause: `ydk task start`/`ydk task done` write shared bookkeeping (`.ydk/manifest.yaml`, `.ydk/tasks/<id>.md`) into each task's own branch. Since every parallel task branched off the same `origin/main`, every PR in the batch carries a diff to the same shared files — whichever merges first wins, the rest conflict against the new main tip. This is accepted as an expected side effect of running tasks in parallel, not something the spawn step tries to avoid up front.

For each conflicted PR, spawn one `ydk-conflict-fixer` agent (scoped to avoid touching any other conflicted PR's branch/worktree in parallel with a sibling fixer). Note: a deterministic, no-LLM manifest-merge tool that would remove the need for this spawn entirely is tracked in task #229 — until that lands, this stays an LLM fixer:
1. `git fetch origin main`, then `git merge origin/main` into the PR's branch inside its worktree.
2. Resolve conflicts: on `.ydk/manifest.yaml` / task-status files, keep both sides' updates (don't drop either task's bookkeeping). On actual code, preserve the real intended logic from the PR's own commits.
3. Rebuild and re-run tests to confirm nothing broke.
4. Commit the merge, push.
5. Re-verify with `gh pr view --json mergeable,mergeStateStatus` that the PR is now clean.

## Known bugs reference

- **`ydk task done` doesn't auto-commit.** See step 3 above — always commit before running it, always verify the PR diff after.
- **`ydk task start`/`ydk task quick` default to branching off current HEAD, not a clean main.** Always pass `--base origin/main` explicitly on both commands.
- **`.ydk/manifest.yaml` conflicts between parallel PRs.** Expected, not a bug to prevent — see the cleanup sub-flow (step 5).
- **`pr-body-validation` verification plugin can replay a stale FAIL.** Its cache key is a hash of `*.py` files project-wide, not the actual plugin input, so it can replay an old failure regardless of current PR content. If a plugin result looks stale/wrong, clear `.ydk/cache/verification/pr-body-validation/` and retry. To skip a genuinely-failing plugin, pass its real plugin name to `--skip-plugin` (e.g. `pr-body-validation`) — not a requirement-key string that appears inside its output (e.g. `screenshot_for_ui` is a requirement key, not the plugin's name, and won't work as a skip target).
