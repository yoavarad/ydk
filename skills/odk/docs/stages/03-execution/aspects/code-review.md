# Code Review

## Why External Review

Self-review is biased. The agent that wrote the code is the least qualified to review it — it already "thinks" the code is right. External review uses independent agents that see the code for the first time, with fresh eyes and no sunk-cost attachment.

## How It Works

Before creating the PR, ODK spawns 1-3 review agents in parallel. Each agent has a different perspective and evaluates the diff against different criteria.

## Review Perspectives

### Spec Compliance Reviewer
Focus: Does the code match the spec (narratives + component manifests)?
- Overlaps with spec alignment check but reviews at a higher level
- Looks for semantic correctness, not just structural matching
- Checks that component manifest definitions are faithfully implemented
- "The spec says orders should be atomic — is the implementation actually atomic?"

### Security Reviewer
Focus: Are there security issues?
- Injection vulnerabilities (SQL, command, XSS)
- Auth bypass possibilities
- Data exposure (logging sensitive data, returning too much in errors)
- Hardcoded secrets or credentials
- Missing input validation

### Quality Reviewer
Focus: Is the code well-written?
- Naming clarity (do function/variable names describe what they do?)
- Code structure (appropriate abstractions, no god functions?)
- Test quality (do tests actually verify behavior, not just coverage?)
- Error handling (are errors handled, not swallowed?)
- Consistency with existing codebase patterns

## Review Configuration

In `.odk/config.yaml`:

```yaml
verification:
  review_models:
    - us.anthropic.claude-sonnet-4-6-v1:0     # Fast, good for most reviews
    # Can add more for multiple perspectives:
    # - us.anthropic.claude-opus-4-6-v1:0      # Deeper analysis
  review_perspectives:
    - spec_compliance
    - security
    - quality
```

## Running It

```bash
odk verify review                # Run all configured review agents
odk verify review --verbose      # Show full review comments
```

Runs automatically as part of `odk verify all` and pre-push hook.

## Review Output

Each review agent returns:
- **Pass/Fail** — are there blocking issues?
- **Comments** — specific findings on specific code sections
- **Severity** — critical (blocks PR), warning (should fix), info (suggestion)

```json
{
  "reviews": [
    {
      "perspective": "spec_compliance",
      "passed": true,
      "comments": []
    },
    {
      "perspective": "security",
      "passed": false,
      "comments": [
        {
          "severity": "critical",
          "file": "app/routes/orders.py",
          "line": 42,
          "comment": "User input passed directly to SQL query without parameterization"
        }
      ]
    },
    {
      "perspective": "quality",
      "passed": true,
      "comments": [
        {
          "severity": "info",
          "file": "app/services/order_service.py",
          "line": 15,
          "comment": "Consider extracting the price calculation into a separate method for testability"
        }
      ]
    }
  ]
}
```

## Blocking vs Non-Blocking

- **Critical** findings block `odk task done` — the agent must fix them
- **Warning** findings are posted to the issue but don't block
- **Info** findings are suggestions — agent can choose to act on them

## Parallelization

All review agents run in parallel via asyncio. With Bedrock prompt caching, the diff content is cached and shared across all reviewers — the first reviewer pays full cost, subsequent reviewers get ~90% reduction.

Typical timing: 3 parallel reviewers complete in ~20-30 seconds.
