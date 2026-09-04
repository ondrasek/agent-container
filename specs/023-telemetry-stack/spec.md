# Feature Specification: Telemetry stack container

**Feature Branch**: `023-telemetry-stack`

**Created**: 2026-09-04

**Status**: Draft

**Input**: User description: "A third kind of container managed by the tool, besides agent containers and control planes: a TELEMETRY STACK container. Addressed through a new `telemetry stack` subgroup — `up`, `ls`, `url`, `dashboards`, `remove` — rather than a role on `up`, because `up`'s surface (agent, task, repo, env-file, egress, credentials, tmux) is meaningless for it. Runs a single all-in-one observability image (grafana/otel-lgtm by default, named at the surface and overridable): OTLP ingest on 4317/4318, Grafana UI on 3000, with Loki, Prometheus and Tempo behind it. `up` publishes the ports, waits until the OTLP receiver actually accepts a record rather than until the container is merely running, and provisions the tool's own dashboards over the Grafana API. `url` reports how to reach it, including the exact otlp_endpoint value to put in settings.yaml so agent containers export into it, and the tunnel command when the UI is bound to loopback. `dashboards` re-provisions without redeploying. Like every other container this tool creates it must be recorded in the inventory, reachable by `panic`, named and port-allocated so several can run on one host without collision, and deployable to a remote host over the same compose-on-the-target-host mechanism. It holds no credentials and runs no agent, so it needs neither credential delivery nor sshd; its exposure decision (loopback versus a routable address) is the security question that replaces them, because an unauthenticated Grafana and an open OTLP ingest must not be published by accident."

## Why this exists

Feature 017 gave every environment somewhere to *send* telemetry. It never gave the operator
somewhere to send it *to*. Declaring `otlp_endpoint` is one line; standing up something that answers
on it is an afternoon of reading vendor documentation, and the operator who wants to see what an
agent did is not the operator who wants to become an observability engineer that day.

Worse, the gap is silent by design. Export is **fail-open** (017): an endpoint that does not exist
produces runs that pass with no telemetry, which reads as *"the agent emitted nothing"* rather than
*"nobody is listening"*. The tool already refuses to let absence look like a decision everywhere
else; here it hands the operator a setting whose most likely outcome is a quiet nothing.

A third kind of container closes that: the tool that asks you to declare an endpoint can also give
you one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stand up a place for telemetry to land (Priority: P1)

An operator with environments already exporting — or about to — runs one command and gets a
running collector with a UI, on the host of their choosing. The command tells them the exact
`otlp_endpoint` line to paste into `settings.yaml`, because knowing the stack is up is not the same
as knowing what to point at it.

**Why this priority**: Without this the feature does not exist. Everything else refines it.

**Independent Test**: Run `telemetry stack up` on a host with no stack; assert an OTLP record is
accepted afterwards and that the printed endpoint is the one that accepted it.

**Acceptance Scenarios**:

1. **Given** a host with no telemetry stack, **When** the operator runs `telemetry stack up obs`,
   **Then** a stack container is running and the OTLP ingest accepts a record.
2. **Given** a stack that has just come up, **When** the command finishes, **Then** it prints an
   `otlp_endpoint` value that, placed in `settings.yaml`, causes an environment's records to arrive.
3. **Given** the stack image is not present on the host, **When** the operator runs `up`, **Then**
   the image is pulled and the operator is told that a pull is happening, not left at a blank prompt.
4. **Given** the container starts but the ingest never becomes ready, **When** the readiness budget
   expires, **Then** the command fails and says the ingest never accepted a record — not that the
   container failed to start, which would be false.

---

### User Story 2 - See what the agents did, without building dashboards (Priority: P1)

The operator opens the UI and finds views already built for *this tool's* data: which environments
are running, what a given run did, and the machine state underneath it — correlated by `run_id`.

**Why this priority**: A collector with no views is a database. The reason to run this rather than
any generic stack is that it knows the shape of the tool's telemetry.

**Independent Test**: After `up`, query the UI's API for the dashboards and assert each one's
queries return data for a run that exists.

**Acceptance Scenarios**:

1. **Given** a stack that has just come up, **When** the operator opens the UI, **Then** the tool's
   dashboards are present without any import step.
2. **Given** dashboards were edited or deleted by hand, **When** the operator runs
   `telemetry stack dashboards obs`, **Then** they are restored without touching the running stack
   or losing the data already in it.
3. **Given** a stack that has been collecting from several environments, **When** the operator opens
   the run view and selects a run, **Then** that run's agent activity and its container's resource
   usage appear together.

---

### User Story 3 - Know how to reach it, and who else can (Priority: P1)

Before anything is published, the operator is told what the exposure decision means. A stack bound
to a routable address is an unauthenticated UI and an open ingest on the network.

**Why this priority**: This replaces the credential and sshd questions the other two container kinds
answer. Getting it wrong is not a broken feature — it is an exposed one, and the failure is silent.

**Independent Test**: Deploy with the default exposure and assert from off-host that neither the UI
nor the ingest answers; deploy with exposure explicitly widened and assert both do, and that the
command said so.

**Acceptance Scenarios**:

1. **Given** no exposure is declared, **When** the stack comes up, **Then** it is reachable from the
   host and from containers on it, and NOT from another machine.
2. **Given** the operator widens exposure, **When** the stack comes up, **Then** the command states
   plainly that the UI is unauthenticated and the ingest accepts from anyone who can reach it.
3. **Given** a running stack, **When** the operator runs `telemetry stack url obs`, **Then** they get
   the UI address, the `otlp_endpoint` value, and — when the UI is bound to loopback on a remote
   host — the command that tunnels to it.

---

### User Story 4 - Run several, and get rid of them (Priority: P2)

Stacks are cheap and disposable. An operator runs one per project, or one on each host, lists what
exists, and removes them without leaving anything behind.

**Why this priority**: Multi-instance and clean teardown are what make it a managed container kind
rather than a documented `docker run`.

**Independent Test**: Bring up two stacks on one host, assert both are healthy and distinguishable,
then remove one and assert the other is untouched.

**Acceptance Scenarios**:

1. **Given** a stack already running on a host, **When** the operator brings up a second with a
   different name, **Then** both run without a port or volume collision.
2. **Given** two stacks, **When** the operator lists them, **Then** each is shown with its host,
   address and whether its ingest is answering.
3. **Given** a running stack, **When** it is removed, **Then** the container is gone and its
   collected data is retained unless the operator asked to discard it.
4. **Given** a removed stack, **When** the operator lists stacks, **Then** it is absent and the
   inventory records what became of it.

---

### User Story 5 - It is a container this tool created (Priority: P2)

A telemetry stack obeys the same fleet-wide rules as everything else the tool creates: it is in the
inventory, and the kill switch stops it.

**Why this priority**: A container kind the kill switch does not know about is a hole in a safety
property the tool already promises. It is P2 only because it is invisible until something goes
wrong — which is exactly when it must not be missing.

**Independent Test**: Create a stack, run the kill switch, assert the stack stopped and the
inventory says so.

**Acceptance Scenarios**:

1. **Given** a running stack, **When** the operator triggers the kill switch, **Then** the stack is
   stopped along with every other container the tool created.
2. **Given** a stack was created, **When** the inventory is read, **Then** the stack appears as a
   thing this tool made, with its kind distinguishable from an agent environment.
3. **Given** the kill switch cannot reach the stack's host, **When** it reports, **Then** the stack's
   fate is `undetermined` rather than assumed stopped.

---

### Edge Cases

- **The ingest port is already taken on the host.** Refuse with the conflict named, rather than
  starting a container that cannot bind and reporting success.
- **A stack is asked for on a host that already has one under that name.** Treat as already-present
  and report it, rather than deploying a second copy over the first.
- **The UI answers but dashboard provisioning fails.** The stack is still useful; report which
  dashboards failed and keep the stack, rather than tearing down a working collector over its views.
- **`url` is asked about a stack that is not running.** Report it as not running rather than printing
  an address that answers nothing.
- **Removal while environments are still exporting to it.** Permitted, and the consequence stated:
  those exports begin failing open, so their telemetry stops silently.
- **The host cannot pull the image** (no route, or an egress policy denies the registry). Fail with
  the pull named as the cause.
- **Disk fills under retained data.** Out of scope to manage, but retention must be a named default
  rather than an unbounded accident.

## Requirements *(mandatory)*

### Functional Requirements

**The kind**

- **FR-001**: The tool MUST manage a third kind of container, distinct from agent environments and
  control planes, whose purpose is to receive and display telemetry.
- **FR-002**: A telemetry stack MUST be addressed through its own command group, and MUST NOT be
  created through the command that creates agent environments.
- **FR-003**: A telemetry stack MUST be identifiable as such wherever the tool lists or records
  containers it created, without inspecting its image.
- **FR-004**: A telemetry stack MUST NOT be given credentials, and MUST NOT be reachable by the
  credential-delivery path used for agent environments.

**Bringing one up**

- **FR-005**: The tool MUST create a telemetry stack on any host it can deploy to, local or remote,
  using the same deployment mechanism as its other containers.
- **FR-006**: `up` MUST report success only once the OTLP ingest has ACCEPTED a record — container
  liveness is not readiness, and reporting otherwise sends the operator to configure an endpoint
  that will drop what it is sent.
- **FR-007**: `up` MUST be idempotent: re-running against an existing stack of the same name MUST
  report the existing one rather than creating a second.
- **FR-008**: The image MUST be a named default at the surface and MUST be overridable, so an
  operator is never blocked by the tool's choice of stack.
- **FR-009**: Several stacks MUST be able to run on one host simultaneously without colliding on
  name, published port or stored data.
- **FR-010**: When a required port is unavailable, the tool MUST refuse and name the conflict.

**Reaching one**

- **FR-011**: The tool MUST report, for a running stack, the UI address and the exact endpoint value
  an operator puts in configuration to export into it.
- **FR-012**: When the UI is not reachable from the operator's machine, the tool MUST provide the
  command that makes it reachable.
- **FR-013**: The reported endpoint MUST be the address usable BY AN AGENT CONTAINER, which is not
  necessarily the address usable by the operator — the two differ on every runtime where containers
  do not share the operator's loopback.

**Views**

- **FR-014**: `up` MUST install the tool's own dashboards, so a fresh stack answers questions about
  agent activity without an import step.
- **FR-015**: Dashboards MUST be re-installable independently of deployment, without disturbing the
  running stack or discarding collected data.
- **FR-016**: Dashboard installation failure MUST NOT fail the deployment; it MUST be reported with
  the failing dashboards named.
- **FR-017**: Dashboards MUST present agent activity correlated with the container resource usage
  recorded during the same run.

**Exposure**

- **FR-018**: The default exposure MUST make the stack reachable from its host and from containers
  on that host, and NOT from other machines.
- **FR-019**: Widening exposure MUST be an explicit operator action, and the tool MUST state, at that
  moment, that the UI is unauthenticated and the ingest accepts from anyone who can reach it.
- **FR-020**: The tool MUST NOT publish the UI or the ingest on a routable address as a side effect
  of any other choice.

**Lifecycle**

- **FR-021**: The tool MUST list telemetry stacks with their host, address, and whether the ingest is
  currently answering.
- **FR-022**: Removal MUST stop and delete the container, and MUST retain collected data unless the
  operator asks for it to be discarded.
- **FR-023**: Every telemetry stack the tool creates MUST be recorded in the inventory, including
  what became of it.
- **FR-024**: The kill switch MUST stop telemetry stacks along with every other container the tool
  created; a stack on an unreachable host MUST be reported as undetermined rather than stopped.
- **FR-025**: Retention of collected data MUST have a named default rather than being unbounded by
  omission.

### Key Entities

- **Telemetry stack**: a container the tool created whose purpose is receiving and displaying
  telemetry. Has a name unique per host, a host, an ingest address, a UI address, an exposure
  setting, and a lifecycle state.
- **Stack endpoint**: the address agent containers export to. Derived from the stack and the
  runtime's networking, and NOT always equal to the address the operator uses.
- **Dashboard set**: the views the tool installs into a stack, versioned with the tool rather than
  with the stack, so re-installing brings a stack up to the tool's current expectations.
- **Inventory record**: the durable note that this tool created this stack, of this kind, on this
  host, and what became of it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with no observability backend can go from nothing to telemetry visible in
  a UI with a single command plus one configuration line, in under five minutes on a first run
  including image download.
- **SC-002**: A stack reported as up accepts a telemetry record 100% of the time, measured by
  sending one immediately after the command returns.
- **SC-003**: The endpoint value the tool prints works verbatim: an environment configured with it,
  and no other change, produces records visible in the stack.
- **SC-004**: A freshly created stack answers "what did this run do" for an existing run without the
  operator writing a query.
- **SC-005**: With default exposure, neither the UI nor the ingest answers from another machine;
  with exposure widened, both do, and the widening was stated at the time.
- **SC-006**: Two stacks run on one host concurrently, and removing one leaves the other serving.
- **SC-007**: After the kill switch runs, no telemetry stack the tool created is left running on any
  reachable host, and any unreachable host's stack is reported as undetermined.
- **SC-008**: Every stack ever created appears in the inventory with its kind and outcome.

## Assumptions

- **The stack is a single image.** An all-in-one distribution is assumed rather than a composed set
  of services; this keeps the tool's job to one container's lifecycle. An operator needing a
  production-grade split deployment is expected to run one and point `otlp_endpoint` at it, which
  FR-008 keeps possible.
- **The stack is for looking at, not for keeping.** It is a development and operations aid with a
  bounded local store, not a system of record. Long-term retention, backup, high availability, and
  authentication of the UI are out of scope.
- **The UI ships unauthenticated.** This is why exposure is the security question of the feature
  (FR-018 to FR-020). The tool does not attempt to add authentication to a third-party UI.
- **Dashboards target the tool's own telemetry shape.** They assume the correlation identifier and
  resource attributes Feature 017 emits. Signals from emitters that do not carry them still arrive
  and are queryable; they are simply not what these views are built for.
- **The tool does not become an observability dependency.** It continues to export by speaking the
  protocol directly (017). Managing a stack is orchestration of a container, and introduces no
  backend library into the tool.
- **Existing host, inventory and deployment machinery is reused.** No new way to reach a host, record
  a creation, or generate a deployment is introduced by this feature.
