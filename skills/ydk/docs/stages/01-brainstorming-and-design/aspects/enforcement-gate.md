# Spec Quality Enforcement Gate

## What This Is

A quality gate defined by 10 YAML-based reviewer criteria. `ydk spec verify` runs component checks, reference integrity, and the reviewers that define deterministic tools (N07-N09); reviewers without tools (N01-N06, N10) are skipped by the CLI — their system prompts are scoring rubrics for the in-session agent to apply when reviewing a spec, not automated LLM calls.

## When It Runs

| Trigger | Condition |
|---|---|
| Manual: `ydk spec verify` | Always available |
| Pre-push hook | Only when enabled in config AND spec files changed |

The pre-push hook is disabled by default. Enable it in `.ydk/config.yaml` under `hooks.pre_push.spec_check: true`.

## How It Works

1. Detects which spec files changed (git diff), or checks all files with `--all-files`
2. Reads all spec content (narratives + component manifests)
3. Runs component checks and reference integrity checks
4. Runs the deterministic tools for reviewers that declare them (N07-N09); reviewers without tools are skipped
5. Per-reviewer timing is logged; `--verbose` shows DEBUG output
6. All scores >= threshold = PASS. Any below = FAIL with detailed report.

Reviewers without deterministic tools (N01-N06, N10) still ship their scoring rubric and system prompt in `.ydk/spec-reviewers/`; apply that judgment in-session (e.g. via the agent doing the spec review) rather than expecting the CLI to score them automatically.

## The 10 Reviewers

Each reviewer is a YAML file in `src/ydk/spec_reviewers/` (copied to `.ydk/spec-reviewers/` on `ydk init`). Each has: id, name, group, threshold, inline Python tools (`tool_names`), and a detailed system prompt with examples and scoring rubric.

| ID | Name | Group | Tools |
|---|---|---|---|
| N01 | Problem Statement | completeness | — |
| N02 | Success Criteria | completeness | — |
| N03 | Scope Boundaries | completeness | — |
| N04 | Terminology Consistency | clarity | — |
| N05 | Ambiguity | clarity | — |
| N06 | Flow Completeness | architecture | — |
| N07 | Information Density | clarity | `scan_filler_phrases` |
| N08 | No Technical Specs in Prose | architecture | `scan_type_annotations` |
| N09 | Component References | architecture | `scan_unlinked_mentions`, `scan_url_paths` |
| N10 | YAGNI | robustness | — |

### Deterministic Tools

Only 4 high-value inline Python tools remain (down from more in earlier versions). They provide evidence for the LLM scorer:

- **`scan_filler_phrases`** (N07) — detects vague phrases like "robust", "scalable", "industry-standard" that add no implementation detail
- **`scan_type_annotations`** (N08) — detects technical specifications in prose (type hints, field definitions, JSON shapes) that belong in component manifests
- **`scan_unlinked_mentions`** (N09) — finds entity/route/concept mentions in prose that lack `[ydk:...]` component references
- **`scan_url_paths`** (N09) — finds URL paths in prose that should be in route component manifests

### Orphaned Components

Components in `.ydk/components/` that are not referenced by any narrative (`[ydk:...]` link) are treated as **errors**, not warnings. Every component must be referenced from at least one narrative.

## CLI Usage

```bash
# Run component checks, reference integrity, and the tool-backed reviewers (N07-N09)
ydk spec verify

# Check all spec files (not just git-changed)
ydk spec verify --all-files

# Show per-reviewer timing and DEBUG logs
ydk spec verify --verbose

# List available reviewers and their thresholds
ydk spec list-criteria
```

## Structured Report Output

The verify command produces a Rich terminal display with:

- **Summary table** — color-coded scores: red (0-3), yellow (4-6), green (7-10)
- **Deterministic tool findings** — breakdown table of tool scan results
- **Per-criterion detail** — full reasoning and suggestions (no truncation)
- **File dump** — reports saved to `.ydk/reports/spec-verify-{timestamp}.txt` and `.json`

```
┌──────────────── Spec Quality Check ────────────────┐
│ Reviewer                   Status    Time    Score  │
│ N07 Information Density    DONE      0.1s    8.0   │
│ N08 No Tech in Prose       DONE      0.1s    9.0   │
│ N09 Component Refs         DONE      0.2s    7.0   │
│ Progress: ████████████████  3/3 complete              │
└─────────────────────────────────────────────────────┘

PASS — 3/3 tool-backed reviewers passed (avg: 8.0/10)
N01-N06, N10 skipped (no deterministic tools) — apply their rubric in-session.
```

## Configuration

In `.ydk/config.yaml`:

```yaml
spec_check:
  timeout: 60                                    # seconds per reviewer
  global_timeout: 120                            # seconds total
  concurrency: 10                                # max parallel reviewer checks
  thresholds:
    completeness: 8
    clarity: 8
    architecture: 8
    robustness: 7

hooks:
  pre_push:
    spec_check: false                            # disabled by default
```

## Custom Reviewers

Projects can add custom reviewers by placing YAML files in `.ydk/spec-reviewers/`. Each reviewer YAML needs: id, name, group, threshold, tool_names (list), and system_prompt (with examples and scoring rubric). Reviewers that declare tools run automatically via `ydk spec verify`; reviewers without tools ship as rubrics for in-session review. Follow the format of the built-in reviewers in `src/ydk/spec_reviewers/`.
