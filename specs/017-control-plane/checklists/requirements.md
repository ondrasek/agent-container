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

**Clarified 2026-07-29 and 2026-07-30.** All items settled.

First pass — the question that decided viability: the control plane **mints its own** keypair
in-container, encrypted at rest, unlocked by an operator-held passphrase on every connect. The
tool never handles the private key, so this **fits** Constitution III's operator-interactive
carve-out rather than needing an exception. Daemon access needs no second credential, since remote
daemon access is already `ssh://user@host` — capability is decided by where the public half is
authorised, which makes scope and revocation enforceable outside the container.

Second pass:

- **Self-termination**: refuse and exclude itself, reporting the exclusion. The control plane is
  the one container whose stopping makes the report undeliverable, so self-exclusion is what makes
  FR-010's guarantee achievable at all.
- **Narrower image** (FR-015a): no agent CLIs, so "no agents in the control plane" is a property
  rather than a rule. Accepted cost is a second image — and it reaches outside this feature, which
  is now recorded under Dependencies: Feature 013's version stamp applies to both images, and the
  existing agent-list agreement test must learn that this image installs **none**, or it will fail
  correctly on a Dockerfile that omits them.
- **Lost passphrase**: no recovery, by design — a recovery path is a way to get the key without
  the passphrase. Redeploy, re-authorise, withdraw the old key. FR-017 requires saying so **when
  the passphrase is printed**, not after it is lost.

Nothing outstanding.
