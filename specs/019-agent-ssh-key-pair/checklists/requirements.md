# Specification Quality Checklist: The Agent SSH Key Pair Is Generated In the Container

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-15
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

**The marker is resolved.** FR-011 is settled: probe the forge **from inside the container** (the
operator's machine holds no private key and cannot answer), fail **soft**, and cache nothing —
registration lives on the forge and a stored answer goes stale the moment a key is revoked.

**A second decision arrived at plan time**, not from the spec: `clone_credential_precheck` refuses to
start when `--repo` is an SSH URL and no key was supplied, which is a premise this feature
inverts. Settled as two-phase (boot, register, redeploy) and recorded as FR-013, which relaxes FR-014's
empty-workspace refusal for that case alone.

**One requirement deliberately amends another feature**, and that is called out rather than smuggled:
FR-003 puts self-generated push material on a persisted volume, which Feature 003's rule forbids for
push material generally. The spec states the amendment, its scope (self-generated only), and the reason
the original rule does not apply.
