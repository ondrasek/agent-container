# Feature Specification: Durable Host Inventory

**Feature Branch**: `014-host-inventory`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Host history tracked at user level — a durable record of what the tool has deployed, where, and when. Prerequisite for the kill switch."

## Overview

The tool can only see what is **currently answering**.

`list` is live-reconciled: it asks each registered host's daemon what exists and reconciles that
against local port state. This is the right design for *"what is running now"*, and it was made
fail-closed deliberately so an unreachable host renders as `unreachable` rather than as zero
containers. But it means the tool has **no memory**. It cannot answer:

- What did I deploy last week, and where?
- Is there a container on a host I have since removed from the registry?
- Something is billing me — did this tool create it?

That last question is the sharp one. A container on an unreachable, forgotten or deprovisioned
host is invisible to a tool that only asks live daemons — and invisible is indistinguishable from
gone. Constitution I says the *container* is disposable; it does not say the **record** of it
should be.

This feature gives the tool a durable, operator-machine-level inventory of everything it has
created: what, where, when, and what became of it.

> **It is also the prerequisite for a kill switch.** You cannot reliably destroy what you cannot
> enumerate, and enumerating by asking live hosts fails exactly when a kill switch matters most —
> when something is wrong, unreachable, or forgotten.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remember everything the tool created (Priority: P1)

Every environment the tool creates is recorded on the operator's machine, and that record
survives the container, the host and the registry entry. The operator can ask what exists —
including things no live daemon will admit to.

**Why this priority**: Without the record there is no feature, and no kill switch. It is also the
only part that must be right from the first release: a record that begins late has a permanent
blind spot.

**Independent Test**: Create environments across two hosts, remove one host from the registry,
stop one container, and confirm the inventory still accounts for all of them with an accurate
state for each.

**Acceptance Scenarios**:

1. **Given** an environment is created, **When** the operator inspects the inventory, **Then** it
   records what was created, on which host, and when.
2. **Given** a host is removed from the registry, **When** the operator inspects the inventory,
   **Then** environments created on it are still listed, marked as belonging to a host no longer
   registered.
3. **Given** an environment is torn down through the tool, **When** the operator inspects,
   **Then** it is recorded as gone rather than silently dropped.
4. **Given** an environment removed **outside** the tool, **When** the operator inspects, **Then**
   the discrepancy is visible — the inventory does not claim it still exists.

---

### User Story 2 - Reconcile memory against reality (Priority: P1)

The operator can compare what the tool remembers with what hosts actually report, and see the
differences: things remembered but gone, things present but unrecorded, things on hosts that
cannot be reached.

**Why this priority**: A record that silently diverges from reality is worse than none, because
it is trusted. Reconciliation is what keeps the inventory honest, and it is what a kill switch
will act on.

**Independent Test**: Create a container outside the tool and delete one created by it, then
confirm reconciliation reports both discrepancies distinctly.

**Acceptance Scenarios**:

1. **Given** an environment recorded but absent from its host, **When** reconciling, **Then** it
   is reported as *missing*, not quietly deleted from the record.
2. **Given** a container present on a host but never recorded, **When** reconciling, **Then** it
   is reported as *unrecorded* — the tool must not claim ownership of what it did not create.
3. **Given** an unreachable host, **When** reconciling, **Then** its environments are reported as
   *unknown*, never as missing (Feature 002's fail-closed rule).
4. **Given** everything agrees, **When** reconciling, **Then** the result is unambiguous and
   quiet.

---

### User Story 3 - Account for what a deployment costs to leave running (Priority: P3)

For environments on hosts the tool provisioned, the operator can see how long each has existed —
enough to notice something forgotten and still billing.

**Why this priority**: Real, and the motivating anxiety behind the kill switch, but it depends
entirely on US1/US2 and adds no safety of its own. Lowest priority deliberately.

**Independent Test**: Create an environment, wait, and confirm the inventory reflects its age and
whether its host is one the tool provisioned.

**Acceptance Scenarios**:

1. **Given** a long-lived environment, **When** the operator inspects, **Then** its age is
   evident without arithmetic.
2. **Given** a tool-provisioned host, **When** the operator inspects, **Then** it is
   distinguishable from a host the operator registered but did not create.

---

### Edge Cases

- **A write that fails** (disk full, permissions) — must not fail the deploy it is recording, but
  must not silently lose the record either; an unrecorded environment is the exact blind spot
  this feature exists to remove.
- **Two invocations at once** — the record must not be corrupted by concurrent writes.
- **A container created outside the tool** — must never be claimed as the tool's own.
- **A host that is unreachable, versus one that is gone** — must be distinguishable; conflating
  them makes reconciliation lie.
- **The record is deleted or missing** — must degrade to today's live-only behaviour, not fail.
- **The record disagrees with local port state** — one of them must be authoritative, stated.
- **An environment recreated with the same name** — must not silently overwrite the history of
  the previous one.
- **Sensitive values** — nothing recorded may contain a credential, token or key.
- **Unbounded growth** — the record must not grow without limit on a machine used for years.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST durably record every environment it creates: what, on which host,
  and when.
- **FR-002**: The record MUST live at **user level**, on the operator's machine, independent of
  any project and of any host.
- **FR-003**: The record MUST survive the container's removal, the host's removal from the
  registry, and the host's deprovisioning.
- **FR-004**: The tool MUST record the **outcome** of an environment — still expected, torn down
  through the tool, or discovered absent.
- **FR-005**: The operator MUST be able to **reconcile** the record against what hosts report,
  and see three distinct classes: recorded-but-missing, present-but-unrecorded, and unknown.
- **FR-006**: An unreachable host MUST yield **unknown**, never *missing* — consistent with the
  existing fail-closed rule.
- **FR-007**: The tool MUST NOT claim ownership of a container it did not create.
- **FR-008**: A failure to write the record MUST NOT fail the operation being recorded, but MUST
  be surfaced — a silently unrecorded environment is the blind spot this feature removes.
- **FR-009**: Concurrent invocations MUST NOT corrupt the record.
- **FR-010**: **No credential, token or key value** may be written to the record (Constitution
  III).
- **FR-011**: The record MUST be readable through the existing machine-readable interface.
- **FR-012**: The record MUST NOT grow without bound; its retention behaviour MUST be defined and
  documented.
- **FR-013**: If the record is absent or unreadable, the tool MUST degrade to today's live-only
  behaviour rather than fail.
- **FR-014**: Where the record and live state disagree, which is authoritative for which purpose
  MUST be defined and documented.
- **FR-015**: Recreating an environment with a previously-used name MUST NOT silently discard the
  earlier history.

### Key Entities *(include if feature involves data)*

- **Inventory entry**: one environment the tool created — its name, host, creation time, and
  current known outcome.
- **Host reference**: which host an entry belongs to, retained even after that host leaves the
  registry, and whether the tool provisioned it.
- **Reconciliation result**: the comparison of record against live state, classifying each entry
  as agreeing, missing, unrecorded, or unknown.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every environment created through the tool appears in the inventory — **100%**.
- **SC-002**: An entry remains after its container, its host registration, and its host are all
  gone — **100%**.
- **SC-003**: Reconciliation classifies every entry into exactly one of agreeing / missing /
  unrecorded / unknown — **zero** unclassified.
- **SC-004**: An unreachable host never produces a *missing* classification — **zero**
  occurrences.
- **SC-005**: A container not created by the tool is never claimed — **zero** false ownership.
- **SC-006**: No credential value appears in the record — **100%** of runs.
- **SC-007**: Concurrent invocations produce no corrupted or lost entries — **zero** across a
  concurrency test.
- **SC-008**: With the record absent, every existing command behaves exactly as before — **zero**
  regressions.

## Assumptions

- **The record is a memory aid, not a source of truth about the present.** Live state is
  authoritative for *"what is running"*; the record is authoritative for *"what we created"*.
  FR-014 requires that division be stated rather than inferred.
- **User level, not project level.** An operator deploys the same project to several hosts and
  several projects to one host; the question *"what have I got running"* is about the operator,
  not the project — and it must survive deleting the project.
- **Recording is a side effect of acting**, not a separate step an operator can forget.
- **This feature does not delete anything.** It remembers, compares and reports; acting on the
  result is the kill switch's job.
- Retention is bounded but generous — this is for a machine used for years, and the interesting
  entries are the old forgotten ones.

## Out of Scope

- Destroying or stopping anything (that is the kill switch).
- Cost or billing integration with any provider.
- Recording what an agent *did* inside a container (that is observability).
- Synchronising the record between machines.
- Managing containers the tool did not create.

## Dependencies

- **Feature 001 / 002 (hosts, lifecycle)**: the registry, per-host state, and the fail-closed
  enumeration rule FR-006 inherits.
- **Feature 006 (agent-as-code)**: provisioned hosts, whose deprovisioning must not erase history.
- **Feature 009 (agent-operable CLI)**: FR-011's machine-readable exposure.
- **Feature 011 (filesystem layout)**: the record is *derived host state*'s sibling — it must be
  placed per the settled vocabulary, and it is **not** configuration.
- **Constitution I (ephemerality)**: the container is disposable; the record of it is not.
- **Constitution III (least exposure)**: FR-010.
