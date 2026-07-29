# Feature Specification: Kill Switch

**Feature Branch**: `015-kill-switch`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "A kill switch — stop everything this tool is running, everywhere, in one action."

## Overview

Stopping one environment is easy. Stopping **everything** is not, and the situations where an
operator wants to are exactly the situations where doing it by hand goes wrong: a key is leaked,
an agent is looping, a bill is climbing, or the operator simply cannot remember what they left
running and where.

Today that requires knowing every host, reaching every host, and issuing a command per
environment. Every step can fail partway, and a partial stop is the worst outcome — the operator
believes they have stopped, and something is still running.

This feature provides one deliberate action that stops everything the tool owns, across every
host it knows about, and **tells the truth about what it could not reach**.

> **It is only as good as the inventory behind it.** Enumerating by asking live daemons fails
> precisely when a kill switch matters most — an unreachable host, a forgotten one, a
> deprovisioned one. This feature therefore acts on the durable inventory (Feature 014), not on
> whatever happens to answer.

The hardest requirement here is not stopping things. It is being **honest about failure**: an
operator reaching for a kill switch is already having a bad day, and a report that overstates
success is worse than an error.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stop everything, and know what didn't stop (Priority: P1)

An operator issues one command. Every environment the tool knows about is stopped. The result
states plainly what stopped, what did not, and what could not be determined.

**Why this priority**: The feature. A version that stops most things and reports success would be
actively dangerous.

**Independent Test**: With environments across a reachable and an unreachable host, invoke the
kill switch once and confirm the reachable ones stop, the unreachable one is reported as
undetermined, and the exit result reflects incomplete success.

**Acceptance Scenarios**:

1. **Given** environments on reachable hosts, **When** the kill switch runs, **Then** all of them
   stop.
2. **Given** one host is unreachable, **When** the kill switch runs, **Then** the others still
   stop — one failure does not abort the rest.
3. **Given** anything could not be stopped or confirmed, **When** the command finishes, **Then**
   it says so explicitly and does **not** report overall success.
4. **Given** the operator re-runs it, **When** everything is already stopped, **Then** it
   succeeds without error — the action is repeatable.

---

### User Story 2 - Choose how far it goes (Priority: P1)

The operator can distinguish *stop* — halt the containers, keep the data — from *destroy* —
remove the containers and their volumes. The destructive form is never the default and never
implicit.

**Why this priority**: A kill switch that only stops is insufficient for a leaked credential; one
that always destroys is unusable for a runaway agent whose work is worth keeping. Both are
needed, and confusing them is unrecoverable. P1 because getting this boundary wrong causes data
loss.

**Independent Test**: Run the stopping form and confirm data survives; run the destroying form
and confirm it is refused without explicit confirmation.

**Acceptance Scenarios**:

1. **Given** the stopping form, **When** it completes, **Then** containers are halted and their
   volumes remain intact.
2. **Given** the destroying form, **When** invoked without explicit confirmation, **Then** it
   refuses.
3. **Given** the destroying form with confirmation, **When** it completes, **Then** the
   environments and their volumes are gone and the inventory records that.
4. **Given** any form, **When** the operator asks beforehand, **Then** they can see exactly what
   would be affected without affecting it.

---

### User Story 3 - Stop a subset (Priority: P2)

The operator can scope the action — one host, or environments matching some criterion — rather
than everything.

**Why this priority**: Useful and likely the common case in practice, but "everything" is the
case that cannot be done reliably by hand, so it comes first.

**Independent Test**: Scope the action to one host and confirm environments on other hosts are
untouched.

**Acceptance Scenarios**:

1. **Given** a scope, **When** the action runs, **Then** only matching environments are affected
   and the report says what was excluded.
2. **Given** a scope matching nothing, **When** the action runs, **Then** it says so rather than
   silently doing nothing.

---

### Edge Cases

- **A host that is unreachable** — must be reported as undetermined, never as stopped. This is
  the single most important behaviour in the feature.
- **A container the tool did not create** — must never be stopped, even when it looks like one of
  the tool's (Feature 014's ownership rule).
- **A host removed from the registry but with environments recorded** — must still be attempted,
  and its state reported.
- **A deprovisioned host** — the environments are gone with it; must be reconciled, not reported
  as failures.
- **Interruption partway** — must leave a truthful record; a resumed or repeated run must be safe.
- **Concurrent lifecycle operations** — must not corrupt state or produce a partial teardown that
  looks complete.
- **Nothing to stop** — must be an unambiguous success, not an error.
- **The inventory is absent** — the feature must refuse rather than fall back to "whatever
  answers", because a kill switch that silently narrows its scope is a false guarantee.
- **A stop that appears to succeed but does not** — must be verified, not assumed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST provide a single action that stops every environment it owns across
  every host it knows of.
- **FR-002**: The action MUST enumerate from the **durable inventory**, not from whatever hosts
  currently answer.
- **FR-003**: A failure against one host or environment MUST NOT prevent the action proceeding
  against the others.
- **FR-004**: The result MUST distinguish **stopped**, **not stopped**, and **could not be
  determined**, per environment.
- **FR-005**: If anything was not stopped or not confirmed, the action MUST NOT report overall
  success.
- **FR-006**: A **stopping** form and a **destroying** form MUST both exist, and destruction MUST
  never be the default or implicit.
- **FR-007**: The destroying form MUST require explicit confirmation, consistent with the
  existing confirmation idiom.
- **FR-008**: The operator MUST be able to preview exactly what would be affected **without
  affecting it**.
- **FR-009**: The action MUST NOT touch a container the tool did not create.
- **FR-010**: The action MUST be **repeatable**: running it when everything is already stopped
  succeeds without error.
- **FR-011**: The action MUST be scopeable to a subset, and MUST state what it excluded.
- **FR-012**: Outcomes MUST be written to the inventory, so a later run and a later audit both
  reflect what happened.
- **FR-013**: If the inventory is unavailable, the action MUST **refuse** rather than silently
  fall back to live enumeration — a kill switch that narrows its own scope is a false guarantee.
- **FR-014**: A stop MUST be **verified**, not assumed from a command exiting zero.
- **FR-015**: The result MUST be available through the existing machine-readable interface,
  including the per-environment outcomes.
- **FR-016**: Interruption partway MUST leave a truthful record, and a repeated run MUST be safe.

### Key Entities *(include if feature involves data)*

- **Kill action**: one invocation — its scope, its form (stop or destroy), and its per-environment
  outcomes.
- **Outcome**: what happened to one environment — stopped, already stopped, failed, or
  undetermined.
- **Scope**: which environments an invocation targets; everything, by default.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With environments on N reachable hosts, one invocation stops **all** of them.
- **SC-002**: An unreachable host is reported as undetermined and **never** as stopped — **zero**
  occurrences across repeated tests.
- **SC-003**: Any incomplete run reports overall failure — **zero** runs that report success while
  something is unstopped or unconfirmed.
- **SC-004**: A container not created by the tool is never affected — **zero** occurrences.
- **SC-005**: The stopping form preserves all volumes — **100%** of runs.
- **SC-006**: The destroying form without confirmation performs **zero** destructive operations.
- **SC-007**: Preview affects nothing — verified by comparing state before and after — **100%**.
- **SC-008**: A repeated invocation after a complete run succeeds without error — **100%**.
- **SC-009**: With the inventory unavailable, the action refuses — **zero** silent fallbacks.

## Assumptions

- **Honesty outranks completeness.** An operator reaching for this is already in trouble; a
  report that overstates success is worse than an error, because it ends the investigation.
- **Stop is the default; destroy is deliberate.** The common emergencies — a looping agent, a
  suspected leak — are served by stopping, and stopping is recoverable. Destruction is not.
- **The inventory is a hard dependency, not an optimisation.** Feature 014 must land first; this
  feature refuses to operate without it rather than degrading to live enumeration.
- **Verification is part of stopping.** A command that exits zero is not evidence; the tool
  confirms, because this is the one action where a wrong answer is most costly.
- Speed matters less than truth. This may take time against slow hosts, provided it reports
  accurately.

## Out of Scope

- Restarting or restoring anything.
- Stopping containers the tool did not create.
- Cost or billing action beyond stopping what the operator is paying for.
- Scheduled or automatic triggering — this is deliberate and operator-invoked.
- Remote invocation from another device (that is the control-plane feature).

## Dependencies

- **Feature 014 (durable host inventory)**: a hard prerequisite — the enumeration source and the
  ownership rule.
- **Feature 002 (lifecycle verbs)**: the existing stop/down/purge/wipe semantics, the per-`(host,
  name)` lock, and the confirmation idiom FR-007 follows.
- **Feature 006 (agent-as-code)**: provisioned hosts, whose deprovisioned environments must
  reconcile rather than fail.
- **Feature 009 (agent-operable CLI)**: FR-015's machine-readable outcomes.
- **Constitution I (ephemerality)**: stopping is safe precisely because durable work is pushed,
  not held in a container.
