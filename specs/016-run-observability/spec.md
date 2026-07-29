# Feature Specification: Run Observability

**Feature Branch**: `016-run-observability`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Observability — what did the agent actually do? A headless run exits with a code and leaves logs in the container; there is no durable record of what an agent changed, what it cost, or why it stopped."

## Overview

When an agent finishes, the evidence dies with the container.

A headless run exits with a status and writes logs into a container that is, by design,
disposable. Once it is torn down — which the tool encourages, and Constitution I assumes — there
is no answer to the questions an operator actually has afterwards:

- What did it change, and did it push?
- Why did it stop — finished, failed, killed, or out of budget?
- What did it cost?
- Which of last night's four runs is the one that broke the build?

The tool already guarantees the *work* survives: every agent commits and pushes, so code is never
trapped in a container. But the **account of the work** has no such guarantee. An operator can
recover what an agent wrote and not recover what it did, why, or at what price.

This feature gives each run a durable record that outlives its container.

> **It is deliberately not a log store.** Logs are voluminous, agent-specific and already
> retrievable while a container lives. What is missing is the small, structured, durable summary
> — the thing you can list, compare and search months later.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know what happened after the container is gone (Priority: P1)

Each run leaves a durable record: which environment and agent, what it was asked to do, when it
started and finished, and how it ended. The record survives teardown.

**Why this priority**: The whole feature. Everything else refines what the record contains.

**Independent Test**: Run an agent headlessly, tear the environment down completely, and confirm
the record is still retrievable and accurate.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the environment is torn down, **Then** the record remains
   retrievable.
2. **Given** several runs of one environment, **When** the operator lists them, **Then** each is
   distinguishable, in order, with how it ended.
3. **Given** a run that failed, **When** the operator inspects it, **Then** the record
   distinguishes *failed* from *finished* — and from *stopped by the operator*.
4. **Given** an interactive session rather than a headless run, **When** it ends, **Then** the
   behaviour is defined — recorded or deliberately not, but not accidental.

---

### User Story 2 - Connect a run to what it changed (Priority: P1)

The record links a run to its effect on the repository: what was committed and whether it was
pushed. An operator can go from *"something changed the build last night"* to the run that did it.

**Why this priority**: This is what makes the record worth keeping. A run summary with no link to
the work is a receipt with no purchase on it. P1 alongside US1 because the tool's central
promise — every agent commits and pushes — is precisely what makes this link possible and
expected.

**Independent Test**: Have an agent make and push a commit, then confirm the record identifies
that commit and its push status.

**Acceptance Scenarios**:

1. **Given** a run that committed and pushed, **When** the operator inspects it, **Then** the
   record identifies what was committed and confirms the push.
2. **Given** a run that committed but did **not** push, **When** inspected, **Then** that is
   visible — this is the failure mode Constitution I exists to prevent, so it must be loud.
3. **Given** a run that changed nothing, **When** inspected, **Then** that is stated plainly, not
   left ambiguous.

---

### User Story 3 - See what it cost (Priority: P2)

Where the agent reports usage, the record captures it, so an operator can see the cost of a run
and of an environment over time.

**Why this priority**: Genuinely wanted, but entirely dependent on what each agent chooses to
report, and useless without US1's record to attach it to. Its dependence on agent behaviour makes
it the least certain to deliver uniformly.

**Independent Test**: Run an agent that reports usage and one that does not; confirm the first is
captured and the second is explicitly *unknown* rather than zero.

**Acceptance Scenarios**:

1. **Given** an agent that reports usage, **When** the run completes, **Then** the record
   captures it.
2. **Given** an agent that reports nothing, **When** the run completes, **Then** the record says
   *unknown* — never zero, which would silently understate a total.
3. **Given** several runs, **When** the operator asks for an environment's total, **Then** any
   unknown component is stated rather than hidden.

---

### Edge Cases

- **A container killed before it could finish** — must still leave a record, marked as such; the
  interesting runs are often the ones that did not end cleanly.
- **A run that never started** (image missing, credential unresolvable) — must be distinguishable
  from one that started and failed.
- **A record write that fails** — must not fail the run itself, but must not be silent.
- **Concurrent runs** in different environments — must not interleave or overwrite records.
- **An agent that reports usage in its own units** — must not be normalised into a false
  equivalence between agents.
- **Secrets in a task or output** — nothing recorded may contain a credential; the task text
  itself may.
- **Unbounded growth** — a machine used for years must not accumulate without limit.
- **A run whose commits were later rewritten** — the record refers to history that may no longer
  exist; must degrade gracefully.
- **The agent's own logs** — remain the detail; the record must not pretend to replace them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every agent run MUST produce a durable record that survives the container's
  removal.
- **FR-002**: The record MUST identify the environment, the agent, the task given, and the start
  and end times.
- **FR-003**: The record MUST state **how the run ended**, distinguishing at least: finished,
  failed, stopped by the operator, and never started.
- **FR-004**: The record MUST link the run to its effect on the repository — what was committed
  and whether it was pushed.
- **FR-005**: A run that committed **without pushing** MUST be visible as such — this is the
  failure Constitution I exists to prevent.
- **FR-006**: Where an agent reports usage, the record MUST capture it; where it does not, the
  record MUST say **unknown**, never zero.
- **FR-007**: Aggregates MUST state when a component is unknown rather than silently excluding it.
- **FR-008**: A failure to write a record MUST NOT fail the run, but MUST be surfaced.
- **FR-009**: Concurrent runs MUST NOT interleave, overwrite or lose records.
- **FR-010**: **No credential value** may be written to a record (Constitution III).
- **FR-011**: Records MUST NOT grow without bound; retention MUST be defined and documented.
- **FR-012**: Records MUST be listable and retrievable through the existing machine-readable
  interface.
- **FR-013**: Whether **interactive** sessions are recorded MUST be a defined decision, not an
  accident of implementation.
- **FR-014**: The record MUST NOT attempt to replace the agent's own logs; its relationship to
  them MUST be stated.
- **FR-015**: Usage reported in agent-specific units MUST NOT be normalised into a false
  equivalence between agents.

### Key Entities *(include if feature involves data)*

- **Run record**: one agent execution — environment, agent, task, timing, and how it ended.
- **Repository effect**: what the run committed and whether it pushed.
- **Usage**: what the agent reported about cost or consumption, in its own terms, or *unknown*.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A run's record is retrievable after its environment is fully torn down — **100%**
  of runs.
- **SC-002**: Every record states how the run ended, from a closed set — **zero** ambiguous
  endings.
- **SC-003**: A run that committed without pushing is identifiable — **zero** such runs that look
  like clean successes.
- **SC-004**: An agent reporting no usage yields *unknown*, never zero — **zero** occurrences of
  a false zero.
- **SC-005**: No credential value appears in any record — **100%** of runs.
- **SC-006**: Concurrent runs across environments produce complete, non-interleaved records —
  **zero** losses under a concurrency test.
- **SC-007**: An operator can identify which of N runs changed a given file — verified for
  N ≥ 5.
- **SC-008**: A killed run still produces a record marked as such — **100%**.

## Assumptions

- **This is a summary, not a log.** Logs stay where they are and remain the detail; this record
  is the small durable thing you can list and compare later. Conflating them would produce a
  store nobody prunes and nobody reads.
- **Unknown is not zero.** For usage especially, a false zero silently understates a total, and a
  total that is quietly wrong is worse than one that admits a gap.
- **The commit link is what makes the record valuable.** The tool's central promise is that
  agents commit and push; the record inherits that as its anchor, which is why FR-005 exists.
- **Agent cooperation varies.** Some agents report usage, some do not, and none report it
  identically. The record accommodates that rather than inventing parity.
- Likely shares a durable store with the host inventory (Feature 014) — both are user-level and
  outlive the container. Deciding that once avoids building two.

## Out of Scope

- Storing or shipping the agent's logs.
- Real-time monitoring, dashboards or alerting.
- Cost estimation for agents that do not report usage.
- Anything about *what the agent should have done* — this records, it does not judge.
- Cross-machine aggregation.

## Dependencies

- **Feature 004 (agent execution)**: headless runs, exit status, and the task delivery whose text
  the record references.
- **Feature 014 (durable host inventory)**: the likely shared store, and the same user-level
  placement question.
- **Feature 015 (kill switch)**: a stopped run must be distinguishable from a failed one, and the
  kill switch is what stops it.
- **Feature 009 (agent-operable CLI)**: FR-012's machine-readable listing.
- **Constitution I (ephemerality)**: the commit-and-push promise the record anchors to, and the
  reason FR-005 matters.
- **Constitution III (least exposure)**: FR-010.
