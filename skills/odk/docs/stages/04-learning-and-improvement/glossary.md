# Stage 04: Learning and Improvement — Glossary

## Memory Engine

The core component that manages the knowledge base. Handles indexing project files into vectors, hybrid search (vector + BM25 + RRF), bootstrapping context for tasks, storing extracted memories with scoring and provenance, and detecting contradictions. Backed by ChromaDB for persistence and Bedrock for embeddings.

## Hybrid Search

The default search mode combining three strategies: vector similarity (semantic, via embeddings), BM25 keyword matching (exact terms), and Reciprocal Rank Fusion (RRF) to merge results into a single ranked list. Ensures both semantic and keyword matches are found.

## BM25

Best Matching 25 — a keyword-based ranking algorithm that scores documents by term frequency and inverse document frequency. Complements vector search by catching exact term matches that semantic search might miss.

## Reciprocal Rank Fusion (RRF)

A method for combining ranked lists from multiple search strategies into a single ranked result. Each result's score is based on its rank position across all lists, with a constant k to balance contributions. Used to merge vector and BM25 results.

## Vector Search

Finding documents by meaning rather than keywords. A query like "how to handle rate limiting" finds content about throttling, backoff, and retry logic — even if those exact words aren't in the query. Powered by embeddings.

## Embedding

A numerical representation of text that captures its meaning. Similar texts have similar embeddings. The memory system converts project knowledge into embeddings and stores them in ChromaDB, then converts queries into embeddings to find the closest matches.

## Memory Score

A composite relevance score (0.0-1.0) computed from 4 factors: category weight (0.50), provenance (0.15), recency (0.25), access frequency (0.10). Memories are ranked by this score during search and bootstrap.

## Scoring Decay

Recency-based decay with a 30-day half-life. A memory's recency component halves every 30 days since creation or last access. Ensures recent knowledge surfaces over stale knowledge.

## Provenance

Source reliability tracking on every memory. Two fields:
- `source_type`: `user-stated` (human said it), `llm-extracted` (extracted from transcript), `agent-discovered` (agent found it during task), `verified` (confirmed by test/evidence)
- `verified`: boolean flag — set when a memory has been independently confirmed

Higher provenance contributes to a higher memory score.

## Negative Knowledge

Memories with extraction type `abandoned` — approaches that were tried and rejected. Contains what was attempted, why it failed, and what was done instead. Prevents future agents from repeating failed experiments.

Example: "Tried using Redis Streams for order events — abandoned because message ordering guarantees require consumer groups which add complexity disproportionate to our scale."

## Contradiction Detection

Automatic detection when a new memory contradicts an existing one. The old memory is marked with `superseded_by` pointing to the new memory's ID and its score is suppressed. Runs on every memory write (both extraction and manual creation).

## Decision Memory

Topic-keyed, append-only decision log. `odk memory record-decision TOPIC` records a decision associated with a topic string. Multiple decisions for the same topic are stored chronologically; the latest entry wins when queried. Provides a complete decision history per topic.

## Progressive Retrieval

Search with controlled depth to manage context window usage:
- `depth=index` — returns titles, IDs, scores, and source info only
- `depth=summary` — returns key points and summaries
- `depth=full` — returns complete memory content

Use `get_memory_details(ids)` to retrieve full content for specific memories identified during index-level search.

## Temporal Validity

Optional time bounds on memories:
- `valid_from` — memory is not surfaced before this timestamp
- `valid_until` — memory is auto-filtered after this timestamp

Useful for time-bound knowledge: API deprecation dates, temporary workarounds, seasonal behaviors. Expired memories are not deleted — they're filtered from search results but retained for audit.

## Consolidation

`odk memory consolidate` merges duplicate or near-duplicate memories into single authoritative entries. Uses embedding similarity to find candidates, then an LLM to merge content while preserving all unique information. Reduces noise and context window waste.

## Procedural Memory

Tracks which prompts, patterns, and approaches were effective across tasks. `odk memory audit` includes procedural effectiveness analysis: which task types succeeded, which patterns were reused, which approaches were abandoned. Feeds into process improvement.

## Extraction

The process of reading a completed task's session transcript and identifying learnings worth remembering: discoveries about external APIs, design decisions with rationale, implementation gotchas, repeating patterns, and **abandoned approaches**. Runs automatically after `odk task done` when configured.

## Bootstrap

Assembling relevant context for a new task before the agent starts working. Combines hybrid search results (ranked by memory score) with spec references and component manifests to give the agent a head start. Runs automatically during `odk task start` when configured.

## Retrospective

An aggregation pass across all tasks in a completed sprint. Identifies what shipped, what failed, which patterns repeat, and what should change for the next sprint. Now includes procedural memory analysis. Produces actionable insights, not a status report.

## ChromaDB

The vector database used for persistent storage of knowledge embeddings. Stores document chunks with metadata (source file, section, type, score, provenance, temporal validity) and enables fast semantic search. Lives at `.odk/memory/chroma/` by default.

## Knowledge Collection

A logical grouping of memories within ChromaDB. Keeps different types of knowledge organized: specs, ADRs, research, extracted learnings. Each collection can be searched independently or together.
