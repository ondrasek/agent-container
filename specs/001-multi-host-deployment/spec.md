# Feature Specification: Multi-Host Deployment (named hosts, drivers, provisioners, compose run)

**Feature Branch**: `001-multi-host-deployment`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Materialize the current discussion into a specification." — a CLI that deploys ephemeral agent containers to named targets running locally or remotely (Hetzner today, other IaaS later), where a *host* is a named target backed by a *driver* (local/remote docker context) with optional *provisioning* (allocate a cloud server), the container is run via docker compose (declarative spec, restartable services, all persistence + injected identity expressed in the generated compose file), images are built on the target host over its context, and attach/reconnect works uniformly regardless of where the container runs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy and attach on a named local host (Priority: P1)

The operator registers a **named host** backed by a local container runtime target (a local docker context), then deploys an agent container to it and attaches. This replaces today's implicit "wherever docker points" behaviour with an explicit, named target, and switches the run mechanism to a generated declarative compose project. It is the foundation every other story builds on — remote hosts are the same run path with a provisioning step in front.

**Why this priority**: Without a named-host + compose run path there is nothing to deploy *to* and no uniform lifecycle to extend to remote targets. This slice alone delivers value: a reproducible, inspectable, restart-on-crash local deployment that the operator attaches to over SSH+tmux.

**Independent Test**: Register a local host pointing at an existing local runtime target; `up` an agent container on it; confirm it is running, attach over SSH+tmux, detach, then `down` it — all without touching any remote infrastructure.

**Acceptance Scenarios**:

1. **Given** no hosts are registered, **When** the operator registers a host named `local` bound to an existing local runtime context, **Then** the host appears in the host list with driver `docker` and its context reference.
2. **Given** the `local` host exists, **When** the operator deploys container `alpha` to it, **Then** a declarative compose project is generated and started, the container runs with its seven persistent volumes and its injected SSH identity, and its published SSH port is reported.
3. **Given** container `alpha` is running on `local`, **When** the operator issues attach for `alpha`, **Then** an interactive SSH+tmux session to the running agent is established.
4. **Given** container `alpha` is running, **When** the operator tears it down, **Then** the container is stopped and removed and its published port is released, while its persistent volumes remain for a later recreation.
5. **Given** container `alpha` was deployed, **When** the operator inspects the generated deployment artifact, **Then** it is a human-readable declarative spec listing the service, volumes, and injected identity material.

---

### User Story 2 - Provision a fresh cloud host and deploy to it (Priority: P2)

The operator registers a **cloud host** for a provider (Hetzner) and asks the tool to **allocate a new server**. The tool creates the server, makes it reachable, installs the container runtime, registers it as a remote target, builds the agent image **on that server**, runs the container there, and reports how to attach over the server's public address. Going from nothing to an attachable remote agent is a single host-registration + deploy flow.

**Why this priority**: This is the headline capability — always-on agents on cheap remote infrastructure — but it depends on the P1 run path already existing. It is higher-risk (real infrastructure, real credentials, real billing) so it follows the local slice.

**Independent Test**: With provider credentials available, register a cloud host with "create a new server"; confirm a server is allocated and becomes reachable, the runtime is installed, the host is registered; deploy a container to it, attach over the server's public address, then tear the container down.

**Acceptance Scenarios**:

1. **Given** provider credentials are available at runtime, **When** the operator registers a cloud host requesting a new server (specifying server size/location/SSH key), **Then** a server is allocated, becomes reachable, has the runtime installed, and is registered as a usable remote host.
2. **Given** a registered cloud host, **When** the operator deploys a container to it, **Then** the agent image is built **on the remote server** (no multi-gigabyte image transfer from the operator's machine) and the container starts there.
3. **Given** a container runs on a cloud host, **When** the operator attaches, **Then** the SSH+tmux session is established to the container via the server's reachable public address and the container's published port — using the same attach flow as a local host.
4. **Given** a deploy targets a remote host, **When** the injected SSH identity is applied, **Then** the private host key and public authorized-keys are transferred from the operator's machine to the remote deployment as declarative injected material (not as a local-filesystem bind that would resolve empty on the remote).
5. **Given** provisioning fails after a server was allocated, **When** the failure is detected, **Then** the operator is clearly informed and offered/performed cleanup so no unusable billable server is silently left running.

---

### User Story 3 - Manage the host registry and tear down safely (Priority: P3)

The operator lists, inspects, and removes hosts, and the tool keeps **server lifecycle distinct from container lifecycle**. Removing a container never removes the server under it; deprovisioning a cloud server is an explicit, guarded act that refuses to destroy a server still hosting containers.

**Why this priority**: Safety and manageability of the fleet. It is not needed to prove the deploy path works, but it prevents expensive or destructive mistakes once multiple hosts and containers exist.

**Independent Test**: With two containers on one cloud host, attempt to deprovision that host and confirm it is refused; remove one container and confirm the server and the other container are untouched; then explicitly deprovision and confirm the server is destroyed only after it is empty.

**Acceptance Scenarios**:

1. **Given** several registered hosts, **When** the operator lists hosts, **Then** each host's name, driver, reachability, and (for cloud hosts) provisioning state are shown.
2. **Given** a cloud host with two running containers, **When** the operator attempts to deprovision the server, **Then** the action is refused with an explanation that the server still hosts containers.
3. **Given** a container is torn down, **When** the operation completes, **Then** the underlying server and all other containers on it are unaffected.
4. **Given** an empty cloud host, **When** the operator explicitly deprovisions it, **Then** the server is destroyed and the host entry is removed (or marked deprovisioned).
5. **Given** a host was registered against an *existing* (operator-supplied) server rather than an allocated one, **When** the host is removed, **Then** the tool removes only its own registration and does not destroy infrastructure it did not create.

---

### Edge Cases

- **Unreachable target**: deploying to a host whose runtime target is unreachable fails fast with a clear diagnostic, not a partial/hung deployment.
- **Partial provisioning**: a server is created but runtime installation fails — the operator is told and no orphaned billable server is left silently running.
- **Destroy-under-load guard**: deprovisioning a server that still hosts containers is refused.
- **Per-host port reuse**: the deterministic published port for a name is per-host; the same name may run on two different hosts without collision, and recreating a name on the *same* host must not race its own just-released port.
- **Missing injected material**: if the local SSH identity material referenced by a deploy is absent at deploy time, the deploy fails with a clear message rather than starting an unreachable container.
- **Runtime capability floor**: a target host that lacks the required compose-capable runtime is reported as unusable at registration/first-deploy, not mid-run.
- **Crash + restart**: a crashed container is restarted automatically; the operator reconnects to a **freshly restarted** agent session (prior tmux/session state is intentionally not resumed), with no loss because durable state was already externalized.
- **Same name, two hosts**: identity (name, ports, volumes) is scoped per host so a container name is unambiguous only together with its host.
- **Legacy address book**: previously configured plain SSH attach targets continue to be attachable during a deprecation window as a degenerate "connect to existing" host.

## Requirements *(mandatory)*

### Functional Requirements

**Hosts & drivers**

- **FR-001**: The system MUST let the operator register a **named host** and select a **driver** that determines how the host is built on, run on, and connected to.
- **FR-002**: The system MUST support a **local/remote container-runtime driver** in which build and run execute against a runtime context that may be local or a remote server, using the same run path for both.
- **FR-003**: The system MUST let the operator **list**, **inspect**, and **remove** registered hosts, showing at least each host's name, driver, reachability, and (where applicable) provisioning state.
- **FR-004**: The system MUST allow at least two host kinds to coexist and be selected per deployment: a local-runtime host and a provider-provisioned remote host. A default host MUST be used when the operator does not specify one.
- **FR-005**: The host registry MUST replace the prior static SSH "address book" as the single source of truth for where containers live, while continuing to allow attaching to previously configured plain SSH targets during a deprecation window.

**Provisioning**

- **FR-006**: The system MUST support a **provider provisioner** (Hetzner for the first release) that can **allocate a new server**, make it reachable, install the required container runtime on it, and register it as a usable remote host.
- **FR-007**: Server allocation MUST be **explicit** — the operator distinctly chooses "create a new server" versus "use this existing server"; the tool MUST NOT allocate billable infrastructure implicitly.
- **FR-008**: The system MUST keep **server lifecycle distinct from container lifecycle**: tearing down a container MUST NOT deprovision its server, and deprovisioning a server MUST be a separate explicit action.
- **FR-009**: The system MUST **refuse to deprovision** a server that still hosts one or more containers, with a clear explanation.
- **FR-010**: The system MUST **not destroy infrastructure it did not create**: removing a host that was bound to an operator-supplied existing server removes only the registration.
- **FR-011**: On provisioning failure after a server has been allocated, the system MUST surface the failure and ensure no unusable billable server is left silently running (offer or perform cleanup).
- **FR-012**: Provider credentials MUST be supplied at runtime and MUST NOT be baked into any image nor exposed on a process command line. (Constitution III — Least Exposure.)

**Deployment / run mechanism**

- **FR-013**: The system MUST deploy each container as a **generated declarative deployment artifact** (a compose project) rather than an imperative run invocation, and this artifact MUST be human-readable and inspectable.
- **FR-014**: The generated artifact MUST declare **all persistent state** the container needs — the seven per-container volumes (workspace, agent configs for the three agents, shell environment, tmux, SSH identity) — created on whichever host runs the container.
- **FR-015**: The generated artifact MUST express the **injected SSH identity** (private host key and public authorized-keys) as declarative injected material sourced from the operator's local machine, so it is transferred to a remote host over the runtime context, rather than as a local-filesystem bind that would resolve empty on a remote host. The private host key MUST be treated as secret and the authorized-keys as public. (Constitution III.)
- **FR-016**: The system MUST **build the agent image on the target host** over its runtime context, avoiding transfer of large built images from the operator's machine, and without requiring an external image registry.
- **FR-017**: Deployed containers MUST be configured to **restart automatically on crash**; a restarted container MUST be reconnectable, and it is acceptable and expected that the prior interactive session is not resumed (durable state having been externalized per Constitution I).
- **FR-018**: The same **attach/reconnect flow** MUST work uniformly for local and remote hosts: an SSH+tmux session to the running agent via the host's reachable address and the container's published port. The tool MUST report the reachable address and port needed to attach.

**Identity & isolation**

- **FR-019**: Per-container identity (name, published port(s), volume names, project name) MUST derive deterministically from the container name and MUST NOT collide across multiple containers on a host, nor across hosts. Port determinism is **per host** so the same name may run on different hosts simultaneously. (Constitution IV — Deterministic Identity.)
- **FR-020**: Tearing down a container MUST release its published port and MUST NOT return before the port is actually released, so an immediate recreate of the same name on the same host does not fail on a stale port.
- **FR-021**: The identity derivation MUST have one authoritative definition reused by every consumer (deploy, attach, teardown, shell completions), and MUST remain a stable contract for already-created containers or provide a migration path. (Constitution IV.)

**Cross-cutting**

- **FR-022**: Every failure mode above MUST produce a clear, actionable diagnostic to the operator rather than a partial or hung state.
- **FR-023**: Documentation (README, CLAUDE.md, and this spec) MUST be updated in the same change as any behavior, scope, identity-contract, or security-posture change introduced by this feature. (Constitution — Development Workflow.)

### Key Entities *(include if feature involves data)*

- **Host**: a named deployment target. Attributes: name, driver kind, driver configuration (runtime context reference, or provider parameters), reachable address, and lifecycle/provisioning state. The authoritative record of *where* containers may run.
- **Driver**: the mechanism a host uses to build, run, and connect — abstracted so local and remote targets share one run path. The universal runtime is a container-runtime context (local endpoint or remote server).
- **Provisioner**: a provider-specific capability that allocates/de-allocates a server and yields a runtime context for it. Provider-specific concerns (API tokens, server sizes, locations, SSH keys) are confined here.
- **Deployment (container instance)**: an agent container bound to exactly one host, identified by its name; owns a generated declarative deployment artifact, a set of persistent volumes, published port(s), and injected identity material.
- **Injected identity material**: the container's SSH host key (secret) and authorized-keys (public), sourced locally and transferred to the deployment.
- **Host registry**: the persisted collection of Host records; the single source of truth that supersedes the prior static SSH address book.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After registering a local host, the operator can deploy and attach to an agent container with a single deploy command and a single attach command (no manual runtime wiring).
- **SC-002**: From an empty state with provider credentials, the operator can go from "no server" to "attached to an agent on a freshly provisioned cloud server" in one host-registration flow plus one deploy, with no manual server setup steps in between.
- **SC-003**: Deploying to a remote host transfers **no built container image** from the operator's machine (the image is built on the server); only source/build context and small identity material cross the wire.
- **SC-004**: N containers spread across at least two hosts run simultaneously with zero name, port, or volume collisions.
- **SC-005**: In 100% of cases, tearing down a container leaves its server and every other container on that server running; and deprovisioning a server that still hosts containers is refused 100% of the time.
- **SC-006**: No secret (provider token, private key) is ever written into an image or passed on a process command line — verifiable as zero occurrences.
- **SC-007**: After an unexpected container crash, the operator can reconnect to a restarted agent without manually recreating the container.
- **SC-008**: Every generated deployment artifact is human-readable and fully describes the container's services, persistent volumes, and injected identity, so the operator can inspect exactly what will run before or after it runs.
- **SC-009**: A failed provisioning attempt never leaves an unusable billable server silently running (operator is always informed, with cleanup offered or performed).

## Assumptions

- **First-release provider scope**: the only cloud provisioner in this release is **Hetzner**; "other IaaS providers later" is explicitly out of scope for now but the driver/provisioner split is designed so adding one is a new provisioner, not a change to the run path.
- **Run mechanism applies to all hosts**: the compose-based declarative run path replaces the prior imperative local run path too — local and remote deployments use the same mechanism, not two code paths.
- **Runtime floor**: target hosts provide a compose-capable container runtime (docker + compose v2, or equivalent). For provisioned cloud hosts the tool installs this; for operator-supplied hosts it is a prerequisite checked at registration/first deploy.
- **Remote build over context**: remote builds run on the server via its runtime context; no external image registry is introduced (avoiding an extra dependency — Constitution VI).
- **Reachability model**: attach reaches the container via the host's address and the container's published port (local hosts via localhost/forwarded, cloud hosts via public address); the existing in-container SSH server remains the attach endpoint, so no `exec`-into-container path is required.
- **Server↔container cardinality**: a server may host multiple containers; container identity is unique per host; the same container name may exist on multiple hosts.
- **Legacy compatibility**: existing plain SSH attach targets remain attachable during a deprecation window as a degenerate "connect to existing" host; they are not auto-migrated into full driver-backed hosts.
- **Credentials**: provider API tokens and SSH keys are injected at runtime from the operator's environment/config, never baked, never on argv (Constitution III); this feature does not introduce any stored long-lived secret.
- **Single operator**: one operator manages the fleet; no multi-tenant access control is in scope (Constitution — Platform & Interface Constraints).
- **Restart semantics**: automatic restart-on-crash is expected; it intentionally does not preserve the interactive tmux session — this is consistent with, and relies on, continuous externalization of durable state (Constitution I).
