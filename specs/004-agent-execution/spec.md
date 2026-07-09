# Feature Specification: Agent Execution & Session Management (interactive/headless, workspace modes, detach/reattach)

**Feature Branch**: `004-agent-execution`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Managing the agents inside the containers — headless or interactive (in tmux). Having the optional workspace volume mounted from a local filesystem (for local deployments) or a temporary workspace volume that does not outlive the container. Detaching from the container tmux and re/attaching to it (ssh)."

## Context & Boundary

This feature owns **what runs inside the container and how the operator interacts with it**. In the feature ladder: 001 = *where* containers run (hosts), 002 = *lifecycle verbs*, 003 = *credentialing* (what an agent needs to function), 004 (this feature) = *running the agent and the operator's session with it*. **This feature runs the agent** — it chooses interactive vs headless, selects the workspace mode, populates the workspace, and provides detach/reattach — and **depends on** Feature 003 for the git push credential (used by clone-on-start and autonomous push) and the injected configuration. It does not deliver secrets/config (003), manage container lifecycle verbs (002), or configure hosts (001).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run an agent interactively and drive it over SSH+tmux (Priority: P1)

The operator starts a deployment in **interactive** mode: the agent runs in a persistent terminal session inside the container, and the operator attaches over SSH to drive it. The session is long-lived — it keeps running when the operator disconnects. Optionally the operator seeds the session with an initial task at launch.

**Why this priority**: Interactive, human-in-the-loop agent work over SSH+tmux is the canonical use of this system (the constitution names `ssh user@host -t tmux attach` as the canonical attach path). Without it there is no way to actually work with an agent.

**Independent Test**: Start a deployment in interactive mode; attach and confirm an interactive agent session; issue a command; confirm it responds. Seed a second deployment with an initial task and confirm the agent begins it without an attach.

**Acceptance Scenarios**:

1. **Given** a deployment started in interactive mode, **When** the operator attaches, **Then** an interactive agent session inside a persistent terminal is presented.
2. **Given** an interactive deployment, **When** the operator provides an initial task at launch, **Then** the agent begins that task without requiring an attach.
3. **Given** an interactive deployment, **When** no operator is attached, **Then** the session and the agent keep running (the session is not tied to a connection).
4. **Given** an interactive deployment that crashed, **When** it is restarted, **Then** the operator can attach to a freshly started session (the prior session is not resumed), consistent with continuous externalization of work.

---

### User Story 2 - Detach and reattach without interrupting the agent (Priority: P1)

The operator disconnects from an interactive session and the agent keeps working; later — possibly from a different machine — the operator reattaches and finds the session as it was left (still running). Reattach lands deterministically on the same named session.

**Why this priority**: The always-on premise is that an agent runs unattended and the operator drops in and out. Detach/reattach that preserves the running session is the mechanism that makes "always-on" real; it is co-critical with US1.

**Independent Test**: Attach to an interactive deployment, start a long-running action, disconnect; confirm from outside that the agent is still running; reattach (including from a different machine) and confirm the same session is presented with the action still progressing/complete.

**Acceptance Scenarios**:

1. **Given** an attached interactive session, **When** the operator disconnects, **Then** the session and any in-progress agent work continue running inside the container.
2. **Given** a detached but running session, **When** the operator reattaches, **Then** they land on the same named session with its state intact.
3. **Given** a running deployment, **When** the operator reattaches from a different machine, **Then** the session is presented identically (attach is not tied to one client).
4. **Given** a deployment whose session has ended (agent exited), **When** the operator reattaches, **Then** the tool either presents a fresh session or clearly reports that nothing is running — never a silent empty attach.

---

### User Story 3 - Run an agent headless as a disposable job (Priority: P2)

The operator runs an agent **headless**: the agent performs a task non-interactively as the container's workload, runs to completion, and the container exits with the agent's result. A successful job is not resurrected. The operator can either watch the run in the foreground (streaming output until it finishes) or launch it detached and inspect its output and result afterward.

**Why this priority**: Headless batch runs (one task = one disposable container) are the purest expression of ephemerality and enable automation, but interactive work (US1/US2) is the primary mode, so this ranks below it.

**Independent Test**: Launch a headless run in the foreground and confirm output streams and the run ends with a success/failure result. Launch a second headless run detached, confirm control returns immediately, then retrieve its output and final result later.

**Acceptance Scenarios**:

1. **Given** a headless run, **When** the agent completes its task, **Then** the container exits and its result (success/failure) is reported.
2. **Given** a headless run that succeeds, **When** the deployment is observed afterward, **Then** it is not automatically restarted.
3. **Given** a foreground headless launch, **When** the run proceeds, **Then** the operator sees streamed output and control returns when the run finishes.
4. **Given** a detached headless launch, **When** the operator issues it, **Then** control returns immediately and the run's output and final result remain retrievable afterward.
5. **Given** a headless run that fails, **When** it ends, **Then** the failure result is distinguishable from success.

---

### User Story 4 - Choose how the workspace is provided (Priority: P2)

At deploy the operator selects the container's **workspace mode**: **persistent** (survives recreation), **bind** (the operator's local filesystem, local hosts only), or **ephemeral** (scratch that does not outlive the container). For persistent and ephemeral workspaces the container populates the working copy on start (clone-on-start using the injected push credential); a bind workspace is already present on the operator's disk.

**Why this priority**: The workspace mode determines where work lives and how the ephemerality discipline applies; it is essential to real use but independent of interactive/headless choice, so it is its own story.

**Independent Test**: Deploy with each workspace mode. Persistent: write to the workspace, recreate, confirm it persists. Bind on a local host: confirm edits appear on the local filesystem; attempt a bind workspace on a non-local host and confirm it is refused. Ephemeral: confirm the workspace is freshly populated on start and gone after teardown.

**Acceptance Scenarios**:

1. **Given** a persistent workspace, **When** the container is recreated by the same name, **Then** the prior working copy is still present.
2. **Given** a bind workspace on a local host, **When** the agent edits files, **Then** the changes appear on the operator's local filesystem.
3. **Given** a bind workspace requested on a **non-local** host, **When** the deploy is attempted, **Then** it is refused with a clear message (a bind cannot resolve on a remote host).
4. **Given** an ephemeral workspace, **When** the container starts, **Then** the working copy is freshly populated (clone-on-start), and **When** the container is torn down, **Then** the workspace does not survive.
5. **Given** a persistent or ephemeral workspace, **When** the container starts and a source repository is configured, **Then** the working copy is populated by cloning it using the injected push credential.

---

### Edge Cases

- **Reattach to a dead session**: the agent exited — reattach presents a fresh session or clearly reports "nothing running," never a silent blank attach.
- **Bind on remote**: a bind workspace against a non-local host is refused (it would resolve on the remote filesystem), mirroring the injected-material rule from Feature 001.
- **Clone-on-start without a credential**: if clone-on-start is configured but the push credential (Feature 003) is missing, the deploy fails fast rather than starting an agent with an empty workspace.
- **Ephemeral work not externalized**: with an ephemeral workspace, anything not committed-and-pushed is lost on teardown — this is intentional (it forces the discipline), and the mode is documented as such.
- **Headless success vs failure**: a headless run's result distinguishes success from failure, and a successful run is never auto-restarted while a failed one follows the deployment's restart policy.
- **Interactive crash**: a crashed interactive session restarts to a fresh session (prior session not resumed), consistent with Feature 001.
- **Two workspace durability models**: persistent and bind tolerate uncommitted local state; ephemeral does not — the operator is not misled into thinking ephemeral work is safe.
- **Mode/workspace mismatch guidance**: headless pairs naturally with ephemeral and interactive with persistent, but any combination is permitted; unusual combinations are not silently altered.

## Requirements *(mandatory)*

### Functional Requirements

**Execution modes**

- **FR-001**: The system MUST support an **interactive** execution mode in which the agent runs in a persistent terminal session inside the container that the operator attaches to over SSH, and which keeps running while no operator is connected.
- **FR-002**: The system MUST support a **headless** execution mode in which the agent runs the task non-interactively as the container's workload, the container **exits with the agent's result**, and a **successful** run is **not** automatically restarted.
- **FR-003**: Interactive mode MUST optionally accept an **initial task** to seed the agent at launch.
- **FR-004**: Headless mode MUST support **both** a **foreground** launch (stream output, return control on completion) and a **detached** launch (return control immediately, with output and final result retrievable afterward).
- **FR-005**: The two modes MAY differ in restart behavior: an interactive session is kept alive/restarted; a headless success terminates and is not resurrected (a headless failure follows the deployment's restart policy).

**Sessions: detach / reattach**

- **FR-006**: An interactive session MUST be **decoupled from the operator's connection**: disconnecting MUST NOT stop the session or the agent's in-progress work.
- **FR-007**: The system MUST let the operator **reattach** to a running session, landing deterministically on the **same named session**, including from a **different machine**.
- **FR-008**: On reattach when no live session exists, the system MUST either present a **fresh session** or **clearly report** that nothing is running — never a silent empty attach.
- **FR-009**: After a crash-restart, reattach MUST land on a **freshly started session** (the prior session is not resumed), consistent with continuous externalization of work (Constitution I).

**Workspace modes**

- **FR-010**: At deploy the operator MUST be able to select the workspace mode: **persistent** (survives recreation), **bind** (operator's local filesystem), or **ephemeral** (does not outlive the container).
- **FR-011**: A **bind** workspace MUST be **restricted to local hosts** and MUST be **refused with a clear message on a non-local host** (a bind path resolves on the remote filesystem).
- **FR-012**: A **persistent** workspace MUST retain the working copy across container recreation by the same name.
- **FR-013**: An **ephemeral** workspace MUST NOT survive container teardown.
- **FR-014**: For **persistent and ephemeral** workspaces with a configured source repository, the container MUST **populate the working copy on start** (clone-on-start) using the injected push credential (Feature 003); if that credential is missing, the deploy MUST fail fast rather than start with an empty workspace.
- **FR-015**: The system MUST make the **durability difference explicit**: persistent and bind tolerate uncommitted local state, whereas ephemeral loses anything not committed-and-pushed on teardown; the operator MUST NOT be misled that ephemeral work is durable.

**Cross-cutting**

- **FR-016**: Execution mode and workspace mode MUST be **independently selectable**; any combination is permitted and unusual combinations MUST NOT be silently altered (though guidance MAY note the natural pairings).
- **FR-017**: Every failure mode (refused bind, missing credential for clone-on-start, dead-session reattach) MUST produce a **clear, actionable diagnostic** rather than a silent or hung state.
- **FR-018**: Documentation (README, CLAUDE.md, this spec) MUST be updated in the same change as any change to execution modes, session behavior, or workspace semantics (Constitution — Development Workflow).

### Key Entities *(include if data involved)*

- **Execution mode**: how the agent runs — **interactive** (persistent attachable session, kept alive) or **headless** (agent-as-workload, exits with a result, success not resurrected). Determines the container's primary workload and restart behavior.
- **Agent session**: the persistent terminal session an interactive agent runs in; decoupled from the operator's connection, identified by a canonical name, reattachable from anywhere.
- **Headless run**: a non-interactive agent execution with a start, streamed or retrievable output, and a final success/failure result; foreground or detached.
- **Workspace**: the container's working copy of the code, in one of three modes — **persistent** (host storage, survives recreation), **bind** (operator's local filesystem, local hosts only), **ephemeral** (does not outlive the container).
- **Clone-on-start**: the start-time population of a persistent/ephemeral workspace from a configured source repository, using the injected push credential (Feature 003).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The operator can attach to an interactive deployment and issue an agent command, with the session presented within seconds of attaching, in 100% of attempts.
- **SC-002**: After the operator disconnects from an interactive session, the agent's in-progress work continues in 100% of cases (no dependency on the connection).
- **SC-003**: The operator can reattach — including from a different machine — and land on the same running session in 100% of attempts; a dead session never yields a silent empty attach.
- **SC-004**: A headless run reports a success/failure result on completion in 100% of cases, and a successful headless run is auto-restarted in 0% of cases.
- **SC-005**: A headless run can be launched both foreground (output streams, control returns on completion) and detached (control returns immediately, output/result retrievable later) — both paths work.
- **SC-006**: A persistent workspace retains its working copy across recreation in 100% of cases; an ephemeral workspace survives teardown in 0% of cases.
- **SC-007**: A bind workspace is honored on a local host and refused on a non-local host in 100% of cases.
- **SC-008**: For persistent/ephemeral workspaces with a configured repository, the working copy is populated on start in 100% of cases, and a deploy with a missing clone credential fails before starting an empty-workspace agent in 100% of cases.

## Assumptions

- **Two execution modes** *(operator decision)*: exactly interactive and headless. An "attachable-but-auto-exits" hybrid is explicitly **deferred** as a documented future mode; the supervised-run need is met by interactive-with-initial-task.
- **Clone-on-start is in scope** *(operator decision)*: persistent/ephemeral workspaces self-populate from a configured source repository using the injected push credential; population is not left entirely to the operator/agent.
- **Headless supports both launch styles** *(operator decision)*: foreground stream-and-block and detached fire-and-forget are both provided.
- **Detach/reattach rests on the SSH+tmux model from Feature 001**: detach = disconnect (session persists via the in-container terminal multiplexer); reattach = SSH back and attach to a canonical session name. No separate "detach" command is required, and attach works uniformly for local and remote hosts (via the host's reachable address and the container's published port).
- **Depends on Feature 003**: the git push credential and injected configuration come from Feature 003; this feature consumes them (clone-on-start, autonomous push) and does not deliver them.
- **Depends on Features 001/002**: hosts, the compose run mechanism, restart-on-crash semantics, and the `workspace` volume identity come from 001/002; this feature refines the *mode* of the workspace and the *shape* of the workload, not the host or lifecycle machinery.
- **Ephemerality alignment**: automatic restart reconnects to a fresh session rather than resuming a prior one; the ephemeral workspace mode deliberately forbids durable local state, forcing the commit-and-push discipline (Constitution I).
- **Agents in scope**: the three baked agent CLIs (Claude Code, Codex, pi-coding-agent); one primary agent per deployment is assumed, with the operator free to launch additional processes within an interactive session manually.
- **Single operator**: one operator attaches to and drives the agents; no multi-user session sharing is in scope (Constitution — Platform & Interface Constraints).
