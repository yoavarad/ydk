# Stage 03: Execution — Glossary

## Proof-Based Development

The principle that every agent claim must be backed by verifiable evidence. Test results, linter output, screenshots, spec alignment reports — not the agent's word. This is what enables hands-off-keyboard development.

## Proof Artifact

A file (JSON, image, text) that captures the output of a verification check. Stored in `.ydk/proofs/<task-id>/`. Posted to the task issue and attached to the PR.

## Worktree

An isolated git working directory for an agent. Created by `ydk task start`, linked to a feature branch, deleted after the task's PR is merged. Agents working on parallel tasks each have their own worktree — no file conflicts.

## Feature Branch

A git branch for one task. Naming convention: `task/<task-id>-<short-description>`. Created with the worktree, merged via PR, deleted after merge.

## Conventional Commit

Commit message format: `<type>(<scope>): <description>`. Types: feat, fix, refactor, test, docs, chore. Enforced by both pre-commit hook and commit-msg hook (installed by `ydk init`). The commit-msg hook validates format and rejects non-conforming messages.

## Red-Green-Refactor

TDD cycle: write a failing test (Red), write minimum code to pass it (Green), clean up without changing behavior (Refactor). Mandatory for all implementation in YDK.

## Spec Alignment

Verification that the implementation matches the spec. An LLM evaluator compares code against spec sections (narratives + component manifests) across 6 dimensions: entity accuracy, interface compliance, error handling, boundary respect, scope compliance, cross-cutting adherence.

## Deterministic Enforcement

Rule-based checks that don't require AI: AST pattern matching, regex scans, file existence checks. Examples: no float for financial values, no future annotations in route files.

## AI Code Review

External agent(s) that review the diff before PR creation. Not self-review — independent agents with different perspectives (security, spec compliance, quality).

## Verification Trigger

A named trigger that determines when verification plugins run: `git:pre-commit` (fast lint/types), `git:pre-push` (full verification including tests, enforcements, and AI checks). Plugins declare which triggers they respond to in their manifest. Use `--trigger` flag to filter: `ydk verify run --trigger pre-commit`.

## Auto-Fix

`ydk verify run --auto-fix` runs `ruff --fix` before checking, automatically resolving common formatting and lint issues before verification evaluates them.

## Auto-Repair Loop

`ydk verify run --retry N --repair` automatically retries failed verifications up to N times. Between retries, the repair system parses structured error output and attempts targeted fixes. Useful for fixing cascading lint/type issues.

## Verification Cache

Content-hash based caching of verification results. If the content hash of checked files hasn't changed since the last verification run, cached results are reused instead of re-running the check. Bypass with `--no-cache`. Clear with `ydk verify clear-cache`.

## TDD Phase Tracking

`ydk task tdd <id> --stage red|green|refactor` records the current TDD phase on a task. Stored in task frontmatter for observability.

## Commit-Message Hook

A git hook installed by `ydk init` that validates commit messages match conventional commit format (`<type>(<scope>): <description>`). Rejects non-conforming commits at commit time.

## Time-Box

Maximum duration for a task. If exceeded, the agent must stop, report progress, and escalate. Configured in `.ydk/config.yaml` under `execution.task_timeout_minutes`.

## Watch System

Background polling daemon that monitors GitHub PRs for new review comments. Installed via `ydk watch install` as a macOS launchd plist that triggers `ydk watch poll` every 30 seconds. Detects new comments, reacts with 👀, and resumes the corresponding Claude Code session.

## Session Tracking

The `.ydk/sessions.yaml` file that maps task IDs to their branch, PR number, worktree path, and session state. Used by the watch system to find the correct session to resume.

## Agent Reply Marker

The HTML comment `<!-- ydk-agent-reply -->` placed on the first line of agent replies to PR review comments. The watch system filters comments starting with this marker to avoid re-triggering on the agent's own replies.

## Collapsible PR Body

The PR description format where each verification result is wrapped in a `<details>` block. Reviewers see a clean summary and can expand individual sections to inspect raw terminal output. Assembled by `PRBodyBuilder` from proof files.
