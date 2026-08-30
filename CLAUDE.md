# YDK -- Yoav Development Kit

> Fork notice: YDK is a personal fork of ODK — Oz Development Kit, created by [Oz Altagar](https://www.linkedin.com/in/oz-altagar-0a50861b3/). All credit for the original design and workflow goes to him.

YDK is an agent skill that orchestrates the full AI-assisted software development lifecycle: brainstorming, task management, execution with proof-based verification, and compound learning. The skill is the primary interface; the CLI exists to support agent automation.

## Setup

```bash
uv sync --all-extras --dev
```

## Commands

```bash
# Tests
uv run pytest tests/ -q --tb=short -x --ignore=tests/fixtures

# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format --check src/ tests/

# Type check
uv run ty check src/ydk/ --python-version 3.13 --exclude "src/ydk/catalog/*/generators/"
```

## Onboarding

Start with `skills/ydk/SKILL.md`. It is the entry point agents should load before doing development work.

## Key Rules

- **Conventional commits** -- `type(scope): description`. Types: feat, fix, docs, chore, refactor, test, ci, perf, release.
- **Versioning is manual** -- run `cz bump` on your branch and push the tag before merging; nothing auto-bumps on merge to main. See `docs/content/docs/architecture/ci-cd.mdx` ("Versioning: manual `cz bump` + tag-sync").
- **TDD mandatory** -- write tests before implementation. Every source file must have a corresponding test file.
- **No mocks of internal classes** -- mock only at system boundaries (LLM, ChromaDB, git subprocess, gh CLI).
- **No hold-the-line** -- all lint/type violations must be fixed, not suppressed. Zero tolerance for new violations.
- **UP-1** -- everything through a PR. No direct pushes to main.
- **Branch naming** -- `type/description` (e.g. `feat/add-telemetry`).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
