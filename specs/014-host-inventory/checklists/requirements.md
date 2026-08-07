# Specification Quality Checklist: Durable Host Inventory

**Purpose**: Validate specification completeness and quality before proceeding to planning

**Created**: 2026-07-29

**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

**Clarified 2026-07-29** (two passes). All items settled.

First pass (cross-cutting): two stores, not one; the inventory lives outside `<state>/<host>/`
because that directory dies with the host it is named for.

Second pass:

- **Outcomes** are a closed set of four: `active` / `removed` / `vanished` / `host-gone`. The
  distinction between the last two is **what disappeared** — the environment or its host — not
  who caused it. `unknown` is deliberately excluded: it is computed at reconciliation, never
  stored.
- **Retention**: keep everything indefinitely, with a large backstop cap. One row per environment
  ever created makes the volume concern largely theoretical, and the entries worth having are the
  old forgotten ones that age-based pruning removes first.
- **Identity**: a generated id per deployment, so FR-015 holds **by construction** — there is no
  overwrite path to get wrong. A reused name is simply several entries.
- **Reconciliation**: explicit command, plus a one-line hint in `list`. A discrepancy an operator
  must already suspect in order to look for is one nobody finds.

Nothing outstanding.
