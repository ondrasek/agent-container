# Feature Specification: Guided Setup Wizard (state-aware next-step guidance)

**Feature Branch**: `007-guided-wizard`

**Created**: 2026-07-22

**Status**: Draft

**Input**: User description: "Rethink the interactive wizard. It must guide the user through the entire setup, always suggesting the right next step. I.e. if the user does not have a host setup, it shall direct the user to setup host, when there is no docker image prepared and built, it shall guide the user to do that, etc. Displaying a menu of arbitrary steps does not help as it is not clear what to do when and why."

## Overview

The interactive wizard (what the operator gets when they run the tool with no
arguments) is today a **flat menu of every action** — provision, start, attach,
inject keys, logs, stop, purge — shown regardless of whether any of them can
succeed right now. The operator is left to know *which* action applies, *in what
order*, and *why*. For someone setting up their first environment, that is a dead
end: the tool knows the machine has no host registered, no image built, and no
container running, yet still asks the operator to choose from options that will
fail.

This feature replaces the flat menu with a **guided, state-aware flow**. Each time
the wizard runs (and after each action), it inspects the current state of the
environment, works out the single most useful **next step** on the path to a
working environment, and **leads with that recommendation and a plain-language
reason** — while still letting the operator override it. The wizard becomes a guide
that walks a newcomer from nothing to a running, attachable agent, and adapts to an
experienced operator's healthy or broken environments.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Zero to attached, guided the whole way (Priority: P1) 🎯 MVP

A newcomer with nothing set up runs the wizard. Instead of a menu of options they
cannot yet use, the wizard detects the empty state and walks them through the setup
journey one step at a time — **register/choose a host → ensure the container image
is available → supply the required credentials/configuration → start a container →
attach to it** — always presenting the single recommended next action first, with a
short explanation of *why this step, now*. Completing a step advances the wizard to
the next recommendation automatically, until the operator lands in a running,
attachable session.

**Why this priority**: This is the whole point of the request — turning a confusing
flat menu into a path a first-time user can follow to a working environment without
external documentation. On its own it delivers the core value.

**Independent Test**: On a machine with no host registered, no image built, and no
container, run the wizard and follow only its recommended next steps; verify it
leads to a running, attachable container, and that at every step it named one
recommended action and explained why.

**Acceptance Scenarios**:

1. **Given** no host is registered/selectable, **When** the wizard starts, **Then**
   its recommended next step is to set up a host, with a reason ("no host is
   configured yet — a host is where containers run"), and setup steps that require a
   host are not offered as if they were ready.
2. **Given** a host is available but the container image is not yet built there,
   **When** the wizard advances, **Then** it recommends building/preparing the image
   and explains why it is needed before a container can start.
3. **Given** host and image are ready but the required credentials/configuration are
   missing, **When** the wizard advances, **Then** it recommends supplying them and
   explains what they are for, before offering to start a container.
4. **Given** all prerequisites are satisfied and no container exists, **When** the
   wizard advances, **Then** it recommends starting a container.
5. **Given** a container is running, **When** the wizard advances, **Then** it
   recommends attaching, and following that recommendation lands the operator in the
   session.

---

### User Story 2 - Adapts to a healthy, in-use environment (Priority: P2)

An experienced operator who already has one or more containers running opens the
wizard. It recognizes the healthy state and leads with the **day-to-day actions that
matter now** — attach to a running container, view its logs, stop/dispose one —
rather than walking them back through setup steps that are already done. The wizard
reflects where the operator actually is.

**Why this priority**: Keeps the guide useful after first-run setup, so the operator
does not outgrow it. Builds directly on US1's state detection.

**Independent Test**: With at least one running container, open the wizard and verify
it leads with attach/logs/manage actions for the existing container(s) and does not
present first-time setup as the recommended next step.

**Acceptance Scenarios**:

1. **Given** one or more running containers, **When** the wizard starts, **Then** the
   recommended next step is a day-to-day action (e.g. attach), not a setup step.
2. **Given** multiple running containers, **When** the operator picks a day-to-day
   action, **Then** the wizard helps them choose which container it applies to.

---

### User Story 3 - Detects and guides out of a broken/partial state (Priority: P2)

Something is wrong: the container runtime is unreachable, a container has exited or
is crash-looping, a required credential went missing, or volumes were left orphaned.
The wizard **names the specific problem** and leads with the corrective next step and
why it will help — instead of a generic menu that hides the fault.

**Why this priority**: The flat menu is worst exactly when something is broken, since
the operator cannot tell a healthy option from a doomed one. Detecting and explaining
the fault is high value, and reuses US1's state model.

**Independent Test**: Simulate each broken state (unreachable runtime, exited
container, missing credential, orphaned volume) and verify the wizard identifies it
and recommends a corrective step with a reason, rather than offering unrelated
actions as normal.

**Acceptance Scenarios**:

1. **Given** the container runtime is unreachable, **When** the wizard starts,
   **Then** it reports that clearly and recommends fixing connectivity before any
   container action, rather than offering start/attach as if they would work.
2. **Given** a container has exited or is crash-looping, **When** the wizard runs,
   **Then** it surfaces that state and recommends the relevant corrective step (view
   logs, recreate, or remove) with an explanation.
3. **Given** orphaned volumes exist, **When** the wizard runs, **Then** it can
   recommend cleaning them up and explains what they are.

---

### User Story 4 - Always explains, never traps (Priority: P3)

At every step the wizard shows a compact summary of the current state, marks its
**recommended** next action distinctly, and still lets the operator choose any other
action that is valid right now (an escape hatch — the recommendation is guidance, not
a cage). For whichever action the operator takes, the wizard shows the **equivalent
non-interactive command**, so the operator gradually learns to drive the tool
directly.

**Why this priority**: Directly answers "it is not clear what to do when and why" —
the state summary plus the reasoned recommendation plus the CLI equivalent make the
wizard teach rather than merely execute. Enhances all prior stories.

**Independent Test**: At any wizard step, verify the state summary is shown, the
recommended action is visually distinct from the alternatives, a valid non-recommended
action can still be chosen, and the equivalent command is displayed for the chosen
action.

**Acceptance Scenarios**:

1. **Given** any wizard step, **When** it is presented, **Then** a current-state
   summary and a clearly-marked single recommendation are shown together.
2. **Given** the operator prefers a different valid action, **When** they select it,
   **Then** the wizard performs it (subject to confirmation for destructive actions)
   instead of forcing the recommendation.
3. **Given** the operator takes any action, **When** it runs, **Then** the wizard
   shows the equivalent non-interactive command for it.

---

### Edge Cases

- **No interactive terminal**: when the wizard cannot run interactively, it must not
  hang or present an unusable prompt; it explains that guided mode needs an
  interactive terminal and points to the non-interactive commands.
- **State changes mid-session**: a container the operator started (or that died) since
  the wizard last looked must be reflected on the next step, so the recommendation is
  never based on stale state.
- **Ambiguous "which one"**: when a recommended action could apply to several
  containers/hosts, the wizard must help the operator pick, never guess silently.
- **A step fails**: if a recommended action fails (e.g. the build errors, the start
  cannot bind), the wizard reports the failure clearly and re-evaluates, rather than
  blindly advancing as if it had succeeded.
- **Partially-complete prerequisites**: e.g. a host exists but is unreachable, or an
  image exists but is stale — the wizard distinguishes "absent" from "present but not
  usable" and recommends accordingly.
- **Operator abandons a step**: cancelling a recommended action returns to the guided
  state (re-evaluated), never to a dead end or a crash.
- **Nothing left to do**: when the environment is fully set up and healthy with a
  running session available, the wizard's recommendation is the obvious daily action
  (attach), and quitting is always an available choice.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The wizard MUST determine the operator's position in the setup journey
  by inspecting the current environment state across its stages: whether the container
  runtime is reachable, whether a host is registered/selectable, whether the container
  image is available on the target, whether the required credentials/configuration are
  present, and whether containers exist and their health/running state.
- **FR-002**: The wizard MUST compute and present a **single recommended next action**
  appropriate to the detected state, distinctly marked as the recommendation.
- **FR-003**: Each recommendation MUST include a short, plain-language **reason** ("why
  this step, now") that a non-expert can act on.
- **FR-004**: The wizard MUST NOT present an action whose prerequisites are unmet as
  though it were ready; such actions are either withheld until their prerequisites are
  satisfied, or shown clearly marked with the missing prerequisite.
- **FR-005**: After each action, the wizard MUST re-evaluate the state and advance its
  recommendation, so the operator can proceed step-by-step from an empty machine to a
  running, attachable container by following recommendations alone.
- **FR-006**: When the environment is fully set up and a container is running, the
  wizard MUST recommend the appropriate day-to-day action (e.g. attach) rather than a
  setup step.
- **FR-007**: The wizard MUST detect and clearly name broken/partial states (runtime
  unreachable, container exited/crash-looping, missing credential, orphaned volumes)
  and recommend the corrective next step with a reason.
- **FR-008**: The wizard MUST let the operator choose any action that is valid in the
  current state instead of the recommendation (an escape hatch); the recommendation is
  guidance, not a forced path.
- **FR-009**: The wizard MUST show a compact **current-state summary** alongside the
  recommendation on each step.
- **FR-010**: When the operator takes an action, the wizard MUST show the **equivalent
  non-interactive command** for it, so the operator can learn to run it directly.
- **FR-011**: The wizard MUST confirm before any destructive or hard-to-reverse action
  (e.g. removing a container, deleting volumes), consistent with the tool's existing
  confirmation behavior.
- **FR-012**: When a recommended action fails, the wizard MUST report the failure
  clearly and re-evaluate state rather than advancing as if it succeeded.
- **FR-013**: When it cannot run interactively (no interactive terminal), the wizard
  MUST decline gracefully with a clear message pointing to the non-interactive
  commands, never hang or crash.
- **FR-014**: When a recommended action could apply to more than one container or host,
  the wizard MUST prompt the operator to choose which, never act on an unintended one.
- **FR-015**: The wizard MUST allow the operator to quit at any step, and cancelling an
  in-progress recommended action MUST return to the (re-evaluated) guided state, not a
  dead end.
- **FR-016**: The set of setup stages the wizard recognizes and the order it walks them
  MUST match the tool's actual prerequisite chain, so following the wizard never leaves
  a required step skipped.

### Key Entities *(include if data involved)*

- **Setup stage**: a distinct milestone on the path to a working environment (runtime
  reachable, host available, image available, credentials/config present, container
  created, container running/attachable), each with a notion of *satisfied /
  unsatisfied / present-but-unusable*.
- **Environment state snapshot**: the wizard's assessment, at a moment, of every setup
  stage plus the inventory of hosts and containers with their health — the input from
  which the recommendation is derived.
- **Recommended action**: the single best next step for the current snapshot, carrying
  its rationale, its target (which host/container, if applicable), whether it is
  destructive, and its equivalent non-interactive command.
- **Action outcome**: the result of performing an action (success/failure + message),
  which triggers re-evaluation and the next recommendation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time operator, starting from a machine with no host, no image,
  and no container, can reach a running and attachable container by following only the
  wizard's recommended next steps — without consulting external documentation or
  guessing from a flat list.
- **SC-002**: At every step, the wizard presents exactly **one** clearly-marked
  recommended action together with a reason for it.
- **SC-003**: The wizard never recommends, or presents as ready, an action whose
  prerequisites are unmet (0 occurrences across the setup journey and the broken-state
  scenarios).
- **SC-004**: For each defined broken/partial state (runtime unreachable, container
  exited/crash-looping, missing credential, orphaned volumes), the wizard identifies
  the specific problem and recommends a corrective step — verified for every case.
- **SC-005**: A first-time operator reaches their first attached session in
  **noticeably fewer decisions** than the flat menu required — no step where the
  operator must know, unaided, which of several options applies.
- **SC-006**: For any action the operator takes through the wizard, the equivalent
  non-interactive command is shown, so a returning operator can reproduce the same
  outcome without the wizard.
- **SC-007**: In every state, the operator can still reach any action that is valid in
  that state (the recommendation never hides a legitimate choice), and can always quit.

## Assumptions

- **Guide, don't silently automate**: the wizard *recommends and leads* each step and
  the operator triggers it (with confirmation for destructive steps); it does not
  perform multi-step setup silently without the operator's go-ahead. This matches the
  request's wording ("direct the user to set up host", "guide the user to do that").
- **Reuse existing capabilities**: the wizard orchestrates the tool's existing
  operations (host setup/selection, image build, container start/attach/logs/stop,
  volume cleanup) — it guides *when and why* to run them; it does not introduce new
  underlying operations. Provisioning a brand-new remote server, where offered, is
  delegated to the tool's existing host-setup path.
- **Local-first default**: on a machine with a working local container runtime and no
  explicitly registered host, the implicit local target counts as an available host,
  so the guided path does not force remote-host registration before a first local
  container.
- **Single operator**: the wizard serves one operator on their own machine
  (consistent with the tool's single-operator assumption); no multi-user or
  concurrent-wizard coordination is in scope.
- **The recommendation is advisory**: it optimizes for the common path to a working
  environment; the operator remains in control and can diverge at any step.
- **Non-interactive contexts are out of scope for guidance**: guided mode targets an
  interactive terminal; scripted/automated use continues through the explicit
  non-interactive commands, which this feature does not change.
