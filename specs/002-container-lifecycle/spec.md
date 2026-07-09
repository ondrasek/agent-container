# Feature Specification: Container Lifecycle Engine (deploy images to a configured host via compose, manage their lifecycle)

**Feature Branch**: `002-container-lifecycle`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Take an existing configured host and deploy a runtime image/images to create running containers using compose, and manage their lifecycle."

## Context & Boundary

This feature is the **container-lifecycle engine** that runs on top of a host already configured by Feature 001 (Multi-Host Deployment). Feature 001 answers *where* containers run (named hosts, drivers, provisioners) and establishes that deployments are expressed as generated compose projects. **This feature owns the verbs that act on a configured host**: turn image(s) into running container(s), then observe, pause, redeploy, dispose, and wipe them. It **inherits** the compose-generation and identity requirements from 001 and does not restate host configuration or provisioning.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy container(s) to a configured host and reach them (Priority: P1)

Given a host that is already configured and reachable, the operator deploys an agent container to it. The tool generates an isolated declarative deployment for that container, builds the runtime image on the host, starts the container, and reports how to attach. Several distinctly-named containers can be deployed to the same host and run as fully independent units.

**Why this priority**: This is the core value of the feature — without "turn a configured host into running agents," nothing else (observe, redeploy, tear down) has a subject. It is the minimum viable slice: one command produces a reachable running agent on a chosen host.

**Independent Test**: Against a pre-configured reachable host, deploy a container by name; confirm the image builds on the host, the container runs as its own isolated deployment, and the reported attach address/port yields an interactive session. Deploy a second, differently-named container to the same host and confirm both run independently.

**Acceptance Scenarios**:

1. **Given** a configured, reachable host, **When** the operator deploys container `alpha`, **Then** an isolated deployment named for `alpha` is generated, its image is built **on the host**, the container starts, and the attach address + port are reported.
2. **Given** container `alpha` is running on host `H`, **When** the operator deploys container `beta` to the same host, **Then** `beta` runs as a separate, independent deployment and `alpha` is unaffected.
3. **Given** a container is running, **When** the operator attaches using the reported address/port, **Then** an interactive SSH+tmux session to the agent is established (attach flow unchanged from Feature 001).
4. **Given** container `alpha` is already deployed on `H`, **When** the operator deploys `alpha` to `H` again with unchanged inputs, **Then** the operation is an idempotent no-op (or reconciles only what changed) rather than creating a duplicate.

---

### User Story 2 - Control a running container across deliberate persistence levels (Priority: P1)

The operator moves a container through its lifecycle at three deliberate levels of persistence: **pause/reclaim** (stop then start, container and volumes intact), **dispose** (remove the container but keep its persistent configuration volumes, so recreating it restores prior state), and **wipe** (remove the container *and* its persistent volumes/image). Redeploying a container after its image changed applies the new image without touching its persistent volumes.

**Why this priority**: Lifecycle control is the other half of the core value and directly encodes the project's ephemerality stance — disposing a container must be a non-event because durable state was externalized, while wiping must be an explicit, guarded act.

**Independent Test**: Deploy a container; stop it and confirm it can be started again unchanged; dispose it and confirm recreating by the same name restores its prior configuration from persisted volumes; change the image and redeploy and confirm the new image is running with volumes intact; wipe it and confirm its persistent volumes are gone only after explicit confirmation.

**Acceptance Scenarios**:

1. **Given** a running container, **When** the operator stops it, **Then** the container is halted but retained, and a subsequent start resumes it without recreation.
2. **Given** a running container, **When** the operator disposes it, **Then** the container is removed but its persistent configuration volumes remain, so a later recreation by the same name restores prior configuration.
3. **Given** a container whose runtime image has been rebuilt, **When** the operator redeploys it, **Then** the new image is applied and the container recreated while its persistent volumes are preserved.
4. **Given** a container with persistent volumes, **When** the operator wipes it, **Then** the operation requires explicit confirmation, and only upon confirmation are the container, its persistent volumes, and its locally-built image removed.

---

### User Story 3 - See the true state and logs by querying the host (Priority: P2)

The operator lists and inspects what is actually running, and reads container logs. State is read **live from the host**, reconciled against what the tool expects, so it stays truthful even after a host reboot, a container crash, or an out-of-band change. The tool never presents a stale local record as truth, and recomputes each container's identity from its name rather than trusting a stored value.

**Why this priority**: Trustworthy observability is essential once containers live on remote hosts, but it depends on P1/P2 existing to have something to observe. It prevents the dangerous failure mode of acting on a stale local picture.

**Independent Test**: Deploy a container; list state and confirm it reflects the host. Then change the host out of band (e.g., stop the container directly, or reboot the host) and confirm the tool's next status reflects the *actual* host state, not the prior local record.

**Acceptance Scenarios**:

1. **Given** containers deployed on a host, **When** the operator lists state, **Then** the list reflects the host's actual running containers, reconciled against expected identities.
2. **Given** a container was stopped or removed out of band on the host, **When** the operator asks for status, **Then** the reported state matches the host's real state, not the tool's previous local record.
3. **Given** a running container, **When** the operator requests logs, **Then** the container's logs are streamed from the host.
4. **Given** any lifecycle command, **When** the tool needs a container's identity (name, ports, volumes, project), **Then** it recomputes that identity from the container name rather than reading a possibly-stale stored value.

---

### User Story 4 - Deploy helper (sidecar) services alongside an agent (Priority: P3)

A single container deployment may include one or more helper services (for example a caching proxy or a local model server) that share the deployment's lifecycle with the agent. Bringing the deployment up, down, or wiping it acts on the agent and its helpers together as one unit.

**Why this priority**: Composability is a stated goal but not required to prove the core lifecycle. It is additive: the "multiple images" case where the extra images are helpers within one deployment rather than separate deployments.

**Independent Test**: Deploy a container declared with one helper service; confirm both the agent and the helper start together; stop/dispose the deployment and confirm both are acted on as one unit; confirm the agent can reach the helper.

**Acceptance Scenarios**:

1. **Given** a deployment declaring an agent plus one helper service, **When** it is brought up, **Then** both services start as part of the same deployment and the agent can reach the helper.
2. **Given** such a deployment, **When** it is disposed or wiped, **Then** the agent and its helper are acted on together as one unit (no orphaned helper).

---

### Edge Cases

- **Unreachable / incapable host**: deploying to a host that is unreachable or lacks the required compose-capable runtime fails fast with a clear diagnostic and leaves no partial deployment.
- **Redeploy with no change**: redeploying unchanged inputs is a no-op; only a changed image or parameters cause a recreate.
- **Recreate after dispose**: recreating a disposed container by the same name reuses its persistent volumes, restoring prior configuration (recreation is a non-event).
- **Stale local picture**: after a host reboot, a crash, or out-of-band `docker`/compose action, status reflects the host's real state, not the tool's last local record.
- **Port-release race**: tearing a container down releases its published port before returning, so an immediate recreate of the same name on the same host does not fail on a stale port (inherited from Feature 001).
- **Destructive confirmation**: wiping persistent volumes always requires explicit confirmation.
- **Duplicate deploy**: deploying a name that already runs on the host reconciles the existing deployment rather than creating a duplicate.
- **Concurrent operations**: two lifecycle operations on the same container at once are serialized or safely rejected, never allowed to corrupt state.
- **Crash + restart**: a crashed container is restarted automatically; the operator reconnects to a freshly restarted agent session (prior session not resumed), consistent with continuous externalization of durable state.

## Requirements *(mandatory)*

### Functional Requirements

**Deployment**

- **FR-001**: The system MUST deploy a container to an already-configured, reachable host by generating an isolated declarative deployment and starting it, with the runtime image built **on the host** (no image transfer from the operator's machine, no external registry required — inherited from Feature 001).
- **FR-002**: Each deployed container MUST be an **independent unit with isolated lifecycle**, keyed by its deterministic identity, so that any lifecycle action on one container does not affect any other container on the same host.
- **FR-003**: The system MUST support **multiple distinctly-named containers running concurrently on one host** without name, port, or volume collision.
- **FR-004**: A deployment MAY include one or more **helper (sidecar) services** that share the deployment's lifecycle with the agent and are reachable by the agent; lifecycle actions MUST act on the agent and its helpers as a single unit.
- **FR-005**: Deploying a container that already exists on the host MUST **reconcile** the existing deployment (update only what changed) rather than create a duplicate.

**Lifecycle at three persistence levels**

- **FR-006**: The system MUST provide **pause/reclaim** — stop a running container while retaining it and its volumes, and start it again without recreation.
- **FR-007**: The system MUST provide **dispose** — remove a container while **keeping its persistent configuration volumes**, so a later recreation by the same name restores prior configuration (recreation is a non-event).
- **FR-008**: The system MUST provide **redeploy** — apply a changed runtime image to an existing container, recreating it while **preserving its persistent volumes**.
- **FR-009**: The system MUST provide **wipe** — remove a container together with its persistent volumes and its locally-built image; wipe MUST require **explicit confirmation** because it destroys durable state.
- **FR-010**: A redeploy MUST pick up a rebuilt image; a deploy or redeploy with unchanged inputs MUST be an **idempotent no-op** (or reconcile only the changed parts).

**Observability & source of truth**

- **FR-011**: State queries (list/status) MUST read the **host's actual running state live** and reconcile it against expected identities; the system MUST NOT present a local record as authoritative state.
- **FR-012**: Whenever a container's identity (name, published port(s), volume names, deployment/project key) is needed, the system MUST **recompute it from the container name** rather than read a stored value that could be stale (Constitution IV — Deterministic Identity).
- **FR-013**: The system MUST stream a running container's **logs** from the host on request.
- **FR-014**: The generated deployment artifact MUST be a **derived, regenerable output** — regenerated from parameters on each deploy — yet **persisted** so subsequent lifecycle operations are reliable, and it MUST remain human-readable and inspectable (Constitution V — Durable Spec, Disposable Code).

**Safety & robustness**

- **FR-015**: Deploying to an unreachable or non-compose-capable host MUST **fail fast** with a clear diagnostic and MUST NOT leave a partial deployment.
- **FR-016**: Tearing a container down MUST **release its published port before returning**, so an immediate recreate of the same name on the same host does not fail on a stale port (inherited from Feature 001).
- **FR-017**: Two lifecycle operations targeting the same container concurrently MUST be **serialized or safely rejected**, never allowed to corrupt state.
- **FR-018**: Every failure mode MUST produce a clear, actionable diagnostic rather than a partial or hung state.
- **FR-019**: Documentation (README, CLAUDE.md, and this spec) MUST be updated in the same change as any behavior, scope, identity-contract, or security-posture change introduced by this feature (Constitution — Development Workflow).

### Key Entities *(include if data involved)*

- **Deployment (container instance)**: the unit this feature manages — an agent container (plus optional helpers) bound to exactly one host, identified by a name. Owns a generated, regenerable deployment artifact, a set of persistent volumes, published port(s), and a lifecycle state. Isolated from every other deployment.
- **Service**: a process within a deployment — the agent, or a helper/sidecar. Has an image source (built on the host, or a referenced image for a helper).
- **Generated deployment artifact**: the derived, regenerable declarative description of a deployment (services, volumes, ports, injected identity), persisted in the tool's state so lifecycle operations are reliable, never treated as the authoritative record of *running* state.
- **Lifecycle state**: one of running / stopped / disposed / absent for a deployment; the **host is the authoritative source**, queried live and reconciled against expected identity.
- **Host** *(from Feature 001, referenced not redefined)*: the already-configured, reachable target the deployment runs on.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a configured, reachable host, the operator deploys and reaches a running container with a single deploy command plus a single attach command, with the image built on the host.
- **SC-002**: Multiple distinctly-named containers run on one host simultaneously; a lifecycle action on one leaves every other container on that host running in 100% of cases.
- **SC-003**: Disposing a container and then recreating it by the same name restores its prior configuration with zero manual reconfiguration (persistent volumes retained).
- **SC-004**: After a host reboot, container crash, or out-of-band change, the tool's next status reflects the host's actual state, not a prior local record, in 100% of cases.
- **SC-005**: Wiping persistent volumes never occurs without explicit confirmation — zero accidental volume deletions.
- **SC-006**: Redeploying a container after its image changed results in the new image running with its persistent volumes unchanged.
- **SC-007**: Every generated deployment artifact is human-readable and fully describes the deployment's services, volumes, and ports, so the operator can inspect exactly what will run before or after it runs.
- **SC-008**: An immediate recreate of a container after tearing it down on the same host succeeds without a stale-port failure.
- **SC-009**: Deploying a name that already runs on the host results in one reconciled deployment, never a duplicate.

## Assumptions

- **Depends on Feature 001**: this feature assumes a host that is already configured, reachable, and compose-capable; it does not configure hosts, register drivers, or provision servers.
- **Live host is the source of truth** *(resolves discussion fork 1)*: the tool's local state files and the generated deployment artifact are **regenerable caches**, not authority; running state is read from the host and identity is recomputed from the container name (Constitution IV). This keeps remote deployments truthful across reboots/crashes/out-of-band changes.
- **Meaning of "multiple images/containers"** *(resolves discussion fork 2)*: in scope are (a) **helper/sidecar services within a single deployment** and (b) **multiple distinctly-named deployments on one host**. **Out of scope**: managed pools of multiple *identical* instances of the same image (which would require instance-suffixed identity — an extension of the Deterministic Identity contract, deferred to future work).
- **Run mechanism and build locality** are inherited from Feature 001: compose is the run mechanism; the agent image is built on the host over its context with no external registry; a helper service may reference a public image.
- **Ephemerality levels**: dispose keeps persistent volumes; only wipe removes them; recreation is deliberately a non-event (Constitution I).
- **Restart semantics**: automatic restart-on-crash is expected and reconnects to a fresh session rather than resuming the prior one (inherited from Feature 001, Constitution I).
- **Scope of "manage lifecycle"**: primary operations are per-container on a single host, plus a host-scoped enumerate/list. Cross-host fleet orchestration and batch "operate on everything everywhere" flows are out of scope for this feature.
- **Single operator**: one operator manages the containers; no multi-tenant controls (Constitution — Platform & Interface Constraints).
- **No new stored secrets**: this feature introduces no new long-lived stored secret; injected identity material continues to follow Feature 001 (secrets/configs, runtime-injected).
