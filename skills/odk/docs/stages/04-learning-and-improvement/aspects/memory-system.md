# Memory System

## How It Works

The memory system turns your project's knowledge files into a searchable, scored knowledge base. When an agent needs context — starting a new task, looking up a past decision, understanding an API quirk — it queries the memory system using hybrid search (vector + BM25 + RRF), with results ranked by a 4-factor relevance score.

## Architecture

**Storage:** ChromaDB, a lightweight vector database that persists to disk at `.odk/memory/chroma/`. No external services required for storage.

**Embeddings:** Generated via Amazon Bedrock using the configured embedding model (default: `cohere.embed-english-v3`). Each text chunk becomes a high-dimensional vector that captures its semantic meaning.

**Keyword Index:** BM25 index maintained alongside the vector store for keyword-based matching. Updated automatically during `odk memory index`.

**Collections:** Knowledge is organized into logical collections within ChromaDB. Specs, ADRs, research, component manifests, and extracted learnings each get their own collection, enabling scoped or cross-collection searches.

## Indexing

`odk memory index` reads all knowledge files from configured locations:

- `docs/specs/` — narrative specification documents
- `.odk/components/` — component manifests (indexed with `odk:` IDs as metadata)
- `docs/adrs/` — architectural decision records
- `docs/research/` — cached research on external technologies
- `docs/project-rules.md` — project conventions and gotchas

Each file is split into chunks (by markdown sections or YAML documents where possible). Each chunk gets an embedding and is stored with metadata: source file, section heading, file type, last modified date, `odk:` ID (for manifests).

Indexing is idempotent. Running it again updates changed files and skips unchanged ones. Deleted files are removed from the index.

## Memory Scoring

Every memory has a composite relevance score computed from 4 factors:

```
score = (category_weight * 0.50) + (provenance_weight * 0.15) + (recency_weight * 0.25) + (access_weight * 0.10)
```

### Category Weight (0.50)

Based on the memory's extraction type:

| Category | Weight | Rationale |
|---|---|---|
| gotcha | 1.0 | Critical — prevents bugs and wasted time |
| decision | 0.9 | Important — guides architectural choices |
| discovery | 0.7 | Useful — provides context |
| pattern | 0.6 | Helpful — suggests approaches |
| abandoned | 0.8 | High value — prevents repeating failed experiments |

### Provenance Weight (0.15)

Based on how the memory was created:

| Source Type | Weight | Description |
|---|---|---|
| verified | 1.0 | Confirmed by test, evidence, or human review |
| user-stated | 0.9 | Human explicitly said it |
| agent-discovered | 0.7 | Agent found it during task execution |
| llm-extracted | 0.5 | Extracted from transcript by LLM (approximate) |

The `verified` flag on a memory upgrades its provenance to 1.0 regardless of `source_type`.

### Recency Weight (0.25)

Time-based decay with a 30-day half-life:

```
recency_weight = 0.5 ^ (days_since_last_access / 30)
```

A memory accessed today has weight 1.0. After 30 days: 0.5. After 60 days: 0.25. After 90 days: 0.125.

The clock resets on every access — frequently retrieved memories stay relevant.

### Access Weight (0.10)

Based on how often the memory has been retrieved:

```
access_weight = min(access_count / 10, 1.0)
```

Caps at 10 accesses. A memory retrieved 10+ times gets full access weight.

## Hybrid Search

`odk memory search <query>` runs three search strategies and merges results:

### 1. Vector Similarity Search

Converts the query into an embedding and finds the most similar chunks in ChromaDB. Captures semantic meaning — "how to handle rate limiting" finds content about throttling and backoff.

### 2. BM25 Keyword Search

Traditional keyword matching using term frequency and inverse document frequency. Captures exact term matches — "asyncpg" finds content mentioning that exact library name, even if the vector search would miss it due to semantic distance.

### 3. Reciprocal Rank Fusion (RRF)

Merges the ranked lists from vector and BM25 into a single result:

```
RRF_score(doc) = sum(1 / (k + rank_in_list)) for each list containing doc
```

Where `k` is a constant (default: 60) that controls how much weight is given to position. Documents appearing in both lists get boosted.

### Search Modes

```bash
odk memory search "rate limiting"                     # Default: hybrid (vector + BM25 + RRF)
odk memory search "rate limiting" --mode vector       # Vector only
odk memory search "rate limiting" --mode keyword      # BM25 only
odk memory search "rate limiting" --mode hybrid       # Explicit hybrid
```

### Progressive Retrieval

Control how much detail is returned:

```bash
odk memory search "rate limiting" --depth index       # IDs, titles, scores only
odk memory search "rate limiting" --depth summary     # Key points and summaries
odk memory search "rate limiting" --depth full        # Complete content
```

Start with `index` to scan broadly, then drill into specific memories:

```bash
# Step 1: Find relevant memories
odk memory search "order validation" --depth index
# Results: mem-001 (0.92), mem-042 (0.85), mem-107 (0.71)

# Step 2: Get details for the top hits
odk memory get mem-001 mem-042
# Returns full content for these specific memories
```

## Temporal Validity

Memories can have optional time bounds:

```yaml
memory:
  id: mem-042
  content: "Binance API v2 endpoints available at /api/v2/"
  valid_from: "2026-01-15T00:00:00Z"
  valid_until: "2026-06-01T00:00:00Z"
```

- **Before `valid_from`**: memory is not returned in search results
- **After `valid_until`**: memory is auto-filtered from search results
- **No bounds**: memory is always available (default)

Expired memories are NOT deleted — they're retained for audit but filtered from active search. `odk memory audit` flags expired entries.

## Contradiction Detection

When a new memory is written (via extraction or manual creation), the system checks for contradictions with existing memories:

1. Search for semantically similar memories (vector similarity > threshold)
2. Use LLM to evaluate if the new memory contradicts any existing ones
3. If contradiction detected: old memory gets `superseded_by: <new_id>`, its score is suppressed
4. Both memories are retained — the old one is still visible in audit mode

**Example:**
```
Existing: "Binance rate limit is 1200 requests/minute"
New:      "Binance rate limit changed to 2400 requests/minute for verified accounts"
→ Old memory marked superseded, new memory active
```

## Bootstrap

`odk memory bootstrap <task-id>` is a specialized search that assembles context for a specific task. It combines:

1. Hybrid search using the task's description (scored and ranked)
2. Direct lookup of the task's spec refs (narratives)
3. Direct lookup of the task's component_refs (manifests)
4. Related ADRs and project rules
5. Relevant abandoned approaches (negative knowledge — what NOT to do)
6. Active decisions for related topics

The result is a focused context package that gives the agent a head start. When `memory.auto_bootstrap: true`, this runs automatically during `odk task start`.

## Configuration

All memory settings live in `.odk/config.yaml` under the `memory` key:

```yaml
memory:
  embedding_model: cohere.embed-english-v3    # Bedrock embedding model
  auto_bootstrap: true                         # Bootstrap on task start
  auto_extract: true                           # Extract on task done
  chroma_path: .odk/memory/chroma              # ChromaDB storage location
  search_mode: hybrid                          # Default: hybrid | vector | keyword
  scoring:
    category_weight: 0.50                      # Weight for extraction category
    provenance_weight: 0.15                    # Weight for source reliability
    recency_weight: 0.25                       # Weight for time decay
    access_weight: 0.10                        # Weight for access frequency
    recency_half_life_days: 30                 # Half-life for recency decay
  contradiction_threshold: 0.85                # Similarity threshold for contradiction check
  consolidation_threshold: 0.90                # Similarity threshold for consolidation
```

## What the Agent Should Know

- The memory system is optional. If ChromaDB is not installed, memory commands fail gracefully and task lifecycle continues without them.
- Bootstrap provides starting context, not complete context. The agent should still explore the codebase during task start.
- Search quality depends on index freshness. Run `odk memory index` after modifying knowledge files.
- Hybrid search is the default and recommended mode. Use `--mode vector` or `--mode keyword` only when you have a specific reason.
- Progressive retrieval (`--depth index`) is efficient for broad scans before drilling into specifics.
- Negative knowledge (abandoned approaches) surfaces automatically during bootstrap — check it before starting a new approach.
- Contradiction detection is automatic. If you see a `superseded_by` reference, check the newer memory.
- Embeddings are generated via AWS Bedrock. The configured AWS profile must have Bedrock access.
