# Specification Quality Checklist: Scaffold a new agent project

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-31
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

**Validated 2026-08-31, single pass, all items pass.**

Checks worth recording, being the ones that could plausibly have failed:

- **No implementation details**: the spec names no command name, no flag, no
  filename, and no file format. It says "a project directory", "a starting
  specification", "the verb that validates the result" — the *shape* of the
  obligation without the syntax that will express it. FR-008 is the sharpest case:
  it requires per-agent configuration to be written where that agent reads it,
  without naming any agent or path, because which agents exist is design, while
  "inert configuration is a silent failure" is the requirement.
- **The central criterion is falsifiable**: SC-001 ("validates on the first
  attempt, zero edits, 100% of scaffolds") is the one that makes this feature
  either work or not, and it can be tested by running the tool's own validation
  against the tool's own output. FR-002 states the same obligation as a
  requirement, deliberately: a scaffold whose output the tool rejects is a defect,
  and that has to be a stated contract rather than a hope.
- **Refusal requirements state WHEN**: FR-004, FR-007, FR-009 and FR-011 all say
  the refusal happens *before* anything is written, and SC-008 asserts the
  directory is left exactly as found. Without the timing, "it refuses" is
  compatible with refusing after a partial write.
- **Constitution III / IX**: FR-013, FR-014 and FR-015 make the no-secret property
  a requirement of the generated *artifacts* — a scaffold writes files that get
  committed, so it is a place where a secret could enter a repository through a
  path nobody was watching. FR-015 also forbids minting keys, matching the
  standing rule that a tool-generated key would be a credential nobody chose.
- **Constitution VIII**: FR-006 requires every applied default to be **named and
  reported**, and SC-006 makes "what I chose vs what was chosen for me"
  distinguishable from the output. This is the principle most at risk in a
  scaffolding feature, whose entire job is filling in values on the operator's
  behalf.

**Deliberate dependency, not a gap**: US4 and FR-019/FR-020 consume *named
configuration variants*, which are specified separately. This feature is complete
and shippable without them; US4 is P3 and separable precisely so that ordering is
free.

**Owed at planning time**: a threat-model row. A scaffold writes files that are
likely to be committed, which is a new way for material to enter a repository —
the argument for FR-013/FR-014 needs to be made there, not only asserted here.
