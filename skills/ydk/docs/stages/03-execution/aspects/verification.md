# Verification

## Plugin Architecture

Verifications are **plugins**, not hardcoded YDK features. YDK provides the runner and interface. The actual checks are external and extensible — adding a new verification means creating a folder, not modifying YDK code.

This applies to ALL verifications: linting, type checking, tests, deterministic enforcements, AI-based checks, screenshots. They're all plugins with the same interface.

## Where Plugins Live

```
# Global (ships with YDK)
ydk/verifications/
├── lint-ruff/
│   ├── manifest.yaml
│   └── check.py
├── types-ty/
│   ├── manifest.yaml
│   └── check.py
└── tests-pytest/
    ├── manifest.yaml
    └── check.py

# Project-specific (created per project)
.ydk/verifications/
├── no-float-financials/
│   ├── manifest.yaml
│   └── check.py
├── spec-alignment/
│   ├── manifest.yaml
│   └── check.py
└── screenshot-dashboard/
    ├── manifest.yaml
    └── check.py
```

YDK searches project-specific first, then global. Project plugins can override global ones with the same name.

## Plugin Manifest

```yaml
name: lint-ruff
description: "Run ruff format check + ruff lint"
layer: 1                    # 1=fast/deterministic, 2=tests, 3=ai-based
trigger:
  - pre-commit              # Named triggers: pre-commit, pre-push
parallel: true              # Safe to run in parallel with same-layer plugins
timeout: 30                 # Seconds before kill
requires: ["ruff"]          # Tools that must be installed (checked by ydk doctor)
supports_auto_fix: true     # Can fix violations when auto_fix is set
```

### Layers

| Layer | Speed | What runs here | Trigger |
|---|---|---|---|
| 1 | < 5 seconds | Lint, type check, formatting | `pre-commit` |
| 2 | < 2 minutes | Unit tests, integration tests, E2E tests, deterministic enforcements | `pre-push` |
| 3 | < 1 minute | AI spec alignment, AI code review, screenshots | `pre-push` |

Layers run sequentially. Within a layer, plugins run in parallel (if `parallel: true`). If any plugin in a layer fails, subsequent layers don't run.

Exception: integration and E2E tests set `parallel: false` because they're resource-heavy.

### Triggers

| Trigger | When | Which layers |
|---|---|---|
| `pre-commit` | Before every commit | Layer 1 only |
| `pre-push` | Before every push | All layers (1 + 2 + 3) |
| `manual` | `ydk verify run` command | As specified by `--trigger` flag |

### Spec Verification (separate from verification plugins)

The `ydk spec verify` command runs a **separate** system from verification plugins. It uses 10 YAML-based reviewers (N01-N10) that evaluate narrative spec quality via the Bedrock Converse API. See `stages/01-brainstorming-and-design/aspects/enforcement-gate.md` for details.

The verification plugin system (`ydk verify run`) handles code-level checks (lint, types, tests, architecture). The spec reviewer system (`ydk spec verify`) handles spec-level quality. They are complementary but independent.

## Plugin Contract

Every plugin's `check.py` follows this contract:

**Input:** JSON on stdin

```json
{
  "project_root": "/path/to/project",
  "changed_files": ["src/orders.py", "tests/test_orders.py"],
  "config": {},
  "task_id": "T-a1b2c3d4",
  "spec_refs": ["orders.md#entities"],
  "component_refs": ["ydk:entity:orders/Order"]
}
```

**Output:** JSON on stdout

```json
{
  "name": "lint-ruff",
  "passed": true,
  "output": "All checks passed!",
  "duration_seconds": 0.3,
  "detail": {}
}
```

**Exit code:** 0 = pass, 1 = fail, 2 = error (couldn't run)

## CLI Commands

```bash
ydk verify run                          # Run all for current context
ydk verify run --trigger pre-commit                # Only fast deterministic checks
ydk verify run --trigger pre-push                # Layers 1 + 2
ydk verify run --trigger pre-push                  # All layers (1 + 2 + 3)
ydk verify run --name lint-ruff         # Run specific plugin
ydk verify run --trigger pre-commit     # Run all pre-commit plugins
ydk verify run --trigger pre-push       # Run all pre-push plugins
ydk verify run --auto-fix               # Run ruff --fix before checking
ydk verify run --retry N                # Retry failed checks up to N times
ydk verify run --repair                 # Auto-repair: fix issues between retries
ydk verify run --retry 3 --repair       # Combined: retry 3 times with auto-repair
ydk verify run --pr <URL>               # Post results as PR comment
ydk verify run --no-cache               # Bypass verification cache
ydk verify list                         # List all available plugins
ydk verify all --save-proof             # Run all + save proof artifacts
ydk verify all --task-id T-a1b2c3d4     # Associate proof with a task
ydk verify clear-cache                  # Clear the verification content-hash cache
```

## Auto-Fix

`ydk verify run --auto-fix` runs `ruff --fix` and `ruff format` before evaluating lint checks. This automatically resolves:
- Import ordering issues
- Unused import removal
- Common formatting problems
- Simple code style fixes

The auto-fix runs BEFORE the verification check, so the check evaluates the fixed code. If issues remain after auto-fix, they are reported as normal failures.

## Auto-Repair Loop

`ydk verify run --retry N --repair` provides an automated fix-and-retry cycle:

1. Run all verifications
2. If any fail, parse the structured error output
3. Attempt targeted fixes based on error patterns (lint, type, test failures)
4. Re-run failed verifications
5. Repeat up to N times

The repair system understands common error patterns:
- Lint violations → applies `ruff --fix` with specific rules
- Type errors → adds type annotations, fixes imports
- Test failures → re-runs with verbose output for better diagnostics

Use `--retry N` without `--repair` to simply retry (useful for flaky tests). Use `--repair` with `--retry N` for the full auto-fix cycle.

## Verification Caching

Verification results are cached using content hashes of the checked files:

- **Cache key**: SHA-256 hash of all files relevant to a verification plugin
- **Cache location**: `.ydk/cache/verify/`
- **Cache hit**: if the content hash matches, the cached result is returned immediately without running the check
- **Cache miss**: the check runs normally and the result is cached

**When caching helps:**
- Running `ydk verify run` multiple times during development when only some files changed
- Re-running after fixing one issue — unchanged checks are instant

**When to bypass:**
- `--no-cache` flag forces all checks to run fresh
- `ydk verify clear-cache` purges the entire cache
- Cache is automatically invalidated when plugin manifests change

## PR Commenting

`ydk verify run --pr <URL>` posts verification results as a comment on the specified PR:

```bash
ydk verify run --trigger pre-push --pr https://github.com/org/repo/pull/47
# Runs all verifications
# Posts results as a comment on PR #47:
#   ✓ lint-ruff (0.3s)
#   ✓ types-ty (0.5s)
#   ✓ tests-pytest (11 passed, 2.1s)
#   ✓ spec-alignment (6/6 dimensions, 12.4s)
#   ALL PASSED
```

This is useful for:
- CI integration (verification runs in CI and posts results to the PR)
- Visibility for human reviewers before they start reviewing
- Audit trail of verification passes/failures

## Git Hook Integration

Hooks installed by `ydk init` in `.ydk/hooks/`:

**pre-commit:**
```bash
#!/bin/bash
ydk verify run --trigger pre-commit
```

**commit-msg:**
```bash
#!/bin/bash
ydk verify commit-msg "$1"
```
Validates conventional commit format: `<type>(<scope>): <description>`. Rejects non-conforming messages.

**pre-push:**
```bash
#!/bin/bash
ydk verify run --trigger pre-push
```

Configured via `.ydk/config.yaml`:
```yaml
hooks:
  pre_commit:
    enabled: true             # Install pre-commit hook
  commit_msg:
    enabled: true             # Install commit-msg hook (conventional commits)
  pre_push:
    enabled: true             # Install pre-push hook
```

## Parallelization

**Within a layer:** All plugins with `parallel: true` run simultaneously via asyncio. Plugins with `parallel: false` (integration tests, E2E tests) run serially after parallel ones complete.

**Between layers:** Sequential. Layer 1 must fully pass before Layer 2 starts.

**AI-based plugins (Layer 3):** All run in parallel. Use Bedrock prompt caching — the changed code is cached and shared across all AI evaluators.

## Creating a New Verification Plugin

```bash
ydk verify create no-float-financials --trigger git:pre-push
```

Creates `.ydk/verifications/no-float-financials/` with manifest.yaml template and empty check.py.

Or manually: create the folder, write manifest.yaml, write check.py following the contract.

**Example — AST-based enforcement:**

```python
#!/usr/bin/env python3
"""Check: no float() or float type hints in financial modules."""
import ast
import json
import sys

context = json.loads(sys.stdin.read())
files = [f for f in context["changed_files"] if f.endswith(".py")]

violations = []
for filepath in files:
    with open(filepath) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "float":
            violations.append(f"{filepath}:{node.lineno}: use of 'float' — use Decimal for financial values")

result = {
    "name": "no-float-financials",
    "passed": len(violations) == 0,
    "output": "\n".join(violations) if violations else "No float usage found",
    "duration_seconds": 0.1,
    "detail": {"violations": len(violations)},
}

json.dump(result, sys.stdout)
sys.exit(0 if result["passed"] else 1)
```

## Proof Artifacts

Every `ydk verify run` produces a VerificationReport saved to `.ydk/proofs/`:

```json
{
  "task_id": "T-a1b2c3d4",
  "timestamp": "2026-04-24T14:30:00Z",
  "checks": [
    {"name": "lint-ruff", "passed": true, "output": "...", "duration_seconds": 0.3},
    {"name": "types-ty", "passed": true, "output": "...", "duration_seconds": 0.5},
    {"name": "tests-pytest", "passed": true, "output": "11 passed", "duration_seconds": 0.8}
  ],
  "all_passed": true,
  "total_duration_seconds": 1.6,
  "cache_hits": 1,
  "cache_misses": 2
}
```

This is the proof that proof-based development relies on. See `aspects/proof-based-development.md` for how proofs are published to issues and PRs.
