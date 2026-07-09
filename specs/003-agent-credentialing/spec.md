# Feature Specification: Agent Provisioning & Credentialing (deploy agent config, inject keys and secrets)

**Feature Branch**: `003-agent-credentialing`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Deploying agents and configurations, injecting keys and secrets" — give each deployed container everything an agent needs to function: its configuration (both operator-canonical and mutable runtime state) and its credentials (an SSH key it pushes with, model/API credentials, and supporting non-secret material), provisioned at runtime under a strict least-exposure discipline.

## Context & Boundary

This is the **credentialing / provisioning layer** for agents. In the feature ladder: 001 = *where* containers run (hosts), 002 = the *lifecycle verbs*, 003 (this feature) = *what an agent needs to function and how it is delivered*, 004 = *running and attaching to* the agent. **This feature owns the delivery of configuration and secrets into a deployment**; it does not run the agent, manage tmux/attach, or choose interactive vs headless (that is Feature 004, which **depends on** the git push credential defined here). It inherits from Feature 001 the compose-based delivery of injected material (`secrets`/`configs`) and the runtime-injection-never-baked rule.

**Governing principle**: Constitution III (Least Exposure) and hard-constraint #4 (agents push autonomously; push auth must work non-interactively; never embed long-lived secrets in the image — inject at runtime).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An agent can push its work autonomously (Priority: P1)

The operator provisions a deployment with an SSH credential the agent uses to push to the remote. From inside the container the agent commits and pushes without any interactive prompt — no passphrase, no host-key confirmation. This is the single most important capability: the whole system rests on agents externalizing work continuously (Constitution I), which is impossible if a push blocks on a prompt.

**Why this priority**: Without non-interactive push, the ephemeral-container model is unsafe — uncommitted work would be trapped in a disposable container. Everything else in this feature is in service of, or secondary to, this.

**Independent Test**: Provision a deployment with a push SSH key; from inside the container, clone a repo, make a commit, and push — confirm it completes with no interactive prompt and no host-key verification stall.

**Acceptance Scenarios**:

1. **Given** a deployment provisioned with a push SSH key, **When** the agent pushes a commit to the remote, **Then** the push succeeds with no passphrase prompt and no host-key confirmation prompt.
2. **Given** the push key is provisioned, **When** the container is inspected, **Then** the key is present only as a runtime-injected, read-only credential and is **not** found baked into any image layer nor on any process command line.
3. **Given** the push key material, **When** the container is torn down, **Then** no copy of the private key remains in any host-side persistent volume — the operator's local copy is the only durable copy.
4. **Given** the outbound push key and the inbound host key (Feature 001), **When** both are provisioned, **Then** they are distinct credentials with distinct roles and neither is used in place of the other.

---

### User Story 2 - An agent is provisioned with model/API credentials safely (Priority: P1)

The operator supplies the credential an agent needs to reach its model/backend (an API key or an equivalent stored authorization). The tool delivers it to the container so the agent can operate, while keeping the credential off the container's command line and out of places where it is casually observable, and never persisting it on the host.

**Why this priority**: An agent that cannot reach its model cannot work at all; this is co-critical with push. It is separated from US1 because the delivery mechanism and the exposure risks differ.

**Independent Test**: Provision a deployment with a model/API credential; confirm the agent can perform an action requiring the backend; then confirm the credential does not appear on the process command line, in the built image, or in a host persistent volume.

**Acceptance Scenarios**:

1. **Given** a model/API credential supplied by the operator, **When** the deployment starts, **Then** the agent can perform an operation that requires the backend.
2. **Given** the credential is delivered, **When** the container or its deployment description is inspected, **Then** the credential value does not appear on any command line nor literally in the deployment description.
3. **Given** an agent that can only consume the credential via its environment, **When** the credential is provisioned, **Then** it is delivered as a runtime file and placed into the agent's environment **inside** the container (not via the host-side launch), and this fallback is recorded as such.
4. **Given** the credential material, **When** the container is torn down, **Then** no copy remains in a host persistent volume.

---

### User Story 3 - Operator config propagates; agent runtime state persists (Priority: P2)

The operator maintains canonical agent configuration on their own machine (settings, project guidance, tool/MCP definitions without embedded secrets). On each deploy, that canonical configuration is delivered into the container so edits made locally propagate on redeploy. Meanwhile the agent's own mutable runtime state (history, caches, learned state) persists across recreation in the deployment's per-agent storage.

**Why this priority**: It makes deployments reproducible and keeps the operator's configuration authoritative, but an agent can function on defaults, so it ranks below the two credential stories.

**Independent Test**: Provision a deployment, edit the canonical config locally, redeploy, and confirm the change is reflected in the container; separately, cause the agent to write runtime state, recreate the container, and confirm the runtime state is still present.

**Acceptance Scenarios**:

1. **Given** canonical agent configuration on the operator's machine, **When** a deployment starts, **Then** that configuration is present in the container.
2. **Given** a running deployment, **When** the operator edits the canonical config locally and redeploys, **Then** the change is reflected in the container (canonical config is delivered fresh each deploy).
3. **Given** an agent that has written runtime state, **When** the container is disposed and recreated by the same name, **Then** the runtime state is restored from the per-agent persistent storage.
4. **Given** canonical config and runtime state coexist for one agent, **When** both are provisioned, **Then** operator-owned files are delivered as fresh canonical material while mutable runtime state is served from persistent storage, without one clobbering the other.

---

### User Story 4 - Secrets rotate cheaply and are scoped narrowly (Priority: P3)

Because every secret is injected at runtime from the operator's machine and never baked or persisted, rotating a secret is: change it locally, redeploy. The operator can also scope the push credential narrowly (e.g. a per-repository deploy key) to limit blast radius, in addition to the default single user key.

**Why this priority**: Rotation and scoping are important security properties but are emergent from the injection model of US1–US2; they are called out to ensure they are verified, not bolted on.

**Independent Test**: Rotate a provisioned secret by changing it locally and redeploying; confirm the new secret is in effect and the old one is nowhere on the host. Provision a narrowly-scoped push credential and confirm it grants only the intended access.

**Acceptance Scenarios**:

1. **Given** a provisioned secret, **When** the operator changes it locally and redeploys, **Then** the new value is in effect and no baked or persisted copy of the old value exists.
2. **Given** the push credential, **When** the operator chooses a narrowly-scoped credential instead of the default, **Then** the deployment uses it and its access is limited to the intended scope.

---

### Edge Cases

- **Missing credential at deploy**: provisioning references a secret that is absent on the operator's machine — deploy fails fast with a clear message rather than starting an agent that cannot push or reach its model.
- **Remote delivery**: a secret/config referenced by a deploy to a remote host is delivered to that host over the runtime context (not left behind as an empty local-only bind), consistent with Feature 001.
- **Two-key confusion**: the inbound sshd host key and the outbound push key are never conflated or interchanged.
- **Non-interactive host verification**: outbound push does not stall on unknown-host verification (the remote's host identity is pre-provisioned as trusted material).
- **Agent cannot read a credential from a file**: for such an agent, the credential is still delivered as a runtime file and placed into the environment inside the container; it is never passed on the launch command line.
- **Secret leakage surfaces**: secrets do not appear in image layers, deployment descriptions, command lines, or host persistent volumes; the operator's local copy remains the sole durable copy.
- **Config vs secret misfiling**: material that carries a secret (e.g. a tool definition containing a token) is treated as a secret, not as non-secret config.
- **Partial provisioning**: if some material is delivered and a later item fails, the deploy does not leave a half-credentialed agent silently running.

## Requirements *(mandatory)*

### Functional Requirements

**Push credential (outbound)**

- **FR-001**: The system MUST provision an **SSH credential the agent uses to push** to remotes, delivered as runtime-injected material, such that the agent can commit and push **non-interactively** (no passphrase prompt, no host-key confirmation) from inside the container.
- **FR-002**: The push credential MUST be **distinct from the inbound sshd host key** (Feature 001): the two are separate credentials with separate roles and MUST NOT be interchanged.
- **FR-003**: The system MUST provision the **trusted remote host identity** (known-hosts material for the push remote) so outbound push never stalls on unknown-host verification.
- **FR-004**: The system MUST support **scoping the push credential**: a default single user key, and the option of a **narrowly-scoped per-repository credential** to reduce blast radius.

**Model/API credentials**

- **FR-005**: The system MUST provision the **model/API credential** an agent needs to reach its backend, delivered as runtime-injected material, such that the agent can operate.
- **FR-006**: Model/API credentials MUST be delivered **as files by default** and placed into the agent's environment **inside the container** only where an agent cannot consume a file; the credential MUST NOT be placed on any process command line nor written literally into the deployment description.

**Configuration (non-secret)**

- **FR-007**: The system MUST deliver **operator-canonical agent configuration** (settings, project guidance, tool/MCP definitions without embedded secrets) into the container **fresh on each deploy**, so local edits propagate on redeploy.
- **FR-008**: The system MUST preserve the agent's **mutable runtime state** (history, caches, learned state) across container recreation via per-agent persistent storage, without the fresh canonical delivery clobbering it.
- **FR-009**: Material that carries a secret MUST be classified and handled **as a secret**, not as non-secret configuration.

**Least-exposure invariants (cross-cutting)**

- **FR-010**: No secret MUST ever be **baked into an image layer**.
- **FR-011**: No secret MUST ever appear on a **process command line**.
- **FR-012**: No secret MUST **rest in a host persistent volume**; secrets are delivered read-only and vanish with the container, leaving the operator's local copy as the sole durable copy.
- **FR-013**: Each secret MUST be delivered **only to the deployment that needs it** (no broader distribution).
- **FR-014**: All injected material MUST be delivered to the target host **over the runtime context** so a remote deployment receives it (never a local-only reference that resolves empty remotely) — inherited from Feature 001.
- **FR-015**: **Rotating** any secret MUST require only changing it on the operator's machine and redeploying; no baked or persisted copy may survive the rotation.

**Robustness**

- **FR-016**: If any referenced secret or config is **absent on the operator's machine at deploy**, the deploy MUST fail fast with a clear diagnostic and MUST NOT start a partially-credentialed agent.
- **FR-017**: If provisioning delivers some material and a later item fails, the system MUST NOT leave a **half-credentialed agent running**; it surfaces the failure.
- **FR-018**: Documentation (README, CLAUDE.md, this spec, and the credentials guidance) MUST be updated in the same change as any change to what is injected, how, or its exposure posture (Constitution — Development Workflow).

### Key Entities *(include if data involved)*

- **Injected material**: any file delivered into a deployment at runtime. Classified as **secret** (private, read-only, ephemeral, never persisted) or **config** (non-secret, may persist). Sourced from the operator's machine; delivered over the runtime context.
- **Push credential**: the outbound SSH key (plus the trusted-remote-host identity) the agent pushes with. Secret; scoped as a single user key or a per-repository key.
- **Model/API credential**: the authorization an agent needs to reach its backend. Secret; delivered as a file, placed into the in-container environment only as a fallback.
- **Canonical agent configuration**: operator-owned, non-secret configuration delivered fresh on each deploy (source of truth = operator's machine).
- **Agent runtime state**: mutable state the agent writes during operation, persisted across recreation in per-agent storage.
- **Host identity keys** *(distinction, some from Feature 001)*: the **inbound** sshd host key (identifies the container to the operator; persisted for stable identity) versus the **outbound** push key (this feature; secret, ephemeral) — explicitly separate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent in a freshly provisioned deployment can commit and push in 100% of cases with zero interactive prompts (no passphrase, no host-key confirmation).
- **SC-002**: An agent in a freshly provisioned deployment can perform a backend-requiring operation, confirming its model/API credential is in effect.
- **SC-003**: In an inspection of a running deployment, the number of secrets found in image layers, deployment descriptions, process command lines, or host persistent volumes is **zero**.
- **SC-004**: After a container is torn down, the number of private-key or API-credential copies remaining anywhere on the host is **zero** (operator's local copy is the sole durable copy).
- **SC-005**: Editing canonical configuration locally and redeploying reflects the change in the container in 100% of cases, while previously-written agent runtime state survives container recreation in 100% of cases.
- **SC-006**: Rotating a secret requires only a local edit plus a redeploy — no in-image or in-volume change — and the prior value is unrecoverable from the host afterward.
- **SC-007**: A deploy that references a missing secret/config fails before starting the agent in 100% of cases (no partially-credentialed agent runs).
- **SC-008**: The inbound host key and the outbound push key are never the same credential — verifiable as two distinct keys with distinct roles.

## Assumptions

- **Push credential is an SSH key** *(operator decision)*: the outbound push credential is an SSH key rather than an HTTPS token, matching the SSH-first design; default is a single user key, with per-repository deploy keys available as a narrower-scope option.
- **Config model is hybrid** *(operator decision)*: operator-canonical config is injected fresh each deploy (edits propagate); agent-written runtime state persists in per-agent storage. Because a single agent config tree can mix both, the split is expected to be applied at the level of specific files/paths rather than whole directories.
- **API-key delivery prefers files** *(operator decision)*: model/API credentials are delivered as runtime file-secrets and exported into the in-container environment only for agents that cannot read a file; exact per-agent capability (which agent reads a credential from a file vs. requires an environment variable vs. supports a stored authorization) is to be verified when planning and may force the environment fallback for specific agents.
- **Depends on / inherits Feature 001**: the delivery mechanism for injected material (secret/config transfer over the runtime context, runtime-injection-never-baked) is established by Feature 001 and reused here, not redefined.
- **Feeds Feature 004**: Feature 004 (agent execution) consumes the push credential (for clone-on-start and autonomous push) and the injected config; this feature provides them and does not run the agent.
- **Agents in scope**: the three baked agent CLIs (Claude Code, Codex, pi-coding-agent); this feature does not add or remove agents.
- **Single operator**: one operator owns all credentials; no multi-tenant credential management or shared secret stores are in scope (Constitution — Platform & Interface Constraints).
- **Provider/host tokens are out of scope here**: host-level provisioning credentials (e.g. the cloud provider API token) belong to Feature 001, not to per-container agent credentialing.
- **No secret manager dependency assumed**: secrets originate from the operator's local machine; integrating an external secret-manager service is not required by this feature (and would need justification against Constitution VI).
