# Brownfield Pipeline

## What This Is

A structured process for understanding an existing codebase that has no formal documentation. This is the prerequisite before brainstorming changes to a brownfield project — you can't design changes to a system you don't understand.

## When to Use

- First time working with an existing codebase
- The project has no `docs/specs/` directory
- The project has code but no formal architecture documentation
- You need to understand the system before proposing changes

## The 4-Phase Pipeline

### Phase 0: Orientation (automated, ~5 minutes)

**Goal:** High-level understanding of what the codebase is.

**What to do:**
1. Read README, CONTRIBUTING, any existing docs
2. Identify tech stack from package files (pyproject.toml, package.json, go.mod)
3. Map the directory structure
4. Count files, lines, identify main languages
5. Read git log for recent activity patterns

**Output:** A mental model of "what is this project" — language, framework, rough architecture.

**Tools:** File reading, `find`, `wc`, `git log`

### Phase 1: Structural Extraction (automated, ~15 minutes)

**Goal:** Extract machine-readable structure from the code.

**What to do:**
1. If Codebase-Memory MCP available: build knowledge graph (call graphs, module boundaries)
2. Otherwise: use grep/LSP to identify:
   - All entity/model definitions (ORM classes, data models)
   - All API routes/endpoints (route decorators, controller files)
   - All service/business logic modules
   - All external integrations (HTTP clients, queue consumers, DB connections)
   - Test file structure and patterns
3. Map imports to understand module dependencies
4. Identify architectural patterns (MVC, hexagonal, layered, etc.)

**Output:** A map of what code exists, where it lives, and how it connects.

**Tools:** Codebase-Memory MCP, LSP, grep, tree-sitter

### Phase 2: Semantic Analysis (AI-assisted, ~30 minutes)

**Goal:** Understand what the code DOES, not just its structure.

**What to do:**
1. For each major module: read the code and summarize its purpose
2. Identify cross-cutting concerns: how errors are handled, how auth works, logging patterns
3. Identify the data flow: request comes in → processed how → response goes out
4. Note any inconsistencies or patterns that seem intentional

**Output:** Architecture description with confidence scores:
- HIGH: extracted directly from code (entity has these fields)
- MEDIUM: inferred from patterns (this module seems to handle auth)
- LOW: guessed (this might be for caching, not sure)

**Tools:** File reading, LLM summarization

### Phase 3: Gap Analysis & Human Review (~1-2 hours)

**Goal:** Identify what's missing, confirm what's right, create initial specs.

**What to do:**
1. Review Phase 1+2 output with the human
2. Confirm or correct architectural understanding
3. Identify areas with no test coverage (high risk for incorrect understanding)
4. Create initial spec files based on confirmed understanding
5. Create project-rules.md with discovered conventions

**Output:**
- `docs/specs/` with initial spec files (scoped to what you confirmed)
- `docs/project-rules.md` with conventions
- `docs/adrs/` if you discover the reasoning behind existing decisions

## Key Principles

### Spec only what you're changing

Do NOT try to reverse-engineer the entire codebase into comprehensive specs. That's wasteful and error-prone. Instead:
- Create an `overview.md` with the high-level architecture
- Create detailed specs ONLY for the subsystems you're about to modify
- Expand specs incrementally as you work on more areas

This follows the "Feathers approach" from legacy code: cover the area of change with characterization specs, not the entire system.

### Confidence scoring

Every finding from automated analysis should have a confidence level:
- **HIGH**: Directly from code (field names, route paths, import relationships)
- **MEDIUM**: Pattern-inferred (this module handles X based on naming and structure)
- **LOW**: Guessed or ambiguous (unclear purpose, could be multiple things)

High-confidence findings go directly into specs. Medium-confidence findings need human confirmation. Low-confidence findings get flagged as questions.

### Don't modify existing code during exploration

Phase 0-3 is read-only. You're understanding, not changing. Changes come after specs are written and brainstormed (Stage 01).

## After the Pipeline

Once you have initial specs and understand the codebase:
1. Enter Stage 01 (Brainstorming) in **Major Feature** or **Small Change** mode
2. The brownfield assessment (Step 3 in brainstorming) is already done — reference what you found
3. Brainstorm the changes with the spec as the baseline
4. Proceed through Stages 02-04 normally

## Tools Summary

| Phase | Tool | Purpose |
|---|---|---|
| 0 | File reading, git log | Orientation |
| 1 | Codebase-Memory MCP | Knowledge graph (call graphs, boundaries) |
| 1 | LSP | Go-to-definition, find-references |
| 1 | grep/Glob | Text search for patterns |
| 2 | File reading + LLM | Summarize module purposes |
| 2 | Codebase-Memory MCP | Structural queries |
| 3 | Human conversation | Confirm/correct understanding |
