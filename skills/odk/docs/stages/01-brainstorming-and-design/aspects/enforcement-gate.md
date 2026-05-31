# Spec Quality Enforcement Gate

## What This Is

A quality gate that evaluates spec files using 10 parallel YAML-based reviewers. Each reviewer scores the spec against one quality criterion using the Bedrock Converse API with forced structured output. All must pass their threshold before the spec can be pushed.

## When It Runs

| Trigger | Condition |
|---|---|
| Manual: `odk spec verify` | Always available |
| Pre-push hook | Only when enabled in config AND spec files changed |

The pre-push hook is disabled by default. Enable it in `.odk/config.yaml` under `hooks.pre_push.spec_check: true`.

## How It Works

1. Detects which spec files changed (git diff), or checks all files with `--all-files`
2. Reads all spec content (narratives + component manifests)
3. Sends the spec content as a cached system prompt prefix to Bedrock
4. Fans out 10 parallel Bedrock Converse API calls (one per reviewer YAML config)
5. Each call uses forced `toolChoice` to guarantee structured JSON output (score, reasoning, suggestions, findings)
6. Per-reviewer timing is logged; `--verbose` shows cache metrics and DEBUG output
7. All scores >= threshold = PASS. Any below = FAIL with detailed report.

**Prompt caching**: the spec content is sent as a cached system prompt prefix shared across all reviewers. The first reviewer primes the cache; the remaining 9 hit the cached prefix for ~90% cost savings on the spec portion.

**Anti-hallucination rules**: every reviewer's system prompt requires the LLM to quote exact text from the spec when citing findings. The LLM cannot invent findings that are not present in the source material.

**LLM score is authoritative**: deterministic tools provide evidence (scan results, pattern counts) but do not override the LLM's judgment. The LLM considers tool findings as input and makes the final scoring decision.

## The 10 Reviewers

Each reviewer is a YAML file in `src/odk/spec_reviewers/` (copied to `.odk/spec-reviewers/` on `odk init`). Each has: id, name, group, threshold, model_tier, inline Python tools, and a detailed system prompt with examples and scoring rubric.

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
- **`scan_unlinked_mentions`** (N09) — finds entity/route/concept mentions in prose that lack `[odk:...]` component references
- **`scan_url_paths`** (N09) — finds URL paths in prose that should be in route component manifests

### Model Tiers

Each reviewer declares a `model_tier` (not a model ID). The tier maps to a Bedrock model via `ai.model_tiers` in config:

| Tier | Default Model | Used By |
|---|---|---|
| `smart` | Sonnet 4 | Most reviewers |
| `fast` | Sonnet 4 | Lightweight reviewers |
| `reasoning` | Opus | Complex reasoning tasks |

### Orphaned Components

Components in `.odk/components/` that are not referenced by any narrative (`[odk:...]` link) are treated as **errors**, not warnings. Every component must be referenced from at least one narrative.

## CLI Usage

```bash
# Run all 10 reviewers
odk spec verify

# Check all spec files (not just git-changed)
odk spec verify --all-files

# Show per-reviewer timing, cache metrics, DEBUG logs
odk spec verify --verbose

# List available reviewers and their thresholds
odk spec list-criteria
```

## Structured Report Output

The verify command produces a Rich terminal display with:

- **Summary table** — color-coded scores: red (0-3), yellow (4-6), green (7-10)
- **Deterministic tool findings** — breakdown table of tool scan results
- **Per-criterion detail** — full reasoning and suggestions (no truncation)
- **File dump** — reports saved to `.odk/reports/spec-verify-{timestamp}.txt` and `.json`

```
┌──────────────── Spec Quality Check ────────────────┐
│ Reviewer                   Status    Time    Score  │
│ N01 Problem Statement      DONE      2.1s    9.0   │
│ N02 Success Criteria       DONE      2.3s    8.5   │
│ N03 Scope Boundaries       DONE      1.8s    8.0   │
│ N04 Terminology            DONE      2.0s    9.0   │
│ N05 Ambiguity              DONE      1.9s    8.5   │
│ N06 Flow Completeness      DONE      2.5s    7.5   │
│ N07 Information Density    DONE      3.1s    8.0   │
│ N08 No Tech in Prose       DONE      2.8s    9.0   │
│ N09 Component Refs         DONE      3.4s    7.0   │
│ N10 YAGNI                  DONE      2.0s    8.5   │
│ Progress: ████████████████  10/10 complete           │
└─────────────────────────────────────────────────────┘

PASS — 10/10 reviewers passed (avg: 8.3/10)
```

## Configuration

In `.odk/config.yaml`:

```yaml
ai:
  provider: bedrock
  model_tiers:
    smart: us.anthropic.claude-sonnet-4-20250514-v1:0
    fast: us.anthropic.claude-sonnet-4-20250514-v1:0
    reasoning: us.anthropic.claude-opus-4-6-v1

spec_check:
  timeout: 60                                    # seconds per reviewer
  global_timeout: 120                            # seconds total
  concurrency: 10                                # max parallel Bedrock calls
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

Projects can add custom reviewers by placing YAML files in `.odk/spec-reviewers/`. Each reviewer YAML needs: id, name, group, threshold, model_tier, tools (list), and system_prompt (with examples and scoring rubric). Follow the format of the built-in reviewers in `src/odk/spec_reviewers/`.
