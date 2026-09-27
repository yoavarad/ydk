# Spec Alignment

## Why This Exists

The #1 trust problem in AI-assisted development: the agent implements something different from what the spec says. Not obviously wrong — subtly wrong. The error response shape is close but not exact. The validation is in the route handler instead of the domain layer. An enum value is missing.

Spec alignment catches drift BEFORE the PR is created.

## How It Works

There is no automated LLM evaluator for this check. Spec alignment is judgment the executing agent applies in-session, before opening the PR:

1. Identify which files changed in the task
2. Re-read the task's spec references
3. Compare the changed code against the referenced spec sections across the 6 dimensions below
4. Note any drift and either fix it or document it as legitimate (see "When Drift Is Legitimate")

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

There is no `ydk verify` command for this check — it is not a deterministic gate and does not run in `ydk verify all` or the pre-push hook. The agent walks the 6 dimensions against the diff and the referenced spec sections before creating the PR, and records the result in the task summary (e.g. as a `cavecrew-reviewer` pass or plain narrative).

## When Drift Is Legitimate

Not all drift is bad. Sometimes reality forces a deviation:
- External API returns a status not in the spec (PARTIALLY_FILLED)
- A library doesn't support the specified approach
- A performance constraint makes the spec's design impractical

In these cases, the agent MUST:
1. Document the deviation in the task issue with evidence
2. Create a spec amendment PR (goes through Stage 01 brainstorming)
3. Spec alignment passes once the spec is updated to match the implementation

Legitimate drift: cites an external constraint with evidence.
Illegitimate drift: the agent made a design choice the spec didn't authorize.
