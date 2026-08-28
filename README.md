# YDK — Yoav Development Kit

> **Fork notice:** YDK is a personal fork of [ODK — Oz Development Kit](https://github.com/oaltagar-personal/odk), created by [Oz Altagar](https://www.linkedin.com/in/oz-altagar-0a50861b3/). All credit for the original design and workflow goes to him; this fork adapts it for my own use.

YDK is my coding workflow, packaged as an installable agent skill. I am [Oz Altagar](https://www.linkedin.com/in/oz-altagar-0a50861b3/), and this repository exists to share the way I structure AI-assisted software work: how I parallelize implementation across many coding agents, keep the work coordinated, and still trust the output.

It is intentionally opinionated. It is not meant to be a generic tool, a universal framework, or a neutral abstraction over every possible development style. YDK captures one specific way of working: specs first, agent-operated execution, deterministic enforcement where possible, and proof before trust.

The repository is meant to be read by coding agents first. Humans should only need to install the skill, tell their agent to use it, and then work with the agent as it guides the project through the process.

## Getting Started

1. Clone this repository.

```bash
git clone https://github.com/yoavarad/ydk.git
cd ydk
```

2. Install the skill by copying `skills/ydk` into your agent's local skills directory.

Common locations:

```bash
# Claude Code / local agent setups often use one of these:
mkdir -p ~/.claude/skills ~/.codex/skills ~/.agents/skills
cp -R skills/ydk ~/.claude/skills/
```

Use the skills directory for the agent you actually run. The installed folder must contain `SKILL.md`.

3. Start a new agent session in your project and say:

```text
Use the YDK skill for this project.
```

That is the onboarding. The agent reads `skills/ydk/SKILL.md`, determines the current stage, and follows the process from there.

## What The User Needs To Know

YDK is not a user-operated app. It is a process skill for coding agents.

The user does not need to learn the CLI, memorize commands, understand component schemas, or manually walk through the lifecycle. The agent is expected to load the skill, inspect the project, choose the correct stage, read the relevant stage instructions, and drive the work.

The human role is to provide taste, product intent, review, and approval. The agent role is to operate the process.

## The Process

YDK organizes software development into stages. The stages are sequential, but not rigid waterfall; discoveries can send the agent back to an earlier stage when that is the correct engineering move.

```text
Idea
  |
  v
Stage 01: Brainstorming and Design
  |
  v
Stage 01.5: Ignition
  |
  v
Stage 02: Task Management and Planning
  |
  v
Stage 03: Execution
  |
  v
Stage 04: Learning and Improvement
```

For small, self-contained changes that do not need the full task hierarchy (a typo fix, a one-line config change), YDK also provides a Quick Dev fast path (`ydk task quick`) that creates a lightweight task and branch directly, skipping dependency tracking and complexity scoring. The same verification checks used by full tasks can still be run before merging.

### Stage 01: Brainstorming And Design

The agent helps turn a vague idea into implementation-ready specifications.

The output is structured design context: narrative specs, project rules, decisions, and component-level descriptions of what the system must do. The important goal is clarity before code. Ambiguity found here is cheaper than ambiguity found halfway through implementation.

### Stage 01.5: Ignition

The agent uses the specification to produce a runnable starting point where possible.

Ignition is not a promise that the whole product is done. It is a way to turn design into a working skeleton with explicit unfinished areas. Those unfinished areas become tracked implementation work instead of invisible gaps.

### Stage 02: Task Management And Planning

The agent decomposes the remaining work into implementation tasks.

Tasks should be small enough for focused execution, tied back to the design, and ordered by dependency. A good task is not a vague instruction like "build auth"; it is a concrete unit of work with acceptance criteria and a test strategy.

### Stage 03: Execution

The agent implements tasks with proof.

This stage emphasizes TDD, verification, code review, and pull-request discipline. The agent should not simply claim that something works. It should produce evidence: tests, lint/type checks where applicable, screenshots or browser proof for UI work, and a clear account of what changed. Verification plugins exist for Python projects, with a growing set of plugins for .NET projects as well.

### Stage 04: Learning And Improvement

The agent captures what was learned.

Decisions, failed assumptions, reusable patterns, and hard-won lessons should become future project context. The point is compound improvement: each project should make the next one less dependent on memory and luck.

## Core Principles

- Specs first. Vague instructions produce vague software.
- Verification over trust. Claims need proof.
- Deterministic enforcement where possible. Do not rely on agents remembering every rule.
- Small tasks with clear acceptance criteria.
- Tests before implementation when changing behavior.
- Pull requests for meaningful changes.
- Decisions recorded when they are made.
- Learning captured after the work, not lost in the chat transcript.

## Repository Layout

```text
skills/ydk/
  SKILL.md                 # Entry point the agent loads
  docs/stages/             # Stage-specific process instructions
  docs/cross-cutting/      # Shared process guidance

src/ydk/
  CLI implementation used by agents and automation

docs/
  Documentation site (getting started, concepts, guides, architecture)

tests/
  Verification for the CLI and process tooling
```

The skill is the important part. The CLI exists to give agents concrete tooling for the process, but humans evaluating this repository should start with `skills/ydk/SKILL.md`.

## License

MIT. See `LICENSE`.
