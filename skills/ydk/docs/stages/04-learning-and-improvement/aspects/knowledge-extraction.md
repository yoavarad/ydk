# Knowledge Extraction

## What Gets Extracted

When a task completes, the extraction system reads the raw Claude Code session transcript (JSONL) and identifies knowledge worth preserving. It looks for five categories:

### Discoveries

Facts the agent learned during implementation that weren't in the spec or project rules. External API behaviors, library quirks, infrastructure constraints.

*Example:* "Binance WebSocket API disconnects after 24 hours regardless of activity — need reconnection logic."

### Decisions

Choices made during implementation with their rationale. Why one approach was chosen over another. These often become ADR candidates.

*Example:* "Used Decimal instead of float for order amounts — precision loss at 8 decimal places caused rounding errors in tests."

### Gotchas

Problems encountered that future agents should know about. Things that look right but break in subtle ways.

*Example:* "PostgreSQL NOTIFY payload has a maximum length of 8000 bytes — large order updates must be truncated or sent as references."

### Patterns

Recurring structures or approaches that worked well. These often become scaffold template candidates.

*Example:* "Every exchange adapter follows the same structure: connection manager, message parser, retry handler, health check."

### Abandoned (Negative Knowledge)

Approaches that were tried and rejected. This is high-value knowledge — it prevents future agents from repeating failed experiments and wasting time on known dead ends.

*Example:* "Tried using asyncio.gather for parallel order processing — abandoned because concurrent balance updates cause race conditions. Must use sequential processing with row-level locking (SELECT FOR UPDATE)."

Each abandoned memory includes:
- **What was attempted**: the approach or technique tried
- **Why it failed**: the specific failure mode or limitation
- **What was done instead**: the successful alternative (if found)

## How Extraction Works

1. The session JSONL contains every message exchanged during the task: user prompts, agent responses, tool calls, tool results.

2. The extractor reads the full transcript and identifies passages where the agent encountered something noteworthy — error messages that led to insights, decision points with trade-off analysis, unexpected behaviors that required workarounds, and approaches that were tried and abandoned.

3. Each identified learning is:
   - Summarized and categorized (discovery/decision/gotcha/pattern/abandoned)
   - Tagged with the source task ID
   - Assigned provenance: `llm-extracted` by default, `agent-discovered` if the agent explicitly noted it
   - Given temporal validity if time-bound (e.g., "API v2 available until June 2026")

4. The learnings are stored in ChromaDB with embeddings, making them searchable by future agents via `ydk memory search` or `ydk memory bootstrap`.

5. **Contradiction detection runs on write.** For each new memory, the system checks existing memories for contradictions. If found, the old memory is marked `superseded_by` the new one. This happens automatically — no manual intervention needed.

## Provenance Assignment

Extracted memories are assigned provenance based on how they were identified:

| How Identified | Provenance |
|---|---|
| Agent explicitly stated "I discovered X" or wrote it to project rules | `agent-discovered` |
| LLM extractor identified it from transcript patterns | `llm-extracted` |
| Human stated it in the conversation | `user-stated` |
| Confirmed by test output or evidence in the transcript | `verified` |

Higher provenance contributes to a higher memory score, making the memory more likely to surface in future searches.

## When Extraction Runs

- **Automatically:** After `ydk task done` when `memory.auto_extract: true` in config. The system looks for the session JSONL at `.ydk/sessions/<task-id>.jsonl`.

- **Manually:** `ydk memory extract T-a1b2c3d4 --jsonl /path/to/session.jsonl` for cases where the JSONL is saved elsewhere or auto-extract was disabled.

## Contradiction Detection on Write

Every time a memory is written (extracted or manually created), the system:

1. Searches for semantically similar existing memories (similarity > `contradiction_threshold`, default 0.85)
2. For each similar memory, uses an LLM to evaluate: "Does the new memory contradict the existing one?"
3. If contradiction detected:
   - Old memory gets `superseded_by: <new_memory_id>`
   - Old memory's score is suppressed (recency weight set to 0)
   - Both memories are retained for audit
   - A log entry records the contradiction

**Example flow:**
```
1. Existing memory: "Binance WebSocket reconnects automatically after disconnect"
2. New extraction: "Binance WebSocket does NOT reconnect — must implement reconnection manually"
3. Contradiction detected → old memory marked superseded
4. Future search for "Binance WebSocket" returns only the corrected memory
```

## What the Agent Should Know

- Not every task produces extractable learnings. Simple refactoring or test additions may not generate discoveries. Zero extractions is a valid outcome.
- Extraction reads the raw transcript, including failed attempts and dead ends. These are often the most valuable learnings — what NOT to do. The `abandoned` category explicitly captures these.
- Extracted memories are approximate. The agent that produced them was focused on implementation, not documentation. Review extractions when the output matters for important decisions.
- The extraction process itself does not modify any project files. It only adds entries to the ChromaDB knowledge base. To turn a discovery into a project rule or ADR, that's a separate manual step.
- Contradiction detection runs automatically. If an extraction contradicts an existing memory, the old one is superseded. This is usually correct, but human review is the final arbiter.
- Abandoned approaches are high-value extractions. If a future agent's bootstrap includes an `abandoned` memory, it should seriously consider that approach as a dead end before retrying it.
