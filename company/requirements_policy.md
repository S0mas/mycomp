# Requirements Policy

This policy defines what makes a requirement acceptable for planning and implementation.
Edit this file to match your project standards — it is loaded by the evaluator for every review.

---

## Mandatory elements

Every requirement (top-level and sub-requirement) MUST have:

1. **A clear description** — state what the system must do, not how.
2. **Acceptance criteria** — at least one testable condition per sub-requirement.
   Write criteria in Given/When/Then format where applicable.
3. **Defined scope** — implementable by a single team in a single session.
   If a requirement spans multiple teams or months, it must be decomposed further.

---

## Clarity rules

- Use precise, unambiguous language. Avoid: "fast", "user-friendly", "scalable", "handle many".
- Quantify where possible: "response time < 200ms at p95", "support 500 concurrent users".
- Name specific actors: "authenticated user", "admin", "background job" — not "the system" or "users".

---

## Completeness rules

- Every happy path must have a corresponding error/failure path defined.
- Authentication, authorisation, and data ownership must be specified where they apply.
- External dependencies (third-party APIs, queues, storage) must be named explicitly.

---

## Feasibility rules

- Requirements must be achievable with the stated tech stack.
- No requirement may depend on an undefined or unavailable external system.
- Scope must be realistic for a single session; unrealistic scope is a policy violation.

---

## Automatic rejection triggers

Any of the following cause an automatic **reject** verdict:

- Fewer than 3 acceptance criteria across the entire submission.
- Acceptance criteria written as "it works" or "no errors".
- Requirements that describe UI aesthetics only, with no functional behaviour.
- Scope that would require more than one full sprint to implement.
- Missing actor: no statement of who performs or benefits from the requirement.
