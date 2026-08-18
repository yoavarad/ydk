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
- **TDD mandatory** -- write tests before implementation. Every source file must have a corresponding test file.
- **No mocks of internal classes** -- mock only at system boundaries (LLM, ChromaDB, git subprocess, gh CLI).
- **No hold-the-line** -- all lint/type violations must be fixed, not suppressed. Zero tolerance for new violations.
- **UP-1** -- everything through a PR. No direct pushes to main.
- **Branch naming** -- `type/description` (e.g. `feat/add-telemetry`).
