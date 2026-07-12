# Feature Specification: Agent-as-Code (declarative project directory)

**Feature Branch**: `006-agent-as-code`

**Created**: 2026-07-12

**Status**: Draft

**Input**: User description: "The tool will become the agent-as-a-code tool. I.e. when run in a (optionally git-tracked) folder, it will treat that folder and it's subfolders as the specification code for the agent. I.e. YAML files specifying the agent, .env files, stored credentials (how?), anything needed to configure the host, docker, agent, ssh keys, etc."

## Overview

Today the tool is driven by imperative commands and a machine-global registry (`hosts.json`): the operator types `host add …`, `up --host …`, `keys …`, and the tool mutates machine-wide state. This feature adds a second, **declarative** way to drive the same lifecycle: a **project directory** whose files *are* the specification for one or more agents — the host they run on, the container(s), the agent configuration, the SSH identity, and the credentials they need. Run the tool inside such a directory and it reads the desired state from the files and makes reality match, rather than being told each step.

This is the "as code" model familiar from Compose/Terraform/Pulumi projects: the directory is the single, portable, reviewable, version-controllable source of truth. A directory can be committed to git so that a whole agent environment is reproducible from a checkout — but git is optional; a plain directory works too.

The declarative model is **additive**: it does not remove the imperative CLI or the global registry. When no project spec is present, the tool behaves exactly as it does today. When a project spec *is* present, it becomes the source of truth for that invocation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Declare an agent environment in a folder and bring it up (Priority: P1)

An operator creates a directory, writes one or more declarative configuration files describing an agent environment — which host to run on (an already-known host), the container(s) to run, and the agent configuration — then runs the tool inside that directory. The tool discovers the spec, validates it, shows what it will do, and on confirmation brings the declared environment up. Re-running the same command against an already-satisfied spec makes no changes.

**Why this priority**: This is the core of the feature — a folder as desired state, reconciled to a running environment. Without it there is no "as code" model. It delivers the headline value (reproducible, reviewable, portable agent environments) on its own, assuming a host already exists.

**Independent Test**: In a scratch directory containing a minimal valid spec that targets an existing local host, run the up/apply command; verify the declared container is running with the declared configuration, and that an immediate second run reports "no changes".

**Acceptance Scenarios**:

1. **Given** a directory with a valid spec targeting a known host, **When** the operator runs the apply command inside it, **Then** the tool discovers the spec, presents the planned changes, and on confirmation the declared container is running.
2. **Given** an environment already matching its spec, **When** the operator re-runs apply, **Then** the tool reports no changes and mutates nothing (idempotent).
3. **Given** a directory with a syntactically or semantically invalid spec, **When** the operator runs any command, **Then** the tool refuses to act and reports which file and which field is wrong, with no partial changes.
4. **Given** a directory with **no** spec present, **When** the operator runs a command, **Then** the tool falls back to today's global-registry behavior (the declarative model is inert).

---

### User Story 2 - Declare the credentials an environment needs, safely (Priority: P2)

The spec must be able to say *which* credentials the environment needs — API keys for the agents, the git push identity, the SSH keys for host access — without forcing plaintext secrets to live in the (potentially committed) directory. The operator declares each credential by **reference to a source** (an environment variable, an OS keychain entry, an external file, or an encrypted-at-rest file that may be safely committed). At apply time the tool resolves each reference and injects the secret into the target at runtime; it never bakes a secret into an image and never writes a resolved secret back into the tracked directory.

**Why this priority**: The user explicitly flagged "stored credentials (how?)" as the open question. It is second only to the core reconcile loop because an agent environment is useless without its keys, but the environment can be demonstrated with reference-only (env/keychain) credentials before encrypted-at-rest storage exists. Getting the security model right is load-bearing (Least Exposure).

**Independent Test**: In a directory whose spec references an API key via an environment variable and a git identity via an external SSH key path, run apply; verify the running container receives the secret at runtime, verify no plaintext secret value appears anywhere in the directory, and verify a spec that would commit a plaintext secret is rejected.

**Acceptance Scenarios**:

1. **Given** a spec that references a secret by an environment-variable name, **When** the referenced variable is set and the operator applies, **Then** the secret is injected into the running target and its value never appears in the directory, in command arguments, or in logs.
2. **Given** a spec that references a secret whose source is unavailable (unset variable, missing file, locked keychain), **When** the operator applies, **Then** the tool fails before making changes and names the missing source.
3. **Given** a directory tracked by git containing a **plaintext** secret file, **When** the operator runs any command, **Then** the tool refuses to proceed and tells the operator the file is a leak risk and how to remedy it (ignore, externalize, or encrypt).
4. **Given** a spec that references an **encrypted-at-rest** secret file plus a decryption key held outside the directory, **When** the operator applies, **Then** the tool decrypts in memory, injects at runtime, and never writes the plaintext to disk in the directory.

---

### User Story 3 - See drift, converge, and tear down from the spec (Priority: P3)

Because the directory is desired state, the operator can ask how reality differs from it and converge safely. A status/diff command reports, per declared resource, whether it is absent, present-and-matching, or present-but-drifted (and how). Apply converges toward the spec. A down/destroy command removes exactly the resources the spec declares, and nothing it does not own.

**Why this priority**: Drift visibility and safe teardown make the model trustworthy for repeated use, but the MVP (US1) is demonstrable without them. This is the layer that turns "run once" into "operate over time".

**Independent Test**: Bring an environment up from a spec; out-of-band change the running container; run the status/diff command and verify the drift is reported; run apply and verify convergence; run down and verify only the declared resources are removed.

**Acceptance Scenarios**:

1. **Given** an applied environment that has since drifted, **When** the operator runs status/diff, **Then** each declared resource is reported as matching or drifted with a human-readable delta.
2. **Given** a drifted environment, **When** the operator applies, **Then** the tool converges reality to the spec and reports what it changed.
3. **Given** an applied environment, **When** the operator runs down, **Then** exactly the resources the spec declares are removed and unrelated containers/hosts on the machine are untouched.

---

### User Story 4 - Declare the host/provisioning in the spec too (Priority: P3)

The spec can declare not only the container and agent but the **target host** — either an existing runtime context or a host to be provisioned (e.g., a cloud server) — so that a single directory captures the entire stack from bare host to running agent. Applying such a spec provisions/registers the host as needed before deploying onto it; tearing it down can deprovision a host the spec created.

**Why this priority**: This unifies host provisioning (Feature 001) under the declarative model and is the most complete expression of "as code", but it depends on US1 being in place and reuses existing provisioning capability, so it is last.

**Independent Test**: With a spec that declares a to-be-provisioned host and a container on it, apply and verify the host is provisioned/registered and the container deployed; down and verify the host the spec created is deprovisioned, while a host the spec merely *referenced* (did not create) is left intact.

**Acceptance Scenarios**:

1. **Given** a spec declaring an existing host context, **When** applied, **Then** the container is deployed onto that host and the host itself is treated as externally owned (never deprovisioned by down).
2. **Given** a spec declaring a host to be provisioned, **When** applied, **Then** the host is provisioned/registered first and the container deployed onto it.
3. **Given** an applied spec that provisioned its own host, **When** the operator runs down with the deprovision intent, **Then** the tool removes the containers and then the host it created, and reports the outcome.

---

### Edge Cases

- **Spec discovery ambiguity**: the tool is run in a subdirectory of a project. It MUST resolve the same project root deterministically regardless of which subdirectory it is run from (walk upward to a project-root marker or the git root), and report which root it selected.
- **Multiple specs / no spec**: a directory tree containing more than one project root, or none, MUST resolve to a single unambiguous answer or a clear error — never a silent guess.
- **Partial apply failure**: if apply fails midway (e.g., host reachable but container fails to start), the tool MUST report exactly what was and was not changed; it MUST NOT leave the operator unable to tell current state.
- **Spec vs. global registry conflict**: a project spec names a host that also exists in the global registry with different settings. Precedence MUST be defined and reported, not silently merged.
- **Secret source changes between plan and apply**: a referenced secret becomes unavailable after the plan is shown but before apply completes — the tool MUST fail safe rather than deploy a half-credentialed environment.
- **Committed-plaintext detection false-negative risk**: a plaintext secret placed in a directory the tool does not scan. The tool MUST document the boundary of what it can and cannot detect rather than imply a guarantee.
- **Drift in a field the tool cannot change in place**: some drift may require recreate rather than update; the tool MUST say so before doing it.

## Requirements *(mandatory)*

### Functional Requirements

**Discovery & model**

- **FR-001**: The tool MUST, when run inside a directory, discover a project specification composed of one or more declarative configuration files in that directory and its subdirectories, resolving a single deterministic project root regardless of the working subdirectory.
- **FR-002**: The tool MUST treat the discovered specification as the **desired state** for one or more agent environments (host binding, container(s), agent configuration, SSH identity, and credential references).
- **FR-003**: The tool MUST validate the specification before taking any action and, on any error, refuse to act and report the offending file and field with no partial changes.
- **FR-004**: When no project specification is present, the tool MUST behave exactly as it does today (imperative CLI over the global registry); the declarative model MUST be additive, not a replacement.
- **FR-005**: The specification MUST be self-contained and portable: a fresh checkout of the directory on another machine, given the same external secret sources, MUST describe the same desired environment.

**Reconcile lifecycle**

- **FR-006**: The tool MUST provide an apply operation that converges the actual environment toward the specification, and this operation MUST be idempotent — applying an already-satisfied spec makes and reports no changes.
- **FR-007**: The tool MUST present the planned changes (a preview/plan) before mutating anything, and honor the existing headless/non-interactive conventions for confirmation.
- **FR-008**: The tool MUST provide a status/diff operation that reports, per declared resource, whether it is absent, matching, or drifted, with a human-readable delta.
- **FR-009**: The tool MUST provide a down/destroy operation that removes exactly the resources the specification declares and owns, and MUST NOT remove resources it does not own.
- **FR-010**: On partial failure of any operation, the tool MUST report precisely what changed and what did not, leaving no ambiguity about current state.

**Credentials (the "how")**

- **FR-011**: The specification MUST be able to declare each required credential (agent API keys, git push identity, host SSH keys) by **reference to a source** rather than by embedding its value.
- **FR-012**: The tool MUST support at least these credential sources: an environment variable, an external file outside the tracked directory, and an OS keychain/secret-store entry; and MUST support an **encrypted-at-rest** file that may be safely committed, decrypted only at apply time with a key held outside the directory.
- **FR-013**: The tool MUST resolve each credential reference at apply time and inject the secret into its target **at runtime**, never baking a secret into an image and never passing it on a command line where other processes could observe it.
- **FR-014**: The tool MUST NOT write a resolved plaintext secret value back into the tracked directory, into logs, or into the global registry at any point.
- **FR-015**: The tool MUST refuse to proceed when it detects a plaintext secret that is tracked by git within the project, and MUST tell the operator how to remedy it (ignore, externalize, or encrypt); it MUST also document the boundary of what it can and cannot detect.
- **FR-016**: When a referenced credential source is unavailable, the tool MUST fail before making changes and name the missing source.

**Host & precedence**

- **FR-017**: The specification MUST be able to bind an environment to a host, either an existing runtime context or a host to be provisioned; a host the spec merely references MUST be treated as externally owned and never deprovisioned, while a host the spec provisioned MAY be deprovisioned on teardown when the operator intends it.
- **FR-018**: When a project spec and the global registry describe the same-named host with different settings, the tool MUST apply a defined precedence and report which source won; it MUST NOT silently merge conflicting definitions.
- **FR-019**: The tool MUST report which project root and which host it selected for every operation, so the operator is never guessing which spec is in effect.

### Key Entities *(include if feature involves data)*

- **Project specification**: the directory tree, rooted at a deterministically discovered marker, whose declarative files collectively define the desired agent environment(s). Portable and optionally git-tracked.
- **Environment (declared)**: one desired agent setup within the spec — its host binding, container(s), agent configuration, SSH identity, and credential references. The unit of apply/status/down.
- **Credential reference**: a named requirement for a secret plus a *source* descriptor (environment variable / external file / keychain / encrypted-at-rest file) — never the secret value itself.
- **Plan/diff**: the computed delta between desired state (spec) and actual state (running containers/registered hosts), per declared resource, presented before mutation.
- **Host binding**: the spec's link to a target host — referenced (externally owned) or provisioned (spec-owned) — reusing the existing host/provisioner model.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can take a directory containing only a spec and the required external secret sources, run a single apply, and reach a running declared agent environment without issuing any other command.
- **SC-002**: Applying an already-satisfied specification makes zero changes and reports "no changes" in 100% of runs (idempotence).
- **SC-003**: A fresh checkout of a committed spec on a second machine, given the same external secret sources, produces an equivalent environment — verifiable by identical status/diff output.
- **SC-004**: No plaintext secret value ever appears in the tracked directory, in logs, or in command arguments across any operation — verifiable by inspection of the directory and captured output after a full apply.
- **SC-005**: When a spec would commit a plaintext secret, or a referenced secret source is missing, the tool refuses before making any change 100% of the time and names the exact problem.
- **SC-006**: For any operation, the operator can determine from the tool's output alone which project root and host were used and exactly what changed — no silent or ambiguous actions.
- **SC-007**: A down/destroy removes only the resources the spec declares; unrelated containers and referenced (non-spec-owned) hosts are untouched in 100% of runs.

## Assumptions

- **Additive, not a rewrite**: the existing imperative CLI (Features 001–005) and the global `hosts.json` registry remain; this feature layers a declarative source-of-truth model on top and reuses the existing host, container, credentialing, and provisioning capabilities rather than replacing them.
- **Reconciliation model**: "as code" implies desired-state convergence — apply is idempotent, drift is detectable, and teardown is scoped to spec-owned resources. This is assumed rather than a one-shot imperative generator.
- **Declarative file format**: human-readable declarative configuration files (YAML, as the user indicated) define the spec; a conventional project-root marker makes discovery deterministic. The exact schema is a planning/design concern, not fixed by this spec.
- **git optional**: the directory may be git-tracked (enabling the committed-plaintext safety check and reproducible checkouts) but git is not required for the declarative model to function.
- **Single operator**: consistent with the constitution, one operator is assumed; no multi-tenant spec ownership or access control.
- **Precedence default (pending confirmation)**: absent other direction, a present project spec is authoritative for its scope for the invocation that runs inside it, overriding a same-named global-registry host, with the override reported.
- **Credential model (see Question 1)**: the recommended default is *references + encrypted-at-rest + gitignored-plaintext-escape-hatch*, so that no plaintext secret is required to live in a committed directory, but the operator can still version encrypted secrets alongside the spec. This is the one decision with material security and scope impact and is raised as a clarification.

## Dependencies

- Builds on **Feature 001** (multi-host deployment, host registry, driver seam, Hetzner provisioner) for host binding and provisioning.
- Builds on **Feature 003** (agent credentialing) for the runtime-injection model that credential references resolve into.
- Relates to **Feature 005** (shell integration / env-configurator, future IaC drivers) — the declarative directory is the natural source for those drivers to consume.
