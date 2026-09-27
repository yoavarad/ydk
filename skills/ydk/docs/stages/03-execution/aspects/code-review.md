# Code Review

## Why External Review

Self-review is biased. The agent that wrote the code is the least qualified to review it — it already "thinks" the code is right. External review uses a fresh perspective that sees the code for the first time, with no sunk-cost attachment.

## How It Works

Code review happens in-session, before creating the PR: the executing agent spawns a review pass (e.g. the `cavecrew-reviewer` subagent, or the code-review skill) against the diff. There is no pre-push plugin or LLM API call — the review is part of the agent's own workflow for the task.

## Review Perspectives

### Spec Compliance
Focus: Does the code match the spec (narratives + component manifests)?
- Overlaps with spec alignment but reviews at a higher level
- Looks for semantic correctness, not just structural matching
- Checks that component manifest definitions are faithfully implemented
- "The spec says orders should be atomic — is the implementation actually atomic?"

### Security
Focus: Are there security issues?
- Injection vulnerabilities (SQL, command, XSS)
- Auth bypass possibilities
- Data exposure (logging sensitive data, returning too much in errors)
- Hardcoded secrets or credentials
- Missing input validation

### Quality
Focus: Is the code well-written?
- Naming clarity (do function/variable names describe what they do?)
- Code structure (appropriate abstractions, no god functions?)
- Test quality (do tests actually verify behavior, not just coverage?)
- Error handling (are errors handled, not swallowed?)
- Consistency with existing codebase patterns

## Running It

Run the review as part of finishing a task, before opening the PR:

```bash
# Delegate to the reviewer subagent
# (see caveman:cavecrew-reviewer, or the code-review skill)
```

There is no `ydk verify review` command — this is agent judgment applied in-session, not a deterministic CLI check.

## Review Output

The reviewer reports findings directly in the conversation, one per issue, tagged by severity:
- **Critical** — blocking, must fix before `ydk task done`
- **Warning** — should fix, but not blocking
- **Info** — suggestion, optional

## Blocking vs Non-Blocking

- **Critical** findings should be fixed before the agent proceeds
- **Warning** findings are worth addressing but don't block
- **Info** findings are suggestions the agent can choose to act on
