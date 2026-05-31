# Stage 04: Learning and Improvement — Overview

## What This Stage Does

After tasks ship and sprints complete, the project accumulates knowledge: what worked, what didn't, which patterns repeat, which decisions paid off. Stage 04 captures that knowledge, indexes it for retrieval, and feeds it back into future work. Without it, every sprint starts from scratch. With it, agents get smarter over time.

## Why This Stage Matters

Agents are stateless between sessions. Everything an agent discovered during a task — API quirks, performance gotchas, design decisions — vanishes when the session ends. Stage 04 solves this by extracting learnings from completed work and storing them in a searchable knowledge base. The next agent starting a related task gets bootstrapped with the relevant context automatically.

This is not about documentation for humans. It is about operational memory for agents.

## Core Concept: Project Memory

The project accumulates three kinds of knowledge:

1. **Explicit knowledge** — specs, ADRs, project rules, research files. Written by humans or agents intentionally. Already exists as files in the repo.

2. **Extracted knowledge** — discoveries, decisions, gotchas, patterns, and **abandoned approaches** pulled from completed task transcripts. The agent didn't write these down; the extraction process identifies and stores them.

3. **Aggregated knowledge** — patterns visible only across multiple tasks. "Every Binance endpoint needs retry logic" is not visible in one task but becomes obvious across five.

Stage 04 handles all three: indexing explicit knowledge, extracting from transcripts, and aggregating across sprints.

## Memory Scoring & Decay

Every memory has a relevance score computed from 4 factors:

| Factor | Weight | Description |
|---|---|---|
| Category | 0.50 | Extraction type: gotcha > decision > discovery > pattern > abandoned |
| Provenance | 0.15 | Source reliability: verified > user-stated > agent-discovered > llm-extracted |
| Recency | 0.25 | Time since creation/last access. 30-day half-life decay. |
| Access frequency | 0.10 | How often this memory has been retrieved |

Memories are ranked by this composite score during search and bootstrap. Low-scoring memories sink; high-scoring ones surface.

## Hybrid Search

The default search mode combines three strategies:

1. **Vector similarity** — semantic search via embeddings (ChromaDB)
2. **BM25 keyword matching** — traditional keyword search for exact term matches
3. **Reciprocal Rank Fusion (RRF)** — merges results from both strategies into a single ranked list

This means `odk memory search "rate limiting"` finds content about throttling AND content that literally mentions "rate limiting" — the best of both worlds.

## Key Capabilities

### Negative Knowledge
Extraction type `abandoned` captures approaches that were tried and rejected. Future agents see "we tried X and it failed because Y" — preventing them from repeating failed experiments.

### Provenance Tracking
Every memory has `source_type` (user-stated, llm-extracted, agent-discovered, verified) and a `verified` flag. Higher provenance = higher score = more likely to surface in search.

### Decision Memory
`odk memory record-decision TOPIC` records topic-keyed decisions in an append-only log. Latest entry wins. When searching for "how do we handle X?", the most recent decision is returned.

### Contradiction Detection
When a new memory contradicts an existing one, the old memory is auto-invalidated with a `superseded_by` reference. Prevents stale knowledge from persisting alongside newer corrections.

### Progressive Retrieval
Search with `depth=index|summary|full` to control how much detail is returned. Start with `index` (titles + scores), drill into `summary` (key points), then `full` (complete content). Use `get_memory_details(ids)` for targeted full retrieval.

### Temporal Validity
Memories can have `valid_from` and `valid_until` timestamps. Expired memories are auto-filtered from search results. Useful for time-bound knowledge like "API v2 is deprecated after 2026-06-01".

### Consolidation
`odk memory consolidate` merges duplicate or near-duplicate memories into single authoritative entries. Reduces noise and context window waste.

### Procedural Memory
`odk memory audit` includes procedural effectiveness analysis — tracking which prompts, approaches, and patterns were effective across tasks.

## Entry Criteria

- At least one task completed (for extraction)
- Sprint completed (for retrospective)
- Or: project files changed (for re-indexing)

## Exit Criteria

- Knowledge base indexed and up to date
- Extracted learnings stored from completed tasks (including abandoned approaches)
- Retrospective completed for the sprint
- Stale/redundant entries flagged
- Contradictions resolved
- Project rules updated with new learnings
- ADRs written for decisions made during execution

## The Learning Loop

```
odk memory index              → Index all project knowledge files into ChromaDB
odk memory search <query>     → Hybrid search (vector + BM25 + RRF) with scoring
odk memory extract T-xxx      → Extract learnings (discoveries, decisions, gotchas, abandoned)
odk memory record-decision TOPIC → Record topic-keyed decision (append-only, latest-wins)
odk memory retrospective      → Aggregate learnings across a sprint
odk memory consolidate        → Merge duplicate memories
odk memory audit              → Comprehensive health audit (stale research, duplicates, procedural reports)
odk memory bootstrap T-xxx    → Assemble context for a new task automatically
```

## Automatic Integration

When configured (`memory.auto_bootstrap: true` and `memory.auto_extract: true`):

- `odk task start` automatically bootstraps relevant memories for the new task (using hybrid search with scoring)
- `odk task done` automatically extracts learnings from the completed task (including abandoned approaches)
- Contradiction detection runs automatically on every memory write

This means the learning loop runs without explicit invocation — agents benefit from past knowledge and contribute new knowledge as a side effect of normal task execution.

## Aspects

Aspects are sub-topics loaded as needed. The instructions.md tells you when to read each one.

| Aspect | File | When to read |
|---|---|---|
| Memory System | `aspects/memory-system.md` | Understanding how indexing, scoring, hybrid search, and retrieval work |
| Knowledge Extraction | `aspects/knowledge-extraction.md` | Understanding what gets extracted from transcripts (including abandoned approaches and contradictions) |
| Retrospective | `aspects/retrospective.md` | Running a sprint retrospective with procedural memory tracking |

## What to Read

1. Read this overview (you're here)
2. Read `glossary.md` for stage-specific terms
3. Read `instructions.md` and follow the steps
4. Read aspect files as directed by instructions.md
