# Stage 01: Brainstorming & Design — Overview

## What This Stage Does

Takes an idea and produces a specification complete enough for an AI agent to implement unsupervised. Specs now consist of two complementary artifacts:

- **Narratives** — markdown storytelling in `docs/specs/` describing the system design, flows, and rationale
- **Component manifests** — structured YAML files in `.ydk/components/` defining every entity, route, error, contract, requirement, NFR, and external dependency

Also produces ADRs (Architecture Decision Records) and project rules that capture decisions and conventions.

This stage does NOT produce epics, stories, or tasks — that's Stage 02. This stage produces specs. Specs are the source of truth that Stage 02 decomposes into actionable work.

## Why This Stage Matters

Every downstream failure — wrong implementation, missed edge case, incompatible components, wasted tokens — traces back to an incomplete or ambiguous spec. A 3-hour brainstorming session that produces a bulletproof spec saves 30+ hours of implementation rework.

Component manifests add machine-readable precision: entities with exact field types, routes with exact request/response shapes, errors with exact codes. Narratives explain the WHY; manifests encode the WHAT.

## Entry Criteria

Enter this stage when:
- Starting a new project (New System mode)
- Adding a new feature to an existing project (Major Feature mode)
- Making a change to existing behavior (Small Change mode)
- Modifying existing specs

## Exit Criteria

Leave this stage when:
- Narrative spec files exist in the project's spec location
- Component manifests exist in `.ydk/components/` for all entities, routes, errors, contracts, requirements, NFRs, and external dependencies
- Every `[ydk:...]` reference in narratives resolves (Layer A linker passes)
- Layer B scanner finds no unlinked concepts in prose
- Spec quality check passes all rubrics (run `ydk spec verify` — now 18 criteria including C17 density and C18 implementation leakage)
- ADRs written for all significant decisions
- project-rules.md updated with conventions and preferences
- PR created and approved by human (UP-1)

## Modes

| Mode | Signal | Output | Duration |
|---|---|---|---|
| **New System** | No existing codebase | Narratives + component manifests + ADRs + project-rules.md | 2-4 hours |
| **Major Feature** | Existing codebase + new capability | New/amended narratives + new manifests + new ADRs | 30-60 min |
| **Small Change** | Modification to existing behavior | Narrative amendment + manifest updates + ADR (if decision made) | 5-15 min |

## Connects To

- **Receives from**: Human idea + existing codebase (if brownfield)
- **Produces for**: Stage 02 (Task Management) receives narratives + component manifests. Tasks get `component_refs` (what to implement) and `spec_refs` (what narrative to read).
- **Cross-cutting**: Change management (UP-1), Research methodology, Brownfield pipeline

## Key Files

- `instructions.md` — the 20-step SOP with examples
- `glossary.md` — terminology for this stage
- `aspects/` — sub-topics (spec enforcement gate)

## What to Read

1. Read this overview (you're here)
2. Read `glossary.md` for stage-specific terms
3. Read `instructions.md` and follow the 20 steps
4. When you reach Step 20 (quality check), read `aspects/enforcement-gate.md`
