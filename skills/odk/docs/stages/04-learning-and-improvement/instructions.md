# Learning and Improvement

## Overview

Capture, index, and reuse knowledge from completed work. Every sprint and every task contributes to the project's collective memory. The goal: agents working on future tasks start with the accumulated wisdom of all past work, not from zero.

The memory system now features scored ranking with decay, hybrid search (vector + BM25 + RRF), negative knowledge (abandoned approaches), provenance tracking, contradiction detection, progressive retrieval, temporal validity, consolidation, and procedural memory.

## Parameters

- **sprint** (optional): Sprint/milestone identifier for scoped retrospectives
- **task_id** (optional): Specific task for targeted extraction or bootstrap
- **project_root** (required): Detected automatically from `.odk/` location

## Steps

### 1. Index Knowledge

Update the ChromaDB index from all project knowledge files: specs (narratives + component manifests), ADRs, research, project rules.

**Constraints:**
- You MUST run `odk memory index` after adding or modifying any knowledge file
- Indexing is idempotent — running it multiple times is safe
- Index covers: `docs/specs/`, `.odk/components/`, `docs/adrs/`, `docs/research/`, `docs/project-rules.md`
- Large files are chunked automatically; sections become individually searchable
- Component manifests are indexed with their `odk:` IDs as metadata, enabling search by component reference

**When to run:**
- After sprint planning (specs may have been updated)
- After any task that adds ADRs or research files
- Before a retrospective (ensures search is current)

**Example:**

```bash
odk memory index
# Indexed 24 files (12 narratives, 8 component manifests, 4 ADRs)
#   Chunks created: 96
#   Skipped: 0
```

### 2. Review Extractions

After tasks complete, the extraction system identifies learnings from the session transcript. Review what was extracted.

**Constraints:**
- Extraction runs automatically after `odk task done` when `memory.auto_extract: true`
- You SHOULD review extracted memories for accuracy
- You MUST correct or remove any misidentified learnings
- Extraction targets: discoveries, decisions, gotchas, patterns, **abandoned approaches** (negative knowledge)
- Each extracted memory gets: category, provenance (`llm-extracted` by default), temporal validity (if applicable)
- Contradiction detection runs automatically — new memories that contradict existing ones auto-invalidate the old entry

**Read `aspects/knowledge-extraction.md` for details on what gets extracted.**

**Manual extraction (if auto-extract is disabled or a session JSONL was saved elsewhere):**

```bash
odk memory extract T-a1b2c3d4 --jsonl /path/to/session.jsonl
# Extracted 4 memories from T-a1b2c3d4:
#   - [gotcha] Binance returns 418 for IP bans (provenance: agent-discovered)
#   - [decision] Used Decimal for all financial amounts (provenance: agent-discovered)
#   - [pattern] All exchange adapters need retry with exponential backoff (provenance: llm-extracted)
#   - [abandoned] Tried asyncio.gather for parallel orders — race condition on balance (provenance: agent-discovered)
# Contradiction detected: memory #42 (old rate limit info) auto-invalidated by new extraction
```

### 3. Record Decisions

For significant decisions made during the sprint, record them as topic-keyed decision memories.

**Constraints:**
- You SHOULD record decisions that affect future tasks using `odk memory record-decision TOPIC`
- Decisions are append-only: latest entry for a topic wins
- The decision history for a topic is always available — nothing is lost

**Example:**

```bash
odk memory record-decision "order-validation-strategy" \
  --body "Validate orders at the domain layer using a dedicated validator class. Service layer calls validator before persisting. Route layer only does HTTP-level validation (request shape)."
# Decision recorded for topic: order-validation-strategy
# This is decision #2 for this topic (previous: validate in service layer)
```

### 4. Sprint Retrospective

After a sprint completes, aggregate learnings across all tasks.

**Constraints:**
- You SHOULD run a retrospective after every sprint
- The retrospective identifies what shipped, what patterns emerged, and what should change
- Retrospective output feeds into the next sprint's planning
- The retrospective now includes procedural memory analysis (which approaches worked best)

**Read `aspects/retrospective.md` for the full retrospective process.**

**Example:**

```bash
odk memory retrospective --sprint "Sprint 3"
# Sprint Retrospective — Sprint 3
#   Tasks completed: 8
#   Memories extracted: 23
#   Contradictions resolved: 2
#   Abandoned approaches: 3
#   Procedural insights:
#     - TDD-first approach succeeded in 7/8 tasks (87.5%)
#     - Auto-repair resolved 12 lint issues across 5 tasks
#     - Checkpoint preview caught 2 issues before human review
```

### 5. Consolidate Memories

Merge duplicate or near-duplicate memories to reduce noise.

**Constraints:**
- You SHOULD run `odk memory consolidate` after sprints with many extractions
- Consolidation merges similar memories while preserving all unique information
- The merged memory retains the highest provenance and most recent timestamp
- Consolidation is non-destructive — originals are marked as `consolidated_into`

**Example:**

```bash
odk memory consolidate
# Found 4 consolidation candidates:
#   - Merged 2 memories about Binance rate limiting → 1 authoritative entry
#   - Merged 2 memories about Decimal precision → 1 authoritative entry
# Consolidated: 4 → 2 (saved 2 duplicate entries)
```

### 6. Audit

Find stale research, redundant entries, contradictions, and knowledge that may need updating.

**Constraints:**
- You SHOULD run `odk memory audit` at the start of each sprint
- Research files older than 90 days are flagged as stale (external APIs change)
- Expired temporal memories are flagged
- Unresolved contradictions are surfaced
- Flagged items need human decision: update, archive, or keep as-is
- You MUST NOT auto-delete flagged items

**Example:**

```bash
odk memory audit
# Memory Audit
#   Stale research (2 files older than 90 days):
#     - docs/research/binance-ws-api.md (last modified 112 days ago)
#     - docs/research/redis-streams.md (last modified 95 days ago)
#   Expired temporal memories: 1
#     - "API v2 endpoint available" (valid_until: 2026-03-01)
#   Low-score memories (below 0.2): 3
#     - Consider consolidating or archiving
```

### 7. Template Discovery

Identify repeating implementation patterns across completed tasks. If the same structure appears three or more times, it should become a scaffold template.

**Constraints:**
- You SHOULD review completed tasks for structural patterns after each sprint
- A pattern qualifies as a template when 3+ tasks used the same file structure
- New templates go in `.odk/templates/`
- Template creation is a task itself — create a discovery task with `odk task add-subtask`

**Example patterns to look for:**
- Same set of files created across multiple tasks (route + service + tests)
- Same error handling shape repeated
- Same validation structure applied to different entities

### 8. Update Project Rules

Refine `docs/project-rules.md` from learnings accumulated during execution.

**Constraints:**
- You MUST add any gotchas discovered during execution to project rules
- You MUST update rules that proved wrong or incomplete
- You MUST NOT remove rules without documenting why (use an ADR)
- Project rules are the first thing an agent reads — keep them actionable

**What belongs in project rules:**
- External API quirks ("Binance returns 418 in addition to 429")
- Codebase conventions not enforced by linters ("all financial values use Decimal")
- Known limitations ("maximum 10 concurrent WebSocket connections")
- Patterns that should always be followed ("all adapters implement retry with backoff")
- Abandoned approaches and why ("do NOT use asyncio.gather for parallel orders — race condition on balance")

### 9. Update ADRs

Document architectural decisions made during execution.

**Constraints:**
- You MUST write an ADR for any decision with long-term consequences
- ADR format: title, status, context, decision, consequences
- ADRs go in `docs/adrs/` with sequential numbering
- ADRs are immutable once accepted — to change a decision, write a new ADR that supersedes it

**Examples of decisions that need ADRs:**
- Choosing a library over building custom
- Changing the data model
- Adding a new integration point
- Changing the error handling strategy

### 10. Procedural Memory Report

Procedural effectiveness analysis is now included as part of `odk memory audit`. The audit command provides a comprehensive health check including stale research, duplicates, and procedural reports.

**Constraints:**
- You SHOULD run `odk memory audit` after each sprint
- The audit includes: stale research files, expired temporal memories, low-score memory candidates, and procedural effectiveness analysis
- Use the report to refine task decomposition and execution strategies for the next sprint

## Troubleshooting

### Index fails with "chromadb not installed"
ChromaDB is an optional dependency. Install it with: `uv pip install 'odk[memory]'`

### Extraction finds nothing useful
Not every task produces extractable learnings. Simple tasks (pure refactoring, adding a test) may not generate discoveries. This is fine.

### Research file flagged as stale but still valid
The 90-day threshold is a heuristic. If the content is still accurate, touch the file to update its modification time, or ignore the warning.

### Bootstrap returns irrelevant results
The quality of bootstrap depends on the quality of the index and the memory scores. Run `odk memory index` to ensure the index is current, check that spec refs and component_refs on the task are accurate, and run `odk memory consolidate` to reduce noise from duplicates.

### Contradiction detection seems wrong
Review both the old and new memory. If the old memory is actually still valid, manually restore it. Contradiction detection uses semantic similarity — it may flag near-misses. Human judgment is the final arbiter.

### Too many low-score memories cluttering results
Run `odk memory consolidate` to merge duplicates, then `odk memory audit` to identify candidates for archiving.
