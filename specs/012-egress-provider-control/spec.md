# Feature Specification: Egress and Provider Control

**Feature Branch**: `012-egress-provider-control`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Egress and provider control for agent containers. Today an agent can reach a model provider the operator never configured … The operator should be able to declare which providers an environment is permitted to reach, have anything undeclared refused or denied rather than silently allowed, and see the default-provider path made explicit instead of implicit."

## Overview

An agent container can talk to a model provider **the operator never chose**.

This is not a hypothesis. Feature 010's verification probe ran opencode inside a container with
**no operator credential of any kind** and it answered normally, reaching a built-in default
provider over the network. Nothing in the tool declared that provider, nothing recorded the
traffic, and nothing would have told the operator it happened.

The tool is otherwise strict about credentials — Constitution III governs how a key is delivered,
where it may rest, and that it never touches a volume. But it says nothing about **where an agent
may send data**, which is the other half of the same concern: a credential that never leaks is
small comfort if the prompt containing your source goes somewhere you did not sanction.

This feature makes the set of reachable providers **declared, enforced and visible**.

> **The hard constraint.** The container is **rootless and immutable at runtime** (Constitution
> II): no `sudo`, no capabilities added, nothing installed after build. Any control that requires
> new privileges — packet filtering, raw sockets, per-container firewall rules — is out of scope
> **by construction**, not by preference. Whatever this feature does, an unprivileged process
> must be able to do.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Declare which providers an environment may use (Priority: P1)

An operator states, per environment, which model providers that environment is permitted to
reach. Anything not on the list is refused. The declaration lives with the rest of the
environment's configuration and travels with the project.

**Why this priority**: Without a declaration there is nothing to enforce and nothing to audit.
This is the feature's foundation and the minimum that closes the observed gap.

**Independent Test**: Declare a single provider for an environment, confirm the agent can use it,
then confirm an attempt to use a second, undeclared provider does not succeed silently.

**Acceptance Scenarios**:

1. **Given** an environment declaring one provider, **When** the agent runs, **Then** it can
   reach that provider normally.
2. **Given** an environment declaring one provider, **When** the agent would reach a different
   one, **Then** that attempt does not silently succeed — the operator learns of it.
3. **Given** an environment that declares **no** providers, **When** it starts, **Then** the
   behaviour is defined and stated, not accidental (see FR-004).
4. **Given** a declaration, **When** the operator inspects the environment, **Then** the
   permitted set is visible without reading agent-specific configuration files.

---

### User Story 2 - The default-provider path is explicit (Priority: P1)

An operator can see that an agent has a built-in provider it will use absent any configuration,
and decide whether that is acceptable — rather than discovering it by observing traffic.

**Why this priority**: This is the specific defect that motivated the feature. A default that
works silently is indistinguishable, to the operator, from no network activity at all. It is P1
alongside US1 because declaring providers is meaningless if a default quietly bypasses the
declaration.

**Independent Test**: With no credential and no declaration, confirm the tool states — before or
at deploy — that the selected agent has a built-in default provider and what that implies.

**Acceptance Scenarios**:

1. **Given** an agent with a built-in default provider, **When** an environment is created
   without declaring providers, **Then** the operator is told, once and clearly, that the agent
   can reach a provider without their credential.
2. **Given** the same, **When** the operator declares providers, **Then** the interaction between
   the declaration and the built-in default is stated, not left ambiguous.
3. **Given** any supported agent, **When** the operator asks what it can reach, **Then** the
   answer comes from the tool rather than from the agent's own documentation.

---

### User Story 3 - Undeclared egress is recorded (Priority: P2)

When an agent reaches, or attempts to reach, a provider outside the declared set, that fact is
recorded where the operator will find it — not only in the moment, but afterwards.

**Why this priority**: Real value, but it builds on US1 and US2 and is useless without them.
Deferring it does not weaken the enforcement they provide.

**Independent Test**: Cause an undeclared provider to be contacted, then confirm the event is
discoverable after the container is gone.

**Acceptance Scenarios**:

1. **Given** an undeclared provider is contacted, **When** the operator inspects the environment,
   **Then** the event is visible.
2. **Given** the container has since been removed, **When** the operator looks for the event,
   **Then** it is still available (containers are ephemeral by Constitution I).
3. **Given** no undeclared egress occurred, **When** the operator inspects, **Then** there is no
   noise — silence means nothing happened.

---

### Edge Cases

- **An agent with no configurable provider list** — the limit of what can be enforced for that
  agent must be stated plainly, not implied to be equivalent to the others.
- **A declared provider the agent cannot use** (no credential for it) — must fail naming the
  missing credential, not the declaration.
- **An agent that ignores the mechanism** — if enforcement can be bypassed by the agent itself,
  that limit must be documented; a control presented as stronger than it is, is worse than none.
- **Enforcement without new privileges is not absolute** — the difference between *"the agent is
  configured not to"* and *"the network will not carry it"* must be explicit to the operator.
- **A provider reached indirectly** (a proxy, a gateway, a self-hosted endpoint) — declaring
  "anthropic" must not accidentally permit or forbid an unrelated endpoint.
- **Environments predating this feature** — must keep working; pre-1.0, no compatibility is
  promised beyond that.
- **Air-gapped or offline use** — declaring zero providers must be a coherent state, not a
  degenerate one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An operator MUST be able to declare, per environment, the set of model providers
  that environment is permitted to reach.
- **FR-002**: The declaration MUST live with the environment's other configuration and travel
  with the project, following the project/user configuration layering already established.
- **FR-003**: An attempt to reach a provider outside the declared set MUST NOT succeed silently.
  The operator MUST learn of it — at deploy time where that is possible, and at run time
  otherwise.
- **FR-004**: The behaviour when **no** providers are declared MUST be defined, documented and
  deliberate — not an accident of implementation. It MUST be stated whether that means "all",
  "none", or "the agent's default".
- **FR-005**: For every supported agent, the tool MUST be able to report **what that agent can
  reach**, including any built-in default provider, without the operator consulting the agent's
  own documentation.
- **FR-006**: When an agent has a built-in default provider that operates without an operator
  credential, the operator MUST be told **once and clearly**, rather than discovering it from
  traffic or from behaviour.
- **FR-007**: Enforcement MUST NOT require adding privileges, capabilities or runtime
  installation to the container (Constitution II). A control needing them is out of scope.
- **FR-008**: The **strength** of the enforcement MUST be stated honestly: whether it prevents
  egress or merely configures the agent not to attempt it, and what an agent that ignores the
  configuration could still do.
- **FR-009**: No provider declaration may expose a credential value, and declaring a provider
  MUST NOT imply storing its credential in the project (Constitution III, and the Feature 011
  rule that the repo holds a locator, never a value).
- **FR-010**: Undeclared egress events MUST be recorded such that they remain available after the
  container is removed (Constitution I — the container is ephemeral).
- **FR-011**: An environment declaring **zero** providers MUST be a coherent, supported state.
- **FR-012**: Behaviour for environments created before this feature MUST remain working, and any
  change in their effective permissions MUST be stated rather than silently applied.
- **FR-013**: The permitted set MUST be visible through the tool's existing machine-readable
  interface, so an agent operating the CLI can determine it without parsing prose.

### Key Entities *(include if feature involves data)*

- **Provider**: a named model endpoint an agent can reach (e.g. the vendor an API key belongs
  to). Identified by a stable name; distinct from the *credential* that authorises it.
- **Provider declaration**: the per-environment set of permitted providers, part of the
  environment's configuration.
- **Built-in default provider**: a provider an agent will use with no operator configuration —
  the thing this feature exists to surface.
- **Egress event**: a record that a provider was reached, or an attempt was made, including
  whether it fell inside the declared set.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every supported agent, an operator can determine the complete set of providers
  it may reach **without reading that agent's documentation** — verified for all four.
- **SC-002**: An environment that declares a provider set never reaches an undeclared provider
  without the operator being informed — **zero** silent occurrences.
- **SC-003**: An agent with a built-in default provider is disclosed to the operator in **100%**
  of environments where no provider is declared.
- **SC-004**: The enforcement strength is stated for every supported agent, with **zero** cases
  where the tool implies a stronger guarantee than it delivers.
- **SC-005**: No new privilege, capability or runtime installation is required — verified by the
  container running exactly as rootlessly as before.
- **SC-006**: An undeclared-egress event remains discoverable after the container is removed —
  **100%** of runs.
- **SC-007**: No credential value is exposed by the declaration mechanism — **100%** of runs.

## Assumptions

- **Enforcement is configuration-level, not packet-level.** Constitution II forbids the
  privileges packet filtering needs, so this feature configures agents and refuses deployments;
  it does not promise a determined process inside the container cannot open a socket. FR-008
  requires this be said out loud rather than implied away.
- **Provider identity is by name, not by endpoint.** Operators think in vendors; the mapping from
  a name to the hosts it implies is the tool's business, and is expected to change as vendors
  change theirs.
- **The four supported agents differ in what they permit.** Some expose a configurable provider
  list, some do not. The feature must degrade honestly per agent rather than pretend uniformity.
- Declaring providers is **opt-in**; an operator who declares nothing is not broken, but they
  are informed (FR-004, FR-006).
- The container remains **rootless and immutable at runtime**; nothing here changes what is baked
  at build time.

## Out of Scope

- Network-level packet filtering, firewalls, or anything requiring added capabilities.
- Controlling egress unrelated to model providers (package registries, git remotes, telemetry).
- Auditing the *content* of what an agent sends — this feature governs *where*, not *what*.
- Per-request cost or token accounting (that is the observability feature).
- Choosing or switching providers on the operator's behalf.

## Dependencies

- **Feature 003 / 008 (credentialing, credential managers)**: providers and credentials are
  related but distinct; the declaration must not become a second place a secret can live.
- **Feature 010 (opencode)**: the agent whose verified default-provider behaviour motivated this.
- **Feature 011 (filesystem layout)**: the declaration follows the established project/user
  configuration layering, and the repo-holds-a-locator rule.
- **Feature 009 (agent-operable CLI)**: FR-013's machine-readable exposure.
- **Constitution II (rootless, immutable runtime)**: the boundary that shapes the whole design.
- **Constitution III (least exposure)**: the principle this feature extends from "where a
  credential rests" to "where data goes".
