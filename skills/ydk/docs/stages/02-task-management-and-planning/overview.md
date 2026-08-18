# Stage 02: Task Management & Planning — Overview

## What This Stage Does

Receives specs (narratives + component manifests) from Stage 01, decomposes them into the PM hierarchy (Release → Epic → Story → Task), validates dependencies, plans sprints, and drives execution through an agent loop.

Tasks now carry two kinds of references:
- **`component_refs`** — which component manifests to implement (e.g., `ydk:entity:orders/Order`, `ydk:route:orders/create`)
- **`spec_refs`** — which narrative files to read for context (e.g., `orders.md`)

## Why This Stage Matters

A perfect spec with bad decomposition produces tasks that are too large (agent fails mid-execution), too small (coordination overhead exceeds benefit), missing dependencies (agent builds on uncommitted code), or wrongly ordered (integration tests run before the code they test exists).

## Entry Criteria

Enter this stage when:
- Specs exist and passed the Stage 01 quality check
- Component manifests exist in `.ydk/components/`
- ADRs and project-rules.md exist
- Ready to start building

## Exit Criteria

Leave this stage (start execution) when:
- Every story has testable acceptance criteria referencing spec sections
- Coverage check passes (every spec section has a story)
- Every story is decomposed into tasks with `component_refs` and `spec_refs`
- Tasks have typed dependencies (8 types; only `blocks`, `conditional-blocks`, `waits-for` create execution edges)
- Complexity scoring completed — no task above split threshold
- DAG validation passes (no cycles, dependencies valid)
- Every task acceptance criterion maps to a story acceptance criterion
- Sprint goal is stated and human-approved

## The PM Hierarchy

```
Release (GitHub Release + git tag)
  └── Epic (GitHub Issue)
        └── Story (GitHub Issue, label: story)
              └── Task (GitHub Issue, label: task, ID: T-a1b2c3d4)
```

Every task links to a story. Every story links to an epic. Every epic belongs to a release. A story is always separate from its tasks — even if trivially small.

Task IDs use hash-based format `T-a1b2c3d4` — collision-free for parallel agent creation. Never sequential `T-001`.

Why strict hierarchy: traceability. Bug in production → which PR → which task → which story → which spec section → which decision → which component manifest.

## Connects To

- **Receives from**: Stage 01 (narratives, component manifests, ADRs, project-rules.md)
- **Produces for**: Stage 03 (Execution) receives tasks with dependency graph, component_refs, and spec_refs
- **Cross-cutting**: Change management (UP-1)

## What to Read

1. Read this overview (you're here)
2. Read `glossary.md` for stage-specific terms
3. Read `instructions.md` and follow the 9-step process
4. Use commands: `ydk task validate-dag`, `ydk task coverage`, `ydk task analyze-complexity`, `ydk task ready`, `ydk task plan-waves`, `ydk task archive-done`
