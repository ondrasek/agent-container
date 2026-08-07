# Specification Quality Checklist: `doctor` — Preflight Validation

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

**Clarified 2026-07-29.** Both listed items are settled, plus two more:

- **Name**: `doctor`. Verified `status` is genuinely taken — it is an alias of `plan` and answers
  whether a *declared spec has converged*, not whether a deploy would work.
- **Image freshness**: a version label stamped at build, compared locally. No registry
  round-trip, so it stays in the default pass.
- **Exit status**: `0` deploy-would-work, `1` blocking, `2+` doctor itself failed. Advisories exit
  `0` deliberately, so `doctor && up` stays viable — a diagnostic people stop chaining is one
  nobody runs.
- **Default scope**: this project's environments plus machine-level state; a name narrows it.

One consequence surfaced while integrating and is now FR-012b: **an image with no version stamp
must report *unknown***, not stale and not fresh. Every image built before this feature is
unstamped, so calling them stale would nag every operator into a rebuild they may not need, and
calling them fresh would assert something unknown. It is the FR-006 rule applied to the case that
will actually be common on day one.

Nothing outstanding.
