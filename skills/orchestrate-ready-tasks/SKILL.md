---
name: orchestrate-ready-tasks
description: Spawn parallel orchestrator subagents for YDK ready tasks — each plans/builds/reviews via cavecrew, self-documents for resumability, and can later fix sibling-PR conflicts after a merge.
disable-model-invocation: true
---

# Orchestrate Ready Tasks

Explicit-invocation only (`/orchestrate-ready-tasks`). This skill spawns agents that create git worktrees, commit code, and open PRs — real side effects, not something that should fire on a fuzzy description match.

## 1. Pre-flight

1. `git fetch origin`
2. Run `ydk task ready` — this is the fresh candidate list. Zero results prints "No tasks found." and exits clean; that's not an error, just report nothing new to start.
3. Scan `.ydk/proofs/*/orchestrator-progress.md` for any task still `in-progress` (a previous orchestrator ran out of budget and documented state before stopping). These are resumable — treat them as part of the worklist even if they're not in the fresh `ydk task ready` output.

## 2. Build the worklist

Worklist = resumable in-progress tasks (from step 1.3) + fresh ready tasks (from step 1.2).

Cap concurrency at **4** orchestrators running at once. If the worklist has more than 4 items, take the first 4, and report the rest as queued (don't spawn them yet).

## 3. Spawn one orchestrator per worklist item

For each item, spawn one `general-purpose` Agent in parallel (not `cavecrew-builder`/`investigator`/`reviewer` for the orchestrator role itself — those agent types have no `Agent` tool in their frontmatter and structurally cannot spawn subagents; `general-purpose` is the confirmed correct choice, matching the `superpowers:dispatching-parallel-agents` precedent). Cap nesting at exactly one level: main thread → orchestrator → cavecrew leaves. Do not let an orchestrator spawn another orchestrator.

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
- **Plan**: self-plan, or spawn `cavecrew-investigator` for read-only "where is X" / "what calls Y" lookups.
- **Build**: spawn `cavecrew-builder` if the change is a surgical 1-2 file edit. Otherwise do it directly — the orchestrator has full tool access, no need to force a scope-mismatched agent.
- **Review**: spawn `cavecrew-reviewer` for a diff review. If findings are non-trivial, loop back to build and re-review.
- **Before running `ydk task done <id>`**: explicitly `git add` and commit the real implementation changes. `ydk task done` does **not** auto-commit uncommitted worktree changes before opening/updating the PR — confirmed across 5+ separate runs. Skipping this step ships an empty or near-empty PR while `ydk task done` still reports success.
- Run `ydk task done <id>`.
- Verify the result: `gh pr view <url> --json changedFiles,files,additions,deletions` and confirm the diff is non-trivial and matches the task's actual scope. If it looks empty or wrong, manually commit/push the real changes onto the PR branch and re-verify — don't just trust the tool's own "success" output.
- **Before context/token budget runs out** (if the task isn't finished yet): write `.ydk/proofs/<task-id>/orchestrator-progress.md` documenting exactly what's done, what's left, and any decisions made, and post `ydk task comment <id> "..."` with the same summary. This lets a fresh orchestrator resume cleanly later (see step 1.3 / the resuming-task branch above) instead of starting over or losing context.

## 4. Report back

One-line summary per task: task id, PR URL (or "skipped: already in progress" / "queued: concurrency cap"), and whether it's fresh/resumed/still-in-progress-documented.

## 5. Cleanup sub-flow: sibling-PR conflicts after a merge

This is a documented follow-up, not automatic — no merge-watching, no auto-merging (every merge still needs explicit human approval). Invoke this step when you're told something like "PR X merged, PRs Y and Z now have conflicts."

Root cause: `ydk task start`/`ydk task done` write shared bookkeeping (`.ydk/manifest.yaml`, `.ydk/tasks/<id>.md`) into each task's own branch. Since every parallel task branched off the same `origin/main`, every PR in the batch carries a diff to the same shared files — whichever merges first wins, the rest conflict against the new main tip. This is accepted as an expected side effect of running tasks in parallel, not something the spawn step tries to avoid up front.

For each conflicted PR, spawn one `general-purpose` fixer agent (scoped to avoid touching any other conflicted PR's branch/worktree in parallel with a sibling fixer):
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
