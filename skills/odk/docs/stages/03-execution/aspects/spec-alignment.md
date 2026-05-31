# Spec Alignment

## Why This Exists

The #1 trust problem in AI-assisted development: the agent implements something different from what the spec says. Not obviously wrong — subtly wrong. The error response shape is close but not exact. The validation is in the route handler instead of the domain layer. An enum value is missing.

Spec alignment catches drift BEFORE the PR is created.

## How It Works

1. ODK detects which files changed in the task
2. Reads the task's spec references (from the task issue)
3. Sends both (changed code + referenced spec sections) to an LLM evaluator
4. The evaluator checks 6 specific dimensions
5. Returns a scored report with specific findings

## The 6 Dimensions

### 1. Entity Accuracy

Does the implementation match the spec's entity definitions?

**Checks:**
- All fields present with correct types?
- Enums have all values from spec?
- State transitions match?
- Constraints (nullable, max length, FK) correct?
- Decimal precision correct?

**Example failure:** Spec says `status: enum [PENDING, FILLED, PARTIALLY_FILLED, CANCELLED]` but implementation has `status: enum [PENDING, FILLED, CANCELLED]` — missing PARTIALLY_FILLED.

### 2. Interface Compliance

Do the API endpoints match the spec's contracts?

**Checks:**
- Correct HTTP methods and paths?
- Request body shape matches spec?
- Response body shape matches spec?
- All status codes implemented?
- Error response shapes match exactly?

**Example failure:** Spec says error shape is `{type, title, status, detail}` (RFC 7807) but implementation returns `{detail: str}` (FastAPI default).

### 3. Error Handling Completeness

Are all error scenarios from the spec implemented?

**Checks:**
- Every error case from spec has a code path?
- Response shapes match?
- No silent error swallowing?
- Edge cases handled (timeout, race condition)?

**Example failure:** Spec defines 6 error scenarios for Place Order but implementation only handles 4. Missing: duplicate order detection and exchange timeout handling.

### 4. Boundary Respect

Is code in the architecturally correct location?

**Checks:**
- Validation in domain layer (not routes, not services)?
- Business logic in service (not adapter, not route)?
- Routes are thin (parse → delegate → format)?
- No prohibited import paths (routes importing domain directly)?

**Example failure:** Order validation checks are inside the route handler instead of `domain/validation/order_validator.py` as specified in the architecture section.

### 5. Scope Compliance

Did the agent stay within the task's declared scope?

**Checks:**
- Only files in the task's "files to create/modify" were touched?
- No features added beyond what the spec describes?
- No gold-plating (convenience methods, extra endpoints)?

**Example failure:** Task was "implement order validation" but agent also added a `GET /orders/stats` endpoint not in any spec.

### 6. Cross-Cutting Adherence

Does the code follow system-wide conventions?

**Checks:**
- Error format matches spec's cross-cutting section?
- Timestamps in correct format (UTC ISO 8601)?
- IDs are correct type (UUID v4)?
- Pagination follows spec pattern?
- Logging uses correct approach?

**Example failure:** Most endpoints return RFC 7807 errors but the new endpoint returns `{"error": "something went wrong"}`.

## Running It

```bash
odk verify spec-align                    # Check changed files against spec
odk verify spec-align --verbose          # Show detailed dimension analysis
```

Runs automatically as part of `odk verify all` and pre-push hook.

## The Output (Proof Artifact)

```json
{
  "spec_alignment": {
    "passed": false,
    "dimensions": {
      "entity_accuracy": {"score": 9, "passed": true,
        "detail": "All Order fields match spec"},
      "interface_compliance": {"score": 6, "passed": false,
        "detail": "Error response uses {detail:str} instead of RFC 7807"},
      "error_handling": {"score": 8, "passed": true,
        "detail": "All 6 error scenarios implemented"},
      "boundary_respect": {"score": 10, "passed": true,
        "detail": "Validation in domain layer as specified"},
      "scope_compliance": {"score": 10, "passed": true,
        "detail": "Only task-scoped files modified"},
      "cross_cutting": {"score": 6, "passed": false,
        "detail": "Error format doesn't match RFC 7807 cross-cutting spec"}
    }
  }
}
```

## When Drift Is Legitimate

Not all drift is bad. Sometimes reality forces a deviation:
- External API returns a status not in the spec (PARTIALLY_FILLED)
- A library doesn't support the specified approach
- A performance constraint makes the spec's design impractical

In these cases, the agent MUST:
1. Document the deviation in the task issue with evidence
2. Create a spec amendment PR (goes through Stage 01 brainstorming)
3. The spec alignment check will pass once the spec is updated

Legitimate drift: cites an external constraint with evidence.
Illegitimate drift: the agent made a design choice the spec didn't authorize.
