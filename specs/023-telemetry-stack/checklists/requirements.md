# Specification Quality Checklist: Telemetry stack container

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-04
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

**Re-validated after clarification (session 2026-09-04).** All 16 items still pass; no
regressions. Five decisions were resolved and each tightened a requirement rather than
adding one:

- **Namespace** — FR-009a now makes a name identify exactly one container of any kind on a
  host. The original FR-009 guarded only stack-vs-stack collision, which would have allowed
  an agent environment and a stack to answer to the same handle: worst precisely when an
  operator is trying to stop one of them.
- **Restart semantics** — FR-007 previously said "report the existing one", conflating
  running with stopped. A host reboot is the ordinary way a stack becomes stopped, and
  recovery must not cost the data the stack exists to hold.
- **Exposure** — chosen as NAMED LEVELS over an explicit bind address, against the
  recommendation. The risk that trade introduces is that a level hides what actually bound,
  and it is real: on some runtimes a container cannot reach a service bound to the host
  loopback. FR-018b answers it by requiring the resolved addresses to be STATED, so the
  abstraction stays inspectable.
- **Readiness** — FR-006a names the 180s budget (Constitution VIII), and FR-006b requires
  the failure to say WHICH stage expired. "Timed out" spans a slow registry, a container
  that will not start, and an ingest that never opens: three fixes, one message.
- **Retention** — both a window and a ceiling (FR-025), plus FR-025b requiring effective
  retention to be reportable, so an evicted run reads as evicted rather than as telemetry
  that was never recorded.


Two iterations were needed; both findings are recorded because they were the
substance of the review rather than tidying.

**Vendor names were moved out of the requirements.** The first draft named the
image, the ports and the query languages in FR text. Those are the *current*
answer to "which stack", and FR-008 exists precisely because that answer must be
replaceable — so naming it in a requirement would have frozen the choice the
requirement is designed to keep open. They now appear only in the Input quote and
as an Assumption.

**"Reachable" was split into two addresses.** The draft asked for "the endpoint"
as though there were one. There is not: on every runtime where containers do not
share the operator's loopback, the address an operator opens and the address an
agent container exports to differ, and conflating them is the single most likely
way for this feature to produce a stack that looks up and receives nothing.
FR-013 now states the distinction as a requirement, and SC-003 tests the printed
value verbatim rather than testing that *an* endpoint works.

**Deliberately not specified**: which dashboards ship. The spec requires that a
fresh stack answers "what did this run do" (FR-014, FR-017, SC-004) and leaves the
panel inventory to planning, since the useful set follows from what the emitters
actually produce — which Feature 017 work showed varies by agent.
