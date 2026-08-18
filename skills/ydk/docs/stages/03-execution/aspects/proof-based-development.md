# Proof-Based Development

## The Principle

Every claim an agent makes must be backed by verifiable evidence. This is what makes hands-off-keyboard development possible: the human reviews proofs, not code.

**Not proof-based:** "I implemented the order validation and it works."
**Proof-based:** "11/11 unit tests pass. Spec alignment: 6/6 dimensions pass. Lint clean. Types clean. Review: 0 critical findings. Screenshots attached."

## What Counts as Proof

| Claim | Required Proof |
|---|---|
| "Tests pass" | Actual pytest output showing test count and pass status |
| "Code is clean" | Actual ruff output showing no violations |
| "Types check" | Actual ty/mypy output showing no errors |
| "Matches spec" | Spec alignment report with 6 dimension scores |
| "No security issues" | Security review agent report |
| "UI looks right" | Screenshot images attached to the issue |
| "Performance is acceptable" | Benchmark results or load test output |

## Proof Artifacts

Every verification produces a proof artifact stored in `.ydk/proofs/<task-id>/`:

```
.ydk/proofs/T-a1b2c3d4/
├── verification.json     # Full verification results
├── test-output.txt       # Raw pytest output
├── lint-output.txt       # Raw ruff output
├── types-output.txt      # Raw ty output
├── spec-alignment.json   # 6-dimension spec alignment report
├── review.json           # AI review agent findings
└── screenshots/          # UI screenshots (if applicable)
    ├── dashboard.png
    └── order-form.png
```

## Where Proofs Are Published

1. **Task issue** — summary posted as a comment after `ydk task done`
2. **PR description** — proof table included in the PR body
3. **PR comment** — `ydk verify run --pr <URL>` posts verification results as a PR comment (useful for CI integration and audit trail)
4. **Local files** — `.ydk/proofs/<task-id>/` for detailed inspection

### Issue Comment Format

```markdown
## Verification Proof — T-a1b2c3d4

| Check | Result | Duration |
|---|---|---|
| Lint (ruff) | PASS | 0.3s |
| Types (ty) | PASS | 0.5s |
| Tests (pytest) | 11 passed | 0.8s |
| Enforce | 3/3 checks passed | 0.2s |
| Spec Alignment | 6/6 dimensions | 12.1s |
| Review | 0 critical findings | 18.4s |
| Screenshots | 2 captured | 3.2s |

All verifications passed. PR #47 created.
```

### PR Description Format (Collapsible)

The PR body uses collapsible `<details>` blocks so reviewers see a clean summary but can expand any section to inspect the raw terminal output. Each verification result gets its own block. The `PRBodyBuilder` assembles this from captured proof files — the agent does not write these sections.

```markdown
Closes #42

## Changes
- Implement order validation rules (domain layer)
- 11 unit tests for all validation scenarios

## Deterministic Checks

<details>
<summary>Lint (ruff) — PASS</summary>

All checks passed!

</details>

<details>
<summary>Format (ruff) — PASS</summary>

0 files would be reformatted

</details>

<details>
<summary>Types (ty) — PASS</summary>

Found 0 diagnostics

</details>

## Verification Plugins

<details>
<summary>Tests (pytest) — 11 passed</summary>

tests/unit/domain/validation/test_order_validator.py::test_valid_order PASSED
tests/unit/domain/validation/test_order_validator.py::test_insufficient_balance PASSED
...
11 passed in 2.1s

</details>

<details>
<summary>TDD Guard — PASS</summary>

All source files have corresponding test files.

</details>

## AI Reviews

<details>
<summary>Spec Alignment — 6/6 dimensions</summary>

entity_accuracy: 10/10
interface_compliance: 9/10
error_handling: 9/10
boundary_respect: 10/10
scope_compliance: 10/10
cross_cutting: 9/10

</details>

<details>
<summary>Code Review — 0 critical findings</summary>

No critical or high severity issues found.
1 info: consider extracting validation helper (non-blocking)

</details>

## Screenshots/Videos

<details>
<summary>Screenshots (2 captured)</summary>

![dashboard](screenshots/dashboard.png)
![order-form](screenshots/order-form.png)

</details>

Full proof: `.ydk/proofs/T-a1b2c3d4/`
```

### PR Comment Format (via `--pr` flag)

When `ydk verify run --pr <URL>` is used, verification results are automatically posted as a PR comment. This happens:
- During CI runs (verification posts results to the PR being tested)
- When an agent re-verifies after addressing review feedback
- For audit trail — each verification run is a separate comment with timestamp

```markdown
## Verification Run — 2026-04-24T14:30:00Z

| Check | Result | Duration | Cache |
|---|---|---|---|
| Lint (ruff) | PASS | 0.3s | hit |
| Types (ty) | PASS | 0.5s | hit |
| Tests (pytest) | 11 passed | 2.1s | miss |
| Spec Alignment | 6/6 dimensions | 12.4s | miss |

ALL PASSED (15.3s, 2 cache hits)
```

## Screenshots as Proof

For tasks that modify UI (web pages, CLI output, terminal interfaces):

**Web UIs:** YDK uses playwright (configurable) to capture screenshots of affected pages. The task's spec refs tell YDK which pages to capture.

**CLIs / Terminal UIs:** YDK captures terminal output of relevant commands.

**Configuration:**

```yaml
verification:
  screenshots:
    enabled: true
    tool: playwright          # or puppeteer, or terminal-capture
    pages:                    # URLs to capture (web UI)
      - url: http://localhost:3000/dashboard
        name: dashboard
      - url: http://localhost:3000/orders
        name: orders
    commands:                 # Commands to capture (CLI)
      - command: "ydk task list"
        name: task-list
```

## Deterministic Proof Capture

When an agent runs `ydk task done`, proof files are captured deterministically — the agent does **not** write the proof sections. The `ProofCapture` class owns this process entirely.

### The Flow

1. The **subagent** runs `ydk task done --summary "Agent narrative here"` **in its own worktree** — the subagent owns the full lifecycle from implementation through PR creation
2. `ProofCapture` runs each quality gate (`ruff check`, `ruff format --check`, `ty check`, `pytest`) via `capture_command()` and saves raw stdout+stderr to `.ydk/proofs/<task-id>/`
3. The agent's `--summary` flag writes `summary.md` — the **only** agent-authored content
4. `PRBodyBuilder` assembles the PR body from a deterministic template + proof files + agent summary
5. The PR is created with this assembled body — proof sections reflect **actual command output**, not agent claims

### Proof File Layout

```
.ydk/proofs/T-abc123/
├── summary.md          # Agent-authored narrative (only agent-written file)
├── ruff-check.txt      # Actual ruff check output
├── ruff-format.txt     # Actual ruff format --check output
├── ty-check.txt        # Actual ty check output
├── pytest.txt          # Actual pytest output
├── verification.json   # Structured verification report (ProofArtifacts model)
├── screenshots/        # Playwright screenshots (if captured)
│   └── after-submit.png
└── session.webm        # Playwright video recording (if captured)
```

### Subagent Owns the Lifecycle

The subagent dispatched for a task owns everything from `ydk task start` through `ydk task done`:

1. `ydk task start` — claims the task, creates a worktree, bootstraps context
2. Agent implements in the worktree (tests first, then code)
3. `ydk task done` — runs `ProofCapture`, assembles PR via `PRBodyBuilder`, creates PR
4. The orchestrator only sees the resulting PR URL — it does not participate in implementation

This means the subagent calls `ydk task done` from inside its worktree. The proof capture runs commands against the worktree's files, ensuring the proof matches exactly what the PR contains.

### Video Capture for E2E Flows

For tasks that involve UI changes, `VideoCapture` uses Playwright to record the browser session:

```bash
ydk visual record --url http://localhost:3000 --actions-file actions.json --output .ydk/proofs/T-abc123/
```

Videos are included in the PR body as links. The actions file specifies browser interactions:

```json
[
  {"type": "fill", "selector": "#email", "value": "test@example.com"},
  {"type": "click", "selector": "#submit-btn"},
  {"type": "wait", "ms": 2000},
  {"type": "screenshot", "name": "after-submit"}
]
```

### Standalone Verification Capture

To capture verification output without completing a task:

```bash
ydk verify run --capture --task-id T-abc123
```

This saves all gate outputs to `.ydk/proofs/T-abc123/` for inspection.

## What Happens When Proof Fails

If any verification fails, `ydk task done` refuses to create the PR. The agent sees:

```
VERIFICATION FAILED

✓ Lint: pass
✓ Types: pass
✓ Tests: 11 passed
✗ Spec Alignment: FAILED (2/6 dimensions below threshold)
  - interface_compliance: 6/10 — error response shape doesn't match spec
  - cross_cutting: 5/10 — timestamps not in UTC ISO 8601

Fix the issues and run `ydk task done` again.
Tip: try `ydk verify run --retry 3 --repair` for auto-repair.
```

The agent must fix the code and re-run. There is no bypass.

## Why This Matters

Without proof-based development, the human must:
- Read every line of code the agent wrote
- Mentally verify it matches the spec
- Run tests manually to check they pass
- Look for security issues by reading code

With proof-based development, the human reviews:
- A proof table showing all checks passed
- Screenshots showing the UI is correct
- An AI review with no critical findings
- A spec alignment report with all dimensions green

The diff is still there for detailed review if wanted. But the proof tells you at a glance: this is trustworthy.
