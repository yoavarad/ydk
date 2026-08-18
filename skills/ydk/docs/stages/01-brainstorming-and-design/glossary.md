# Stage 01: Brainstorming & Design — Glossary

Terms specific to the brainstorming and design stage. For cross-stage terms, see the main SKILL.md glossary section.

## Spec

The authoritative description of a system or subsystem. Consists of two parts: narratives (markdown prose in `docs/specs/`) and component manifests (structured YAML in `.ydk/components/`). Every repo MUST have both before development begins.

DO NOT USE: plan, design doc, PRD, requirements document.

## Narrative

A markdown storytelling file in `docs/specs/` that describes the system design in prose: flows, rationale, trade-offs, context. References component manifests via `[ydk:...]` inline links. Narratives explain WHY and HOW; manifests encode WHAT.

DO NOT USE: spec file (ambiguous — use "narrative" for prose, "manifest" for YAML).

## Component Manifest

A structured YAML file in `.ydk/components/` that defines a single entity, route, error, contract, requirement, NFR, or external dependency. Every manifest has a unique ID (`ydk:<type>:<namespace>/<name>`) and a `$schema` field pointing to its schema in `.ydk/schemas/`. No schema = validation error.

## Schema

A YAML definition in `.ydk/schemas/` that describes the structure of a component type. YDK ships with 13 default schemas (entity, route, error, contract, requirement, nfr, external-dep, etc.). Projects can add custom schemas. Every schema field has a description.

## `ydk:` ID Format

The canonical identifier for every component manifest. Format: `ydk:<type>:<namespace>/<name>`. Examples: `ydk:entity:orders/Order`, `ydk:route:orders/create`, `ydk:error:orders/insufficient-balance`. Always use the full ID — never use shorthands.

## Layer A (Deterministic Linker)

A fast, deterministic validator that checks every `[ydk:...]` reference in narratives resolves to an existing component manifest in `.ydk/components/`. Runs as part of `ydk verify` and `ydk spec verify`.

## Layer B (LLM Scanner)

An AI-based scanner that reads narrative prose and identifies concepts that should be linked to a component manifest but aren't. Catches prose like "the Order entity" without an `[ydk:entity:orders/Order]` link. Runs during `ydk spec verify`.

## Spec Location

The designated directory where narrative specs live. Default `docs/specs/`, configurable per project. Any folder structure with markdown files works. MUST be git-tracked and editable via file changes.

## Spec Amendment

A change to an existing spec. Always goes through a PR. The commit message explains what changed and why. For lightweight amendments, consider the spec evolution system (`ydk change propose`).

## ADR (Architecture Decision Record)

A record of a significant decision. Lives in `docs/adrs/NNN-title.md`. Contains: what was decided, why, alternatives considered, consequences. Append-only — superseded decisions are marked, never deleted.

## project-rules.md

Agent-agnostic file (`docs/project-rules.md`) containing conventions, preferences, non-negotiables, and domain context. Any AI agent (Claude, Cursor, Copilot) or human can read it. Updated throughout the brainstorming session as rules emerge.

## Exit Criteria

The 18 quality dimensions a spec must satisfy before leaving this stage. Grouped into 4 rubrics: completeness, clarity, architecture, robustness. Plus C17 (spec density) and C18 (implementation leakage). Validated by `ydk spec verify`.

## Rubric

A group of related quality criteria. The 4 built-in rubrics are: completeness (entities, external deps, error scenarios, auth), clarity (agent-readable, glossary, tech stack, scope), architecture (boundaries, contracts, cross-cutting, testing), robustness (NFRs, adversarial review, brownfield). Extended with C17 density and C18 leakage checks.

## Adversarial Review

The process of deliberately trying to break the design by asking "what if" questions: external service down, 10x traffic, race conditions, malicious input. Answers MUST be in the spec, not left to the implementing agent.

## Brownfield Assessment

The process of exploring an existing codebase to document constraints before designing changes. Identifies: existing patterns, untouchable files, infrastructure in place, conventions to follow.

## E2E Walkthrough

A complete end-to-end user flow traced through the entities and interfaces, used to verify the data model supports all required operations. Done after entity modeling to catch gaps.
