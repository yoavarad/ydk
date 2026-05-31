# Research Methodology

## Why Research Matters

AI agents have training data cutoffs. Libraries change APIs. Services change rate limits. The agent's knowledge is stale by default. Research bridges the gap between what the agent "knows" and what's actually true right now.

Without research: agents hallucinate API endpoints, use deprecated patterns, miss rate limits.
With research: agents build on current, verified information.

## When to Research

| Situation | Research needed? |
|---|---|
| Using a library/framework the agent knows well | No — unless checking for recent changes |
| Integrating with an external API | Yes — always verify endpoints, auth, rate limits |
| Using a technology for the first time | Yes — deep research before making decisions |
| Something unexpected happened (API returned unexpected response) | Yes — verify current behavior |
| Brainstorming (Stage 01) before asking clarifying questions | Yes — informed questions are better questions |

## Research Depth Levels

### Quick Lookup (seconds)

Need a specific fact: an API endpoint shape, a library version, a config option.

**Tools:** Context7 (library docs), web search
**Output:** Used inline, not cached
**Example:** "What's the httpx timeout default?"

### Targeted Research (minutes)

Need to understand a specific technology or integration well enough to design with it.

**Tools:** Context7 + Tavily (web search) + DeepWiki (repo understanding)
**Output:** Cached as markdown in `docs/research/`
**Example:** "How does Binance's WebSocket API handle reconnection?"

### Deep Dive (minutes)

Need comprehensive understanding of a domain, comparing multiple approaches, evaluating trade-offs.

**Tools:** All available — Context7, Tavily, DeepWiki, Codebase-Memory MCP
**Output:** Formal document committed to `docs/research/`
**Example:** "What's the best approach for real-time price streaming in 2026?"

### Code Exploration (minutes)

Need to understand an existing codebase — its structure, patterns, relationships.

**Tools:** LSP, grep, Codebase-Memory MCP, file reading
**Output:** Understanding feeds into specs and task descriptions
**Example:** "How does the existing auth middleware work? What pattern should new endpoints follow?"

## Research Tools

| Tool | What it does | When to use |
|---|---|---|
| **Context7** | Fetches current library/framework documentation | Any question about a specific library |
| **Tavily** | Web search for current information | General tech questions, community discussions, recent changes |
| **DeepWiki** | AI-powered documentation for GitHub repos | Understanding how an open source project works |
| **Codebase-Memory MCP** | Tree-sitter knowledge graph of a codebase | Structural code understanding (call graphs, module boundaries) |
| **LSP** | Language Server Protocol (go-to-definition, find-references) | Precise code navigation in existing codebases |
| **grep/Glob** | Text search across files | Finding where something is used or defined |

## Research Caching

Targeted and deep dive research gets cached in `docs/research/` for reuse.

**File format:**
```markdown
# Research: [Topic]

**Researched**: YYYY-MM-DD
**Tools used**: Context7, Tavily
**Confidence**: HIGH | MEDIUM | LOW

## Key Findings
...

## Sources
...
```

**Why cache:** Other agents working on related tasks don't need to re-research the same topic. The cache saves time and API costs.

**Expiry:** Research expires based on confidence and technology stability:
- HIGH confidence + stable tech → review after 6 months
- MEDIUM confidence → review after 3 months  
- LOW confidence → review after 1 month
- Any integration issues → immediate re-research

`odk memory audit` flags expired research entries.

**Discovery:** Before researching externally, agents SHOULD check `docs/research/` and `odk memory search` for existing research on the topic.

## Research in Each Stage

### Stage 01 (Brainstorming)
- Research technologies BEFORE asking clarifying questions (Step 3 in instructions)
- Inform the brainstorming with what you found
- Cache results for implementation

### Stage 02 (Task Management)
- Research is rarely needed — decomposition works from specs
- Exception: understanding existing codebase for brownfield decomposition

### Stage 03 (Execution)
- Research when hitting unexpected behavior from external systems
- Research when a library doesn't work as documented
- Cache findings in project-rules.md (gotchas) or docs/research/

### Stage 04 (Learning)
- `odk memory audit` checks research cache freshness
- Stale research gets flagged for re-validation
- Sprint retrospective may identify topics needing fresh research
