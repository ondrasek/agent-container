# Feature Specification: Podman secrets

**Feature Branch**: `025-podman-secrets`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Support for podman secrets."

## Why this exists

`docs/credentials.md` already names the destination: *"If hardening the HTTPS path is needed later,
the upgrade path is: switch `GH_TOKEN` to a compose `secrets:` block (or `podman secret` on the
VPS) … and read `/run/secrets/gh-token` in the entrypoint instead of `$GH_TOKEN`."* That sentence
has been sitting in the threat model's mitigation table for several features, describing a path
nobody has built.

Today every credential the tool delivers has the same shape: **the tool holds the plaintext**, if
only for the moment it takes to push it into a running container over that container's own sshd.
Constitution IX makes that push the one legitimate channel, and it is a good answer to the question
it was asked — *how does a secret get in without entering the deployment description*. But it
answers that question by making the tool a courier, and a courier is a thing that can drop what it
carries: into a traceback, a `--json` payload somebody adds later, a debug log, a process table.
Feature 019 removed an entire class of this exposure by making the container generate its own SSH
key so the tool never sees one at all, and the threat model calls that *eliminated by design* rather
than mitigated.

**A podman secret offers the same shape for credentials the container cannot generate itself.** The
operator creates it on the host; the container mounts it; the tool names it and never touches the
value. That is not a weaker version of Constitution IX — it is the same principle applied one step
further back.

## The tension this feature exists to resolve

Constitution IX says secrets travel to the container **over its own sshd**, explicitly **not** the
container runtime's channel, and gives a specific reason: that channel's security is whatever the
operator's context happens to be, so a `tcp://` context would carry the plaintext in the clear. The
tool can only *check* that channel, never *provide* it — and a guard against your own transport is
a sign you picked the wrong one.

Podman secrets are a **runtime-side store**. On its face that is the forbidden channel.

**The distinction that decides it is WHO PUTS THE VALUE THERE.**

| | Tool CREATES the secret | Tool REFERENCES an existing secret |
|---|---|---|
| Who holds the plaintext | the tool, then the runtime | only the operator and the runtime |
| How it reaches the store | over the runtime channel — **`tcp://` carries it in the clear** | it is already there; nothing is sent |
| Constitution IX | **violated**, exactly as written | **not engaged** — the tool transports nothing |
| Compared to today | strictly worse than the sshd push | strictly better: one fewer holder |

Creating is the thing IX forbids, and forbids for a reason that has been measured. Referencing is
a different act that happens to touch the same subsystem. **This feature is the second column.**

A secondary consequence makes it more than a technicality: `configs: {file:}` is a daemon-side bind
that was **measured** not to cross a remote context (the 001/003 lesson). A podman secret has the
same daemon-side nature, but that is an *advantage* here rather than a defect — for a remote host
the secret already lives on that host, so nothing crosses at all. The mechanism that broke config
delivery is the mechanism that makes this one work.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Give a container a credential the tool never sees (Priority: P1)

An operator running a VPS creates a podman secret on it once — `podman secret create gh-token -` —
and declares in their environment's configuration that `GH_TOKEN` comes from that secret. They
deploy. The container reads the token; the tool never had it, never transported it, and has nothing
to drop.

**Why this priority**: it is the feature. Everything else here is the consequence of getting this
one interaction honest.

**Independent Test**: create a podman secret on a host, declare it, deploy, and assert the
container can read the value — then assert the value appears nowhere on the operator's machine, in
the deployment description, in any run record, or in any `--json` output.

**Acceptance Scenarios**:

1. **Given** a podman secret that exists on the target host, **When** an environment declares a
   credential sourced from it, **Then** the container receives the value and the tool never reads
   it.
2. **Given** the same deployment, **When** the operator inspects the generated deployment
   description, **Then** it carries the secret's NAME and no part of its value — the description is
   a plan that outlives the need, and nothing with that lifetime may hold a secret.
3. **Given** a declared secret that does NOT exist on the host, **When** the operator deploys,
   **Then** the tool refuses before creating anything and names the secret and the host, because a
   container that starts without the credential it was promised fails later and further away.
4. **Given** a remote host reached over an `ssh://` or `tcp://` context, **When** the deployment
   runs, **Then** the value crosses no channel at all — it was already on that host.

---

### User Story 2 - Know what a container will hold before it holds it (Priority: P1)

An operator about to deploy can see which credentials arrive by which route: pushed by the tool over
sshd, or mounted by the runtime from a store the tool cannot read. The two have different exposure
and different revocation, and an operator who cannot tell them apart cannot reason about either.

**Why this priority**: Constitution VIII — a reader reports absence, and absent ≠ defaulted ≠
declared-empty. A credential whose *route* is invisible is a defaulted decision nobody made.

**Independent Test**: declare one credential of each kind, deploy, and assert the tool states both
and distinguishes them.

**Acceptance Scenarios**:

1. **Given** an environment declaring both kinds, **When** the operator deploys, **Then** the tool
   states which credentials it will push and which the runtime will mount, before it creates
   anything.
2. **Given** a running environment, **When** the operator asks what it holds, **Then** referenced
   secrets are listed by NAME and never by value, and are marked as not-tool-held.
3. **Given** a referenced secret, **When** the operator runs `--purge`, **Then** the tool states
   that it did NOT remove the secret, because it does not own it — see the revocation limit below.

---

### User Story 3 - It behaves the same on both runtimes, or says why not (Priority: P1)

An operator on docker declares a referenced secret. They are told plainly that this route is
podman-only and why, at declaration time. They are never given a deployment that silently delivered
nothing.

**Why this priority**: ADR 0001 makes podman the default, so this is not a niche path — but "works
on one runtime and silently does nothing on the other" is precisely the divergence this project
keeps finding (a docker-only DNS rule survived months of green builds while being inert under the
default runtime). A credential that silently fails to arrive is the worst version of it.

**Independent Test**: declare a referenced secret against a docker host and assert the tool refuses
with a reason, rather than deploying a container missing its credential.

**Acceptance Scenarios**:

1. **Given** a docker host, **When** an environment declares a referenced secret, **Then** the tool
   refuses and names the runtime as the reason.
2. **Given** a host whose runtime cannot be determined, **When** a referenced secret is declared,
   **Then** the tool refuses rather than assuming — an assumption here is a credential that may not
   arrive.
3. **Given** a mixed fleet, **When** the operator declares a referenced secret at the user level,
   **Then** the refusal names which hosts it cannot serve, not merely that some cannot.

---

### Edge Cases

- **The secret changes after the container starts.** Podman mounts a snapshot; a rotated secret does
  not reach a running container. The tool MUST NOT imply otherwise, and the remedy is a recreate —
  stated where an operator will meet it, not discovered when a rotated credential appears not to
  have rotated.
- **The tool cannot reconcile what it did not create.** Constitution IX's persistence clause pairs
  persistence with reconciliation: whatever holds a secret must be removed when the operator stops
  declaring it, or the declaration stops being the authority. **That clause cannot be honoured for a
  referenced secret, and this feature must say so rather than pretend.** `--purge` removes the
  tool's own artifacts; the podman secret is the operator's, and removing it could break another
  container the tool knows nothing about. This is a real reduction in what the tool can promise, and
  it is the price of not holding the value.
- **A secret name that is not a name.** Names reach a runtime command line. They are validated at
  the surface, the way every other operator-supplied name in this tool is.
- **The same name, different hosts, different values.** A name is resolved per host. The tool does
  not assume a name means the same thing on two machines, and says which host a refusal is about.
- **A referenced secret and a pushed credential targeting the same variable.** A conflict, refused
  at the surface — two routes to one destination means one of them silently loses, and which one is
  not something an operator should have to discover.
- **The container cannot read the mounted secret.** A permission or path failure inside the
  container looks identical to "the credential was never declared". It must not: the entrypoint
  distinguishes *absent* from *present but unreadable*.
- **Rootless podman, and whose store it is.** Secrets belong to the user running podman. A secret
  created by a different user on the same host is not visible, and a refusal that says "no such
  secret" when the truth is "not yours" sends an operator to the wrong place.
- **`podman secret` stores the value unencrypted by default.** Referencing one does not make a host
  secure that was not. The tool MUST NOT imply that using this route hardens anything about the host
  itself; what it changes is who holds the value *in transit and in this tool*.

## Requirements *(mandatory)*

### Functional Requirements

**The boundary**

- **FR-001**: The tool MUST support declaring a credential whose value lives in a **runtime-managed
  secret store** on the target host, identified by NAME.
- **FR-002**: The tool MUST NOT read the value of such a secret, at any point, for any purpose —
  including validation, diagnostics and error messages. The whole of this feature's benefit is that
  the tool is not a holder; a single read that "just checks" restores the exposure it removes.
- **FR-003**: The tool MUST NOT CREATE, write, update or delete a secret in that store. Creating one
  means sending a plaintext value over the runtime channel, which is exactly what Constitution IX
  forbids and for a reason that was measured: a `tcp://` context carries it in the clear.
- **FR-003a**: The tool MUST NOT offer a convenience that creates one on the operator's behalf, and
  MUST NOT leave a dormant path toward doing so. A capability that exists but is switched off is one
  an operator cannot verify the absence of, and the absence is the property being claimed.
- **FR-004**: The secret's NAME MAY appear in the deployment description; its VALUE MUST NOT, nor
  may the description reference a file the tool wrote containing it. A description is a plan that
  outlives the need (Constitution IX).

**Refusing rather than half-delivering**

- **FR-005**: The tool MUST verify that a declared secret EXISTS on the target host before creating
  anything, and MUST refuse naming both the secret and the host when it does not. Existence is
  checkable without reading the value.
- **FR-006**: The tool MUST refuse a referenced secret on a runtime that does not support this
  mechanism, naming the runtime as the reason. It MUST NOT fall back to another delivery route, and
  MUST NOT deploy a container whose credential will not arrive.
- **FR-006a**: A runtime that cannot be determined MUST be a refusal, not an assumption. An
  assumption here is a credential that may silently not arrive.
- **FR-007**: The tool MUST refuse a declaration that routes two different credentials to the same
  destination, rather than letting one silently win.
- **FR-008**: Secret names MUST be validated at the surface, as every other operator-supplied name
  in this tool is.

**Saying what is true**

- **FR-009**: Before creating anything, the tool MUST state which credentials it will PUSH and which
  the runtime will MOUNT. The two have different exposure and different revocation, and a route the
  operator cannot see is a decision nobody made (Constitution VIII).
- **FR-010**: Wherever the tool enumerates what an environment holds, a referenced secret MUST
  appear by name, never by value, and MUST be marked as **not held by this tool**.
- **FR-011**: The tool MUST state, at the point an operator would otherwise assume otherwise, that
  **it cannot revoke a referenced secret**. `--purge` MUST say what it did not remove. Constitution
  IX's persistence-plus-reconciliation clause cannot be honoured for a value the tool does not own,
  and the honest response is to name the gap, not to narrow the claim quietly.
- **FR-012**: The tool MUST state that a rotated secret does not reach a RUNNING container, and name
  the remedy.
- **FR-013**: The tool MUST NOT describe this route as making a host more secure. It changes who
  holds a value in transit and within this tool; it does not encrypt a store that is not encrypted.

**Inside the container**

- **FR-014**: The entrypoint MUST distinguish a credential that is **absent** from one that is
  **present but unreadable**. The two have different causes and different remedies, and reporting
  them identically is the silent-failure shape this project keeps finding.
- **FR-015**: A referenced secret MUST NOT be copied onto any volume, and MUST NOT outlive the
  container through any artifact the tool creates. The operator's store is the durable copy; the
  tool adds no second one.

**Reconciling with what exists**

- **FR-016**: This route MUST NOT change how any existing credential source behaves. An operator who
  declares nothing new sees nothing new.
- **FR-017**: This route MUST NOT become a way to deliver material the tool refuses to handle
  elsewhere — in particular it MUST NOT become a channel for an SSH private key, which Features
  018/019 removed entirely and which the tool has no path that accepts.
- **FR-018**: The tool MUST continue to mint nothing. A referenced secret is the operator's
  declaration about a value the operator created.

### Key Entities

- **Referenced secret**: a credential that exists in a runtime-managed store on a host, named in an
  environment's declaration, mounted into the container by the runtime. The tool knows its name, its
  host and its destination inside the container — and not its value.
- **Delivery route**: how a declared credential reaches a container — *pushed* by the tool over the
  container's own sshd, or *mounted* by the runtime. A property of each declaration, visible before
  deploy and after.
- **Existence check**: the question "is this name present in that host's store", answerable without
  reading the value, and the thing FR-005 refuses on.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A credential delivered by this route appears nowhere on the operator's machine, in the
  deployment description, in any run record, or in any machine-readable output — verified by
  searching all four for the value after a successful deployment.
- **SC-002**: The tool makes zero read accesses to a referenced secret's value across the feature's
  whole test suite, asserted structurally rather than observed, because a negative property observed
  on the paths a test happened to exercise is not a property.
- **SC-003**: A declared secret that does not exist on the target host produces a refusal naming the
  secret and the host, and creates nothing, 100% of the time.
- **SC-004**: A referenced secret declared against an unsupported or undetermined runtime produces a
  refusal naming the runtime, and never a container missing its credential.
- **SC-005**: Before a deployment, an operator can see for every declared credential which route it
  takes, without reading the generated deployment description.
- **SC-006**: `--purge` on an environment with a referenced secret states that the secret was not
  removed and why.
- **SC-007**: A container whose mounted secret is unreadable reports something different from one
  whose credential was never declared, verified by producing both states.
- **SC-008**: An operator declaring nothing new observes no change in behaviour, verified by the
  existing credential suites passing unchanged.

## Assumptions

- **Reference-only is the whole feature.** Creating a secret is not a smaller version of this
  feature, it is the thing Constitution IX forbids; the spec treats it as out of scope rather than
  deferred, so that no later change can read "we did the read-only half first".
- **The operator's store is the authority.** Its contents, encryption, backup and access control are
  the operator's, not the tool's. This feature reduces what the tool holds; it does not take
  responsibility for the host.
- **Existence is checkable without reading.** The runtime can answer "does this name exist" without
  returning the value. If that turns out to be false on some runtime, FR-005 must be reconsidered
  rather than satisfied by reading.
- **The destination inside the container is a file.** Runtime-mounted secrets appear as files; a
  declaration therefore names a path, and whatever consumes it reads a file rather than an
  environment variable. Existing file-based credential consumption is reused.
- **Docker is out of scope for the mechanism, not for the refusal.** Docker's secret support is tied
  to swarm and has different semantics; this feature does not attempt to unify them. What it does
  guarantee is that a docker operator is told, not silently under-served.
- **No new dependency.** The runtime's own client is already required and already used; nothing is
  added (Constitution VI).
- **Existing machinery is reused.** No new way to reach a host, generate a deployment or record a
  creation is introduced.
