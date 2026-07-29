# Feature Specification: Control-Plane Container

**Feature Branch**: `017-control-plane`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Control plane containers — i.e. ssh to remote from my iPhone and get access to a configured agent-container CLI to manage my agent containers."

## Overview

Managing agent containers requires the operator's laptop.

The CLI runs on the operator's machine: the host registry lives there, the per-host state lives
there, credentials resolve there, and the tool assumes a shell it controls. That is a sound design
for the tool's actual job — driving containers — but it means the *management* surface is only
available where the tool is installed and configured.

The consequence is practical. An agent is running on a VPS, something needs attention, and the
operator has a phone. They can SSH to the VPS, but what they find there is a Docker daemon, not a
tool that knows what they have deployed, where else it is deployed, or how to stop it.

This feature makes the management surface itself something you can attach to: a **control-plane
container** — an agent-container the tool deploys, whose purpose is not to run an agent but to
give an SSH-reachable, already-configured CLI over the operator's environments.

> **The tool already knows how to do most of this.** It builds SSH-reachable containers with
> persistent identity, injects credentials without baking them, and attaches over `ssh … -t tmux`.
> The novelty is not the container; it is that this one is given the operator's *management*
> context rather than an agent's working context — which makes its blast radius, and the
> credentials it holds, categorically different from every container the tool has built so far.

## Clarifications

### Session 2026-07-29

- Q: How does a long-lived control plane hold host access without violating Constitution III?
  → A: **It mints its own.** On first deploy the control plane generates its **own** SSH keypair
  inside the container and stores it on its volume, **encrypted** with a passphrase the CLI prints
  **once**. The operator keeps that passphrase in their password manager. The tool therefore never
  handles the private key — there is no injection channel to violate — and the durable material is
  encrypted at rest with the decryption factor held entirely outside the system. This **fits** the
  existing carve-out (on-volume credentials are operator-interactive-login only) rather than
  requiring an exception to it.
- Q: When is the passphrase supplied? → A: **On every connect.** The control plane is
  **interactive-only**: it does nothing unattended, and its key stays locked whenever no operator
  is attached. After a host reboot it comes back locked, which is harmless because it has no
  unattended work to do.
- Q: Does it need separate host/daemon credentials to stop containers? → A: **No — the same key.**
  Remote daemon access in this tool is `ssh://user@host` (a docker context or podman connection),
  so daemon access *is* an SSH key. Authorising the control plane's **public** key in two places
  gives it two capabilities: in an agent container's `authorized_keys` → a shell inside it; on the
  **host account** → the daemon, and therefore lifecycle control.
- Q: How does the control plane obtain the inventory? → A: **It pulls, on connect.** Push is ruled
  out by interactive-only operation: a locked control plane cannot receive anything, and making it
  receivable would require giving agent containers credentials to write *into* it — inverting the
  trust direction, so that a compromised agent container could write to the thing that manages
  everything.

**Consequence, stated deliberately**: one key spans two very different privilege levels — a
sandbox shell and machine-level daemon access. That is accepted, because a control plane that can
inspect but not stop is a viewer, not a control plane. The passphrase is what carries that risk,
and it is why FR-004 and FR-008 exist.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Manage from a device that has nothing installed (Priority: P1)

An operator SSHes into a control-plane container from any device with an SSH client — a phone, a
borrowed laptop — and finds a working, configured CLI: it knows their hosts, and can list, stop
and inspect their environments.

**Why this priority**: This is the feature. Anything less than a usable CLI on arrival is just
another empty container.

**Independent Test**: From a client with no tool installed and no configuration, SSH in and
complete a full management task — list environments across hosts, then stop one — without
configuring anything on arrival.

**Acceptance Scenarios**:

1. **Given** a deployed control plane, **When** the operator SSHes in from an unconfigured
   device, **Then** the CLI is present, configured, and knows their registered hosts.
2. **Given** the session, **When** the operator lists environments, **Then** they see the same
   environments their laptop would show.
3. **Given** the session, **When** the operator stops an environment on another host, **Then** it
   stops, and the outcome is recorded as it would be from the laptop.
4. **Given** a small screen, **When** the operator works, **Then** the experience is usable —
   this surface exists for a phone.

---

### User Story 2 - Bound what it can do (Priority: P1)

The control plane holds credentials for reaching hosts. The operator can see exactly what it can
reach and act on, and can constrain that — because a container that can manage everything is a
container worth stealing.

**Why this priority**: P1, and arguably the reason to be careful shipping this at all. The tool's
whole credential posture (Constitution III) is built on secrets being ephemeral, never on a
volume, and scoped to one container's job. A long-lived container holding host access inverts
that. Shipping US1 without US2 would trade a real security property for convenience.

**Independent Test**: Deploy a control plane scoped to a subset of hosts and confirm it cannot
reach or act on the others, and that this is visible before deploying.

**Acceptance Scenarios**:

1. **Given** a control plane, **When** the operator inspects it, **Then** they can see which
   hosts it can reach and what it is permitted to do.
2. **Given** a scoped control plane, **When** it attempts an out-of-scope host, **Then** the
   attempt fails and is visible.
3. **Given** any control plane, **When** an operator considers deploying one, **Then** the
   security consequences are stated up front, not discovered later.
4. **Given** a compromised or suspect control plane, **When** the operator revokes it, **Then**
   its access ends without requiring every host to be reconfigured by hand.

---

### User Story 3 - Survive being the thing that manages everything (Priority: P2)

The control plane is itself an environment the tool knows about: it appears in the inventory, can
be stopped, and cannot quietly destroy itself while doing so.

**Why this priority**: Necessary for coherence, but only once US1 and US2 exist. It is where the
recursion has to be handled deliberately.

**Independent Test**: From inside a control plane, invoke a kill switch and confirm the behaviour
regarding its own container is defined and safe.

**Acceptance Scenarios**:

1. **Given** a control plane, **When** the operator lists environments, **Then** it appears among
   them, identified as a control plane rather than an agent environment.
2. **Given** an operator inside a control plane, **When** they invoke an action that would stop
   everything, **Then** the treatment of its own container is defined — refused, deferred, or
   last — and never an accidental self-termination mid-operation.
3. **Given** a control plane that is stopped, **When** it is restarted, **Then** it is usable
   again without reconfiguration.

---

### Edge Cases

- **Self-termination** — the container must not destroy itself partway through an operation and
  leave the result unknown.
- **Two control planes** — must not conflict, and each must be identifiable.
- **A control plane deployed to a host it also manages** — must be coherent.
- **Credential exposure inside the container** — anyone with the session has whatever it holds;
  this is the feature's central risk and must be stated, not implied.
- **A stale control plane** — one whose tool version predates the environments it manages, or
  whose host registry has drifted.
- **Loss of the SSH key** to the control plane — recovery must not require rebuilding every
  managed host.
- **A phone-sized screen** — output that assumes a wide terminal is unusable for the actual
  motivating case.
- **An interrupted mobile connection** mid-operation — must not corrupt state; the session ends,
  the operation's outcome must still be knowable.
- **Nested control planes** — must be prevented or deliberately supported, not accidental.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST be able to deploy a **control-plane environment** whose purpose is
  management rather than running an agent.
- **FR-002**: An operator MUST be able to reach it over SSH from a device with **no tool
  installed and no configuration**, and find a working, configured CLI.
- **FR-003**: The control plane MUST be able to enumerate and act on the operator's environments
  across the hosts it is permitted to reach.
- **FR-003a**: It MUST obtain the inventory by **pulling on connect**, never by receiving pushes.
  A locked control plane cannot receive, and making it receivable would require agent containers
  to hold credentials into it — inverting the trust direction.
- **FR-004**: The control plane's reach MUST be **declared and visible**, and constrainable to a
  subset of hosts. Scope is defined by **where its public key is authorised** — an enforceable
  boundary outside the container, not a setting the container could ignore.
- **FR-005**: An out-of-scope action MUST fail visibly rather than partially succeed.
- **FR-006**: The security consequences of deploying one MUST be stated **before** deployment —
  specifically that a session holds whatever access the container holds.
- **FR-007**: The control plane MUST **generate its own** SSH keypair inside the container on
  first deploy. The private key MUST be stored **encrypted at rest** on its volume, with a
  passphrase the tool prints **exactly once** and never stores. The tool MUST NOT transmit,
  persist or otherwise handle that private key — it has no injection channel for it.
- **FR-007a**: The control plane MUST be **interactive-only**. It performs no unattended work,
  and its key MUST remain locked whenever no operator is attached. The passphrase MUST be supplied
  by the operator **on connect**.
- **FR-007b**: The control plane's **public** key is what grants capability. Authorised in an
  agent container it grants a shell there; authorised on a **host account** it grants daemon
  access and therefore lifecycle control. Both MUST be explicit acts, never implicit in
  deployment.
- **FR-008**: The operator MUST be able to **revoke** a control plane by withdrawing its public
  key from the hosts and containers that trust it. The tool MUST perform that withdrawal across
  them from a single command — the operator does not edit N hosts by hand.
- **FR-009**: The control plane MUST appear in the inventory, identified as a control plane
  rather than an agent environment.
- **FR-010**: An action invoked from inside a control plane that would stop or destroy **its own
  container** MUST have defined behaviour, and MUST NOT self-terminate mid-operation leaving the
  outcome unknown.
- **FR-011**: Output MUST be usable on a **narrow screen** — the motivating case is a phone.
- **FR-012**: A stopped or rebooted control plane MUST be usable again **without
  reconfiguration**: its key persists on its volume, and the operator supplies the passphrase on
  the next connect. Recovery MUST NOT require the operator's own machine.
- **FR-013**: An interrupted session MUST NOT corrupt state, and the outcome of an in-flight
  operation MUST remain knowable afterwards.
- **FR-014**: Multiple control planes MUST be individually identifiable and MUST NOT conflict.
- **FR-015**: The image MUST remain **rootless and immutable at runtime**; the control plane adds
  no privileges (Constitution II).
- **FR-016**: A control plane whose tool version differs from what an environment was created
  with MUST behave predictably and say so.

### Key Entities *(include if feature involves data)*

- **Control plane**: an environment whose role is management — its permitted hosts, permitted
  actions, and identity.
- **Permission scope**: which hosts it may reach and what it may do there.
- **Session**: an operator's SSH connection to it. The key is unlocked for the session and
  locked again when it ends.
- **Control-plane keypair**: generated in-container, private half encrypted at rest on its volume,
  public half authorised wherever the control plane is meant to reach.
- **Passphrase**: printed once at deploy, held by the operator outside the system, supplied on
  every connect. The tool never stores it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator completes a full management task — list across hosts, then stop one —
  from a device with nothing installed, configuring nothing on arrival.
- **SC-002**: The environments listed from a control plane match those listed from the operator's
  own machine — **zero** divergence for hosts in scope.
- **SC-003**: An out-of-scope host is unreachable from the control plane — **zero** successful
  out-of-scope actions.
- **SC-004**: The permitted scope is visible before deployment — **100%** of deployments.
- **SC-005**: Revoking a control plane ends its access without per-host manual reconfiguration —
  **100%**.
- **SC-006**: A stop-everything action invoked from inside never leaves its own container's
  outcome unknown — **zero** occurrences.
- **SC-007**: Output is legible at **80 columns or fewer** — verified for every management
  command.
- **SC-008**: No new class of durable secret is introduced — verified against the credential
  rules — **100%**.

## Assumptions

- **This is still the highest-risk feature in the roadmap, but the risk is now located.** It is
  not that the tool must bend its credential rules — the control plane mints its own key and the
  tool never handles it, which fits the existing operator-interactive carve-out. The risk is that
  **one key spans two privilege levels**: a sandbox shell in an agent container, and daemon access
  on a host. Whoever holds the volume *and* the passphrase holds both. That is accepted
  deliberately, because a control plane that can inspect but not stop is a viewer; the passphrase
  is what carries the risk, and FR-004 and FR-008 are the controls on it.
- **It reuses what exists, including the credential shape.** SSH-reachable containers, persistent
  identity and `attach` are built, and remote daemon access is already `ssh://user@host` — so a
  keypair is the *only* credential type involved. Nothing new is invented; what changes is where
  the public half is authorised.
- **The phone is the motivating client**, so narrow output is a requirement rather than a
  courtesy.
- **It must be deployable last.** It consumes the inventory, the kill switch and `doctor`;
  specifying it before those would mean guessing at their interfaces.
- Scope is **which hosts and containers authorise the public key**. That makes it enforceable
  outside the container rather than by the container's own good behaviour, and it makes revocation
  concrete: withdraw the key.
- **Standing authorisation is a new concept.** Until now, keys were injected per deployment. A
  control plane's public key is authorised across many containers and hosts, including ones
  created later — so it is a *standing* key, and it is the thing an attacker would target.

## Out of Scope

- A web UI, an HTTP API, or any non-SSH surface.
- Multi-user or multi-tenant access control — single operator remains assumed.
- Running agents inside the control plane.
- Cross-operator or shared control planes.
- Automatic or unattended deployment of control planes.

## Dependencies

- **Feature 013 (`doctor`)**, **014 (inventory)**, **015 (kill switch)**, **016
  (observability)**: the management surface it exposes. It should be specified last and built
  last for exactly this reason.
- **Feature 001 / 002 (hosts, lifecycle)**: the registry it carries and the verbs it offers.
- **Feature 003 / 008 (credentialing)**: the operator-interactive carve-out FR-007 relies on —
  on-volume credentials are permitted when they originate from an operator-interactive act, which
  is exactly what generating a passphrase-protected key at deploy is.
- **Feature 014 (inventory)**: pulled on connect (FR-003a), never pushed.
- **Feature 005 (shell integration)**: the attach path this reuses.
- **Constitution II (rootless, immutable runtime)**: FR-015.
- **Constitution III (least exposure)**: the principle this feature strains hardest, and the
  reason FR-004/FR-006/FR-008 exist.
