# Brainstorming & Design

## Overview

Produce a specification complete enough for an AI agent to implement unsupervised. Specs consist of narratives (markdown storytelling) and component manifests (structured YAML). Also produce ADRs and project rules that capture decisions and conventions. This SOP walks through a 20-step process from idea to approved spec.

## Parameters

- **idea** (required): The human's description of what they want to build. Can be one sentence or ten paragraphs.
- **mode** (required): New System, Major Feature, Small Change, or Rewrite. Detected automatically from context (see Step 1).
- **existing_codebase** (optional): Path to existing code if brownfield. Null for greenfield.
- **existing_docs** (optional): Path to existing documentation that defines the system design. When present in Rewrite mode, these docs ARE the design — you translate them to YDK format rather than brainstorming from scratch.

**Constraints for parameter acquisition:**
- You MUST determine the mode before proceeding past Step 1
- You MUST NOT ask for mode directly — infer it from the idea and codebase context
- You MUST confirm the mode with the human before proceeding

## Steps

### 0. Catalog Discovery

Before brainstorming, check the catalog for ignition packs that match the project's architecture. The choice of ignition pack influences how you design component manifests — your components should align with what the pack can consume.

**Constraints:**
- You MUST run `ydk catalog search <architecture-keywords>` to find relevant ignition packs (e.g., `ydk catalog search "fastapi hexagonal"`)
- You MUST run `ydk catalog list` to see what is already installed
- You SHOULD install an ignition pack before finalizing component manifests: `ydk catalog install <pack-name>`
- You MUST run `ydk catalog info <pack-name>` to understand what component types the pack consumes and what code it generates
- You MUST design component manifests toward the installed pack's requirements (field names, types, structure)
- If no suitable pack exists, proceed without one — manual scaffolding in Stage 03 still works

**Example:**

> ```bash
> ydk catalog search "python fastapi"
> # Results:
> #   hexagonal-architecture — FastAPI + SQLAlchemy hexagonal layout with ports/adapters
> #   python-quality — ruff, ty, pytest verification plugins
>
> ydk catalog install hexagonal-architecture
> ydk catalog info hexagonal-architecture
> # Consumes: entity, route, error, contract, external-dep
> # Generates: domain models, repository ports, FastAPI routes, Alembic migrations, test stubs
> # TODOs registered for: service logic, validation rules, repository implementations
> ```

### 1. Scope Assessment

Determine whether the idea is one project or several independent subsystems. This prevents wasting time refining details of something that needs decomposition first.

**Constraints:**
- You MUST listen to the full idea before assessing scope
- You MUST flag if the idea describes multiple independent products ("trading + blog + analytics = 3 projects")
- If multiple independent products, You MUST help decompose into sub-projects and pick one to start
- You MUST determine the mode (New System / Major Feature / Small Change / Rewrite) and confirm with the human
- You SHOULD NOT proceed to detailed questions until scope and mode are confirmed
- **Rewrite mode**: The system already exists with complete documentation. The design is FIXED — you translate existing docs into YDK specs (narratives + component manifests) rather than brainstorming from scratch. Skip Steps 2-13 (questions/research) and go directly to Step 14 (narratives) using existing_docs as your complete input.

**Example:**

> **Human**: "I want a paper trading app where I can practice buying and selling crypto with fake money but real market data, and track my portfolio over time."
>
> **Agent**: "This is one coherent system with related subsystems — auth, order management, portfolio tracking, market data. They share a database and user model, so this is one project, not multiple independent ones. We'll brainstorm it as a single spec but break the implementation into demo-able increments. This is a **New System** brainstorming."
>
> *If the user had said "Build me a platform with trading, social features, a blog, and an analytics dashboard":*
>
> **Agent**: "These are 4 independent products. Let's pick one to start with and give it its own spec cycle. Which is the highest priority?"

### 2. Problem Statement

Restate the idea as a clear, neutral problem statement: WHO needs WHAT, WHY. This prevents scope drift — if agent and human aren't aligned on WHAT, every subsequent question is wrong.

**Constraints:**
- You MUST restate the idea as "We are building [description]"
- You MUST get explicit confirmation ("Yes, that's it") before proceeding
- You MUST NOT proceed without confirmation
- You MUST write the problem statement to `docs/project-rules.md` under "## Product Context"

**Example:**

> **Agent**: "Let me restate: We are building a simulated cryptocurrency trading platform that uses real-time market prices but virtual balances, allowing users to practice trading strategies without financial risk, with portfolio tracking to measure performance over time."
>
> **Human**: "Yes, exactly."
>
> *Agent writes to `docs/project-rules.md`:*
> ```
> ## Product Context
> Paper trading platform — simulated crypto trading with real market data
> and virtual balances. Educational/practice purpose, not real money.
> ```

### 3. Brownfield Assessment

Explore existing codebase and document constraints. For greenfield, state "no constraints" and move on.

**Constraints:**
- If greenfield: You MUST explicitly state "Greenfield — no constraints"
- If brownfield with no docs: You MUST run the brownfield exploration pipeline (see `cross-cutting/brownfield-pipeline.md`) before proceeding
- If brownfield: You MUST document existing patterns, untouchable files, infrastructure, and conventions
- You MUST confirm constraints with the human

### 4. Research

Research technologies, APIs, and patterns BEFORE asking clarifying questions. Informed questions are better questions.

**Constraints:**
- You MUST research unfamiliar technologies before asking questions about them
- You SHOULD use Context7 for library/framework docs
- You SHOULD use Tavily for general tech landscape questions
- You SHOULD use DeepWiki for understanding open source repos
- You SHOULD use LSP/grep/Codebase-Memory MCP for existing codebase understanding
- You MUST cache targeted research results in `docs/research/` for reuse
- You MUST write discovered gotchas to `docs/project-rules.md`

**Example:**

> Agent researches Binance API (Context7) → discovers `PARTIALLY_FILLED` status not in tutorials.
>
> *Writes to `docs/project-rules.md`:*
> ```
> ## Known Gotchas
> - NEVER use `from __future__ import annotations` in FastAPI route files
>   (breaks dependency injection at runtime)
> - Binance API returns PARTIALLY_FILLED status — must handle as first-class state
> ```

### 5. Clarifying Questions

Ask questions one at a time. Multiple choice when possible. Always have an opinion and explain why.

**Constraints:**
- You MUST ask one question at a time — never a wall of questions
- You MUST provide multiple choice options when possible
- You MUST have an opinion and explain your recommendation
- You MUST challenge assumptions — you are a design partner, not a yes-man
- You MUST watch for: over-engineering, under-specifying, contradictions, premature optimization
- You MUST write an ADR immediately after each significant decision
- You MUST update project-rules.md after each preference or convention is stated
- You MUST propose 2-3 approaches with trade-offs before the human commits
- You MUST NOT accept answers without understanding the reasoning

**Example — challenging the user:**

> **Agent**: "Authentication — two options:
>
> **(A)** Single-user — simplest, all data belongs to one user
> **(B)** Multi-user with JWT — adds registration, login, token management
>
> I'd recommend (B). Retrofitting auth later is a rewrite."
>
> **Human**: "Multi-user, JWT."
>
> *Agent writes ADR immediately:*
> ```markdown
> # ADR-001: Multi-user JWT auth from day 1
> ## Status: Accepted
> ## Context: Could start single-user (simpler) or multi-user
> ## Decision: Multi-user with email + password + JWT
> ## Alternatives: Single-user — simpler but retrofitting is a rewrite
> ## Consequences: Every endpoint needs auth middleware, every query filters by user_id
> ```

### 6. Tech Stack Declaration

Propose the complete technology stack. Lock it — not revisited during implementation.

**Constraints:**
- You MUST specify: language + version, framework, database, ORM, HTTP client, key libraries, package manager, testing tools, linting
- You MUST get human approval before locking
- You MUST write an ADR for the stack decision
- You MUST NOT leave any technology choice ambiguous ("a modern framework" = failure)

**Example:**

> ```
> Backend:  Python 3.13, FastAPI 0.115+
> Database: PostgreSQL 16 (asyncpg driver)
> ORM:      SQLAlchemy 2.x async, Alembic for migrations
> HTTP:     httpx (async, for Binance API calls)
> Schemas:  Pydantic v2
> Packages: uv
> Tests:    pytest + pytest-asyncio, httpx AsyncClient for E2E
> Linting:  ruff + ty
> Deploy:   Docker Compose (FastAPI + PostgreSQL + nginx)
> Frontend: Next.js 15, TypeScript, Tailwind CSS, shadcn/ui
> ```

### 7. Entity & Domain Modeling → Component Manifests

Define every entity with ALL fields, types, constraints, relationships, enums, state transitions. No placeholder language. **Every entity MUST be created as a component manifest in `.ydk/components/`.**

**Constraints:**
- You MUST define every field with: name, type, nullable/required, constraints, default
- You MUST list all enum values explicitly — not "various statuses"
- You MUST define state transitions if the entity has a status field
- You MUST define relationships with FK references and cardinality
- You MUST specify indexes for known query patterns
- You MUST use Decimal for financial values — NEVER float
- You MUST NOT use placeholder language ("typical fields", "etc.", "standard columns")
- You MUST walk through a complete E2E user flow after entity modeling to verify the data model
- You MUST write financial/data rules to project-rules.md
- You MUST create a component manifest for each entity: `ydk component create entity <namespace>/<name>`
- You MUST reference entities in narratives using `[ydk:entity:<namespace>/<name>]`

**Example — Order entity manifest:**

> ```yaml
> # .ydk/components/entities/orders/Order.yaml
> $schema: ../../schemas/entity.yaml
> id: ydk:entity:orders/Order
> name: Order
> fields:
>   - name: id
>     type: UUID
>     constraints: [PK, server-generated]
>   - name: user_id
>     type: UUID
>     constraints: [FK→User, required]
>   - name: symbol
>     type: str
>     constraints: [max 10, required]
>   - name: side
>     type: enum
>     values: [BUY, SELL]
>     constraints: [required]
>   # ... all fields with full types and constraints
> state_transitions:
>   PENDING: [FILLED, PARTIALLY_FILLED, CANCELLED]
>   PARTIALLY_FILLED: [FILLED, CANCELLED]
> indexes:
>   - [user_id, "created_at DESC"]
>   - [status]
> ```

**E2E walkthrough example:**

> "User registers → places BUY order → order fills → position created → views portfolio with P&L → sells partial position → balance updated. Does the data model support every step?"
>
> Human: "What if user sells more than they own?"
>
> Agent: "Good catch — validation rule: SELL quantity <= position.quantity. Adding to error scenarios."

### 8. External Dependencies → Component Manifests

Document every external system with enough detail to write the client code from the spec alone. **Each external dependency MUST be a component manifest.**

**Constraints:**
- You MUST document for each external system: base URL, auth method, endpoints used (with request/response shapes), rate limits (numbers), error response shapes, retry/timeout strategy
- You MUST NOT just name the dependency ("use Binance API" = failure)
- You SHOULD calculate whether rate limits accommodate the planned usage
- You MUST create a component manifest: `ydk component create external-dep <namespace>/<name>`

**Example:**

> ```yaml
> # .ydk/components/external-deps/exchange/binance-rest.yaml
> $schema: ../../schemas/external-dep.yaml
> id: ydk:external-dep:exchange/binance-rest
> name: Binance REST API
> base_url: https://api.binance.com/api/v3
> auth: none (public endpoints)
> endpoints:
>   - path: /ticker/price
>     method: GET
>     params: { symbol: str }
>     response: { symbol: str, price: str }
> rate_limits:
>   weight_per_minute: 1200
>   on_429: Retry-After header
>   on_418: banned 2-5 min
> retry: { backoff: [1s, 2s, 4s], max: 3, timeout: 5s }
> planned_usage: ~8 weight/min
> ```

### 9. Component Architecture

Define modules, single responsibility per module, dependencies, directory structure.

**Constraints:**
- You MUST define every component with: name, single responsibility, depends-on, depended-on-by
- You MUST state forbidden dependencies explicitly (e.g., "routes NEVER import from domain")
- For any piece of functionality, You MUST be able to point to exactly ONE owner

### 10. Interface Contracts → Component Manifests

Define typed request/response shapes for every boundary. **Each interface contract MUST be a component manifest.**

**Constraints:**
- You MUST define for every API endpoint: method, path, typed request body, typed response body, all status codes with response shapes
- You MUST include error response shapes (not just "returns error")
- Two independent agents MUST be able to implement caller and callee from these contracts and get compatible code
- You MUST create route manifests: `ydk component create route <namespace>/<name>`
- You MUST create error manifests for non-trivial error scenarios: `ydk component create error <namespace>/<name>`

**Example:**

> ```yaml
> # .ydk/components/routes/orders/create.yaml
> $schema: ../../schemas/route.yaml
> id: ydk:route:orders/create
> method: POST
> path: /api/v1/orders
> request:
>   symbol: str
>   side: "BUY" | "SELL"
>   order_type: "MARKET" | "LIMIT"
>   quantity: Decimal
>   price: Decimal | null
>   notes: str | null
> responses:
>   201: { id: UUID, symbol: str, side: str, order_type: str, quantity: Decimal, price: Decimal | null, status: "PENDING", created_at: datetime }
>   400: { type: validation_error, errors: [{ field: str, message: str }] }
>   401: { type: auth_error, detail: "Invalid or expired token" }
>   422: { type: business_error, code: INSUFFICIENT_BALANCE, detail: str }
> ```

### 11. Auth & Security

Define authentication, authorization, token lifecycle, failure responses.

**Constraints:**
- You MUST specify: auth mechanism, token lifecycle, per-endpoint rules, resource ownership, failure responses (401 vs 403)
- You MUST NOT use "standard JWT" without specifying every detail

### 12. Error Scenarios & Edge Cases → Component Manifests

For every happy path, enumerate error scenarios with exact response shapes. **Each significant error scenario MUST be a component manifest.**

**Constraints:**
- For every feature, You MUST enumerate: invalid input, external service down, timeout, partial failure, race condition, auth failure, business rule violation
- You MUST specify exact response shapes for each error
- You MUST NOT use "handle appropriately" or "return error"
- You MUST write critical error handling rules to project-rules.md
- You MUST create error manifests: `ydk component create error <namespace>/<name>`

### 13. Non-Functional Requirements → Component Manifests

Quantify everything. No adjectives — numbers only. **Each NFR MUST be a component manifest.**

**Constraints:**
- You MUST specify: latency (P95, P99), throughput, availability, resource limits, data volume
- You MUST NOT use adjectives ("fast", "scalable", "reliable") — only numbers
- Every NFR MUST be convertible to a test or monitoring alert
- You MUST create NFR manifests: `ydk component create nfr <namespace>/<name>`

### 14. Cross-Cutting Concerns

Define system-wide behaviors once.

**Constraints:**
- You MUST define once: error format, pagination, timestamps, IDs, logging/tracing, health check, CORS
- You MUST NOT re-describe these in individual feature sections

### 15. Scope Declaration

Define what IS and ISN'T being built.

**Constraints:**
- You MUST provide three lists: IN scope, OUT of scope, DEFERRED
- The OUT of scope list MUST prevent gold-plating — if it's not listed, an agent might build it

### 16. Testing Strategy

Define test types, what's real vs stubbed, rules.

**Constraints:**
- You MUST define: test types (unit, integration, E2E), what each covers, DB strategy, external API strategy
- You MUST state explicit rules (e.g., "NEVER mock internal classes")

### 17. Frontend Design

Draw ASCII wireframes for each page. This surfaces missing API requirements. **You MAY use the visual companion for interactive mockups.**

**Constraints:**
- You MUST draw an ASCII wireframe for each significant page
- You MUST list the API calls each page needs
- You SHOULD ask the human to review each wireframe before proceeding
- You MAY use `ydk visual start` to launch the browser-based mockup tool for interactive design
- You MAY use `ydk visual push` to share mockups and `ydk visual feedback` to collect human input
- You MAY use `ydk visual screenshot` to capture mockup screenshots for the spec

**Example:**

> ```
> ┌──────────────────────────────────────────────┐
> │  LILLY                   [Portfolio] [Orders] │
> ├──────────────────────────────────────────────┤
> │  Balance: $98,450        Total P&L: +$1,230  │
> │  ┌─ Positions ────────────────────────────┐  │
> │  │ Symbol   Qty    Avg     Current   P&L  │  │
> │  │ BTCUSDT  0.5    $42K   $43.2K   +$600 │  │
> │  └────────────────────────────────────────┘  │
> │  ┌─ Quick Trade ──────────────────────────┐  │
> │  │ [BTCUSDT ▼] [BUY][SELL] Qty:[___]     │  │
> │  │                       [Place Order]    │  │
> │  └────────────────────────────────────────┘  │
> └──────────────────────────────────────────────┘
> ```
>
> API calls needed: GET /portfolio, GET /orders?limit=5, GET /prices, GET /auth/me

### 18. Glossary Lock

Lock terminology. One name per concept.

**Constraints:**
- You MUST define every domain concept with one canonical name
- You MUST list synonyms as "DO NOT USE"
- You MUST scan the full spec for inconsistencies after writing the glossary

### 19. Adversarial Review

Deliberately try to break the design with "what if" questions.

**Constraints:**
- You MUST challenge the design with at minimum: external service down for hours, 10x traffic, race conditions on shared resources, malicious input, decimal precision, concurrent operations
- You MUST NOT leave any challenge with "we'll handle it" — answers go in the spec
- You MUST resolve every challenge with a concrete mechanism in the spec

**Example:**

> - "Binance down 2 hours?" → Show banner, orders return 503, portfolio shows stale prices
> - "Double-click submit?" → Idempotency key, 409 on duplicate within 5s
> - "Balance goes negative from concurrent orders?" → SELECT FOR UPDATE on balance row

### 19b. In-Session Self-Review

Before showing the assembled spec to the human, perform a self-review:

1. **Placeholder scan** — Search for "TBD", "TODO", "to be determined", "TBC", incomplete sections, or vague requirements. Fix them inline.
2. **Internal consistency** — Check that entities referenced in API contracts exist in the data model. Check that error codes in error scenarios match the cross-cutting error format. Check that glossary terms are used consistently.
3. **Scope check** — Is this focused enough for a single implementation plan? If not, flag for decomposition.
4. **Ambiguity check** — Could any requirement be interpreted two different ways? If so, pick one and make it explicit.
5. **YAGNI check** — Does the spec include features nobody asked for? Unnecessary abstraction layers? Over-engineering?
6. **Component reference check** — Verify every entity, route, error, NFR, and external dependency mentioned in narratives has a corresponding component manifest. Verify every `[ydk:...]` link resolves. Fix any missing manifests or broken links.

Fix any issues inline. Do NOT show the spec to the human until this review passes.

### 20. Spec Assembly, Quality Check & Sign-Off

Assemble everything into spec files. Run quality check. Get human approval.

**Narrative Writing Rules:**

When writing narrative specs, follow these rules strictly to pass the spec reviewers:

- **NEVER include technical specifications in prose** — URLs, type annotations, field definitions, JSON shapes, database column types belong in component manifests, not narratives
- **ALWAYS reference components by `[ydk:type:namespace/name]` ID** — every entity, route, error, NFR, and external dependency mentioned in prose must have an inline link
- **When removing a technical detail from prose, REPLACE it with a component reference** — don't just delete it; the information must live somewhere
- **The component must exist in `.ydk/components/`** for the reference to resolve — create it first with `ydk component create`
- **Run `ydk component validate` frequently** during writing to catch broken references early
- **Every component must be referenced from at least one narrative** — orphaned components are errors, not warnings

**Constraints:**
- You MUST assemble narratives into the project's spec location
- You MUST ensure all component manifests exist in `.ydk/components/` with valid `$schema` references
- You MUST run the Layer A deterministic linker to validate all `[ydk:...]` references: `ydk component validate`
- You MUST run the Layer B LLM scanner to find unlinked concepts (runs as part of `ydk spec verify`)
- You MUST run the spec quality check: `ydk spec verify` (10 YAML-based reviewers — N01-N10, covering problem statement, success criteria, scope, terminology, ambiguity, flow completeness, information density, no-tech-in-prose, component references, and YAGNI)
- You MUST use `--all-files` flag when checking files not in the git diff
- You MAY use `--verbose` to see per-reviewer timing and cache metrics
- For details on the quality gate, see `aspects/enforcement-gate.md`
- You MUST fix all failures before creating PR
- You MUST create PR with: narrative files + component manifests + ADRs + project-rules.md
- You MUST NOT merge without human approval (UP-1)
- You SHOULD propose agile, demo-able increments for implementation ordering

**Example output:**

> ```
> docs/specs/overview.md, orders.md, portfolio.md, auth.md, exchange.md, frontend.md, glossary.md
> .ydk/components/entities/orders/Order.yaml, entities/auth/User.yaml, ...
> .ydk/components/routes/orders/create.yaml, routes/orders/list.yaml, ...
> .ydk/components/errors/orders/insufficient-balance.yaml, ...
> .ydk/components/external-deps/exchange/binance-rest.yaml, ...
> .ydk/components/nfrs/system/latency-p95.yaml, ...
> docs/adrs/001-multi-user-jwt-auth.md, 002-periodic-portfolio-refresh.md, 003-tech-stack.md
> docs/project-rules.md
> ```

### Scaffold Awareness (during design)

Before finalizing component manifests, check available scaffolds:
```
ydk scaffold list
```

If a scaffold exists for your architecture (e.g., `fastapi-route`, `python-model`), design your component manifests to match the scaffold's expected input shape. This ensures scaffolding can generate 60-70% of boilerplate.

For greenfield projects, scaffolding should generate:
- Data models from entity components
- Route handlers from route components
- Test stubs from test components
- Repository implementations from contract components

The agent SHOULD use scaffolding wherever possible to reduce manual code.

### Custom Component Schemas

YDK ships with 13 default schemas (entity, route, error, contract, etc.) but projects can create custom schemas when the defaults don't fit. If your project has domain-specific component types that don't map well to the built-in types, create a custom schema in `.ydk/schemas/`.

**When to create a custom schema:**
- The built-in type forces you to leave required fields empty or use them for unrelated purposes
- Multiple components share a structure that no built-in type captures
- You need domain-specific validation (e.g., CLI commands need arguments/options, not HTTP methods/paths)

**How to create one:**
1. Create a YAML file in `.ydk/schemas/<type-name>.yaml` following the schema format
2. Define `name`, `description`, `version`, and `fields` with types, requirements, and descriptions
3. Create components using `$schema: "ydk:schema:<type-name>"` and `id: "ydk:<type-name>:<namespace>/<name>"`

**Example — YDK's own `cli-command` schema:**

YDK itself uses `cli-command`, `core-module`, and `pydantic-model` custom schemas because its CLI commands don't fit the `route` schema (which expects HTTP methods), its core modules don't fit `contract` (which expects service interfaces), and its Pydantic models don't fit `entity` (which expects database models).

### Decision Archaeology

Brainstorming session transcripts are stored by Claude Code at:
```
~/.claude/projects/<project-hash>/<session-id>.jsonl
```

When someone asks "why did we decide X?", these transcripts contain the full reasoning context — questions asked, alternatives considered, and trade-offs evaluated. ADRs capture the WHAT and WHY of decisions; transcripts capture the HOW of the conversation that led to them.

To extract learnings from a brainstorming session:
```
ydk memory extract <task-id> --jsonl <path-to-session-jsonl>
```

## Troubleshooting

### User wants to skip brainstorming
Explain: every hour spent on specs saves 10 hours of implementation rework. Even simple changes benefit from a 5-minute brainstorm (Small Change mode). For truly trivial changes, suggest `ydk task quick "description"` instead.

### Spec fails quality check
Read the failure report — it tells you which of the 10 reviewers (N01-N10) failed and why. Common failures:
- **N07 (Information Density)** — filler phrases detected by `scan_filler_phrases`. Replace vague adjectives ("robust", "scalable") with specific numbers or remove them.
- **N08 (No Technical Specs in Prose)** — type annotations or JSON shapes found in narrative by `scan_type_annotations`. Move them to component manifests and replace with `[ydk:...]` references.
- **N09 (Component References)** — unlinked entity/route mentions found by `scan_unlinked_mentions`. Add `[ydk:...]` links or create missing manifests.
Go back to the relevant step and fix the gap. Don't try to "game" the check by adding shallow content — fix the actual gap. Use `--verbose` to see per-reviewer timing and tool findings detail.

### Layer A linker finds broken references
An `[ydk:...]` reference in a narrative points to a component manifest that doesn't exist. Create the missing manifest with `ydk component create` or fix the reference.

### Layer B scanner finds unlinked concepts
The scanner identified a concept in prose that should reference a component manifest. Add the `[ydk:...]` link or create the manifest if it doesn't exist.

### User disagrees with agent's recommendation
Accept valid counterarguments. The agent is adversarial about assumptions but deferential on preferences. If the user has a good reason, respect it and document it in an ADR.

### Brownfield with no documentation
Enter the brownfield pipeline (see `cross-cutting/brownfield-pipeline.md`) before brainstorming. This establishes a spec location and baseline understanding of the codebase.

### Brainstorming session is too long
Check if the idea should be decomposed into sub-projects (Step 1). A 4-hour session for a complex new system is normal. A 4-hour session for a small change means something is wrong.
