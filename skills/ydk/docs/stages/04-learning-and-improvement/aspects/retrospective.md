# Retrospective

## Purpose

A sprint retrospective aggregates learnings across all tasks completed in a sprint. Individual task extractions capture micro-level knowledge; the retrospective identifies macro-level patterns: what keeps going wrong, what keeps working, what should change. Now includes procedural memory tracking — which approaches and prompts were effective.

## When to Run

Run a retrospective after every sprint completes — after the last task's PR is merged and before the next sprint's planning begins. The retrospective output directly informs the next sprint's priorities and approach.

## What Gets Aggregated

### What Shipped

A factual summary of completed tasks. Not a celebration — a record. Which tasks were planned, which actually shipped, and which were deferred or blocked.

### What Failed

Tasks that were blocked, timed out, or required multiple attempts. Understanding failure modes improves task decomposition and dependency management for the next sprint.

### Abandoned Approaches

Approaches tried and rejected across the sprint. Aggregated from individual task extractions with `abandoned` category. These represent collective negative knowledge — "things the team learned NOT to do."

### Repeating Patterns

Knowledge that appears across multiple tasks:

- **Common blockers** — if three tasks were blocked waiting for the same API, that dependency needs architectural attention.
- **Common gotchas** — if multiple agents hit the same issue, it should become a project rule.
- **Common structures** — if multiple tasks created the same file pattern, it should become a scaffold template.

### Contradictions Resolved

Memory contradictions detected and resolved during the sprint. Reviews whether the automatic resolution was correct and whether any need human correction.

### Velocity Indicators

How long tasks actually took versus estimates. Not for tracking individual performance — for improving task decomposition. If tasks consistently take 3x longer than expected, they're being scoped too large.

### Procedural Memory Analysis

`ydk memory audit` generates an effectiveness analysis across all sprint tasks:

- **Task type success rates** — which kinds of tasks (entity, route, test, integration) had the highest first-pass success rates
- **Pattern reuse** — which scaffold templates or approaches were reused most effectively
- **Auto-repair effectiveness** — how often `--retry --repair` resolved issues vs. manual fixes needed
- **Checkpoint preview value** — how many issues were caught by checkpoint preview that would have failed at `ydk task done`
- **TDD discipline** — correlation between strict TDD adherence and task success
- **Abandoned approach frequency** — which domains produce the most failed experiments (indicating spec gaps)

This analysis feeds directly into the next sprint's planning: adjust task decomposition, identify areas needing better specs, and refine execution strategies.

## The Process

### Step 1: Gather Data

```bash
ydk memory retrospective --sprint "Sprint 3"
```

This lists all completed tasks for the sprint and their outcomes, including extraction counts, contradictions, and abandoned approaches.

### Step 2: Search for Patterns

Use hybrid search to find cross-task patterns:

```bash
ydk memory search "blocked" --mode hybrid
ydk memory search "retry" --mode hybrid
ydk memory search "workaround" --mode hybrid
ydk memory search "abandoned" --mode hybrid
```

### Step 3: Generate Procedural Memory Report

```bash
ydk memory audit
```

Review the effectiveness analysis. Identify:
- Approaches that consistently work → reinforce in project rules
- Approaches that consistently fail → add to negative knowledge
- Task types that need better decomposition → adjust Stage 02 patterns

### Step 4: Update Project Knowledge

Based on retrospective findings:

- Add new project rules for repeated gotchas
- Add abandoned approaches to project rules as warnings
- Write ADRs for decisions that affected multiple tasks
- Create scaffold templates for repeated structures
- File discovery tasks for systemic issues
- Update research files that proved stale or inaccurate
- Record key decisions via `ydk memory record-decision TOPIC`

### Step 5: Consolidate and Re-index

After updating project files:

```bash
ydk memory consolidate    # Merge duplicate memories from the sprint
ydk memory index          # Re-index all project knowledge files
```

This ensures the next sprint's agents benefit from clean, consolidated, up-to-date knowledge.

## What the Agent Should Know

- The retrospective is a process, not just a command. `ydk memory retrospective` provides the data, but the analysis and follow-up actions require judgment.
- Retrospective findings should be concrete and actionable. "We should write better tests" is not actionable. "Unit tests for exchange adapters should include a disconnect simulation" is.
- The retrospective feeds directly into the next sprint's planning. Identified patterns become explicit task requirements or constraints.
- Procedural memory analysis (`ydk memory audit` with procedural analysis) is the key new capability — it tells you WHAT WORKS, not just what happened.
- Not every sprint needs a deep retrospective. If the sprint went smoothly and shipped as planned, a quick review of extracted memories plus the procedural report is sufficient.
- Abandoned approaches aggregated across the sprint are particularly valuable — they represent expensive lessons that should be preserved.
