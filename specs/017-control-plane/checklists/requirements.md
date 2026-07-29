# Specification Quality Checklist: Control-Plane Container

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

**Clarified 2026-07-29.** Three of the four listed items are settled, including the one that
decided whether the feature was viable in this shape:

- **How host access is held**: the control plane **generates its own** keypair in-container,
  encrypted at rest, unlocked by an operator-held passphrase on every connect. The tool never
  handles the private key, so there is no injection channel to violate — this **fits**
  Constitution III's operator-interactive carve-out rather than needing an exception.
- **Revocation** is concrete: withdraw the public key from the hosts and containers that trust it,
  performed by the tool across them from one command.
- **Daemon access needs no separate credential.** Remote daemon access is already
  `ssh://user@host`, so the same keypair serves both; capability is decided by *where the public
  half is authorised*.

Still open for planning:

1. **Self-termination behaviour** (FR-010) — refuse, defer, or act on itself last.
2. **Whether the control plane runs the same image** as agent containers or a narrower one.
   Reusing it is cheaper; a narrower one carries less worth stealing, which matters more here
   than anywhere else in the roadmap.

One consequence to carry into planning: a control plane's public key is a **standing**
authorisation across many hosts and containers, including ones created later. Every prior feature
injected keys per deployment. That difference is the thing an attacker would target.
