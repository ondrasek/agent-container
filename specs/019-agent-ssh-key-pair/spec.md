# Feature Specification: The Agent SSH Key Pair Is Generated In the Container

**Feature Branch**: `019-agent-ssh-key-pair`

**Created**: 2026-08-15

**Status**: Draft

**Input**: Operator directive: *"When the agent needs outbound authentication via ssh, the workflow is
for me to get its public key via agent-container cli and register/push it wherever needed. The
private/host key is generated inside the container ONLY and never leaves it."*

## Terminology — and why the old name was wrong

**It is the agent's SSH key pair.** The container holds a keypair for outbound SSH authentication; the
**private half never leaves it**, and the **public half** is what the operator obtains and registers.

The existing code calls this a *"push key"* (`--push-key`, `push_key`, `INJECT_PUSH_KEY_PATH`, from
Feature 003). **That name is wrong and this feature does not carry it forward.** The key is wired to
git's `core.sshCommand`, which git uses for **every** SSH transport operation — `clone`, `fetch`,
`pull`, `ls-remote`, `push` — so it was never push-specific. The entrypoint's own clone path already
refers to *"an SSH URL with no push key configured"*, i.e. it clones with the thing it calls a push
key. Under FR-013's two-phase flow the first thing the key ever does is **clone**; it may never push
at all.

Nor is it git-specific. It is the agent's outbound SSH identity, and git is merely today's consumer.

The legacy names appear below **only** where this feature names what it removes.

## Overview

**Feature 018 established the principle for inbound identity. This applies it to outbound
authentication, which is the only place the tool still writes a private key to the operator's disk.**

Today `--push-key` takes the operator's own SSH private key, copies it to
`<state>/<host>/<name>.push_key` at mode **0644**, and delivers it into the container. Two
consequences, both established by reading the code:

1. **A plaintext private key persists on the operator's machine.** `clear_state` removes only
   `<name>.port`, so `down --purge` does not delete it — the same shape as the `.host_key` file
   Feature 018 has just removed, at the same mode, for the same measured reason (compose exposes the
   source file's mode, and `dev`'s uid need not match the host uid that ran `up`).
2. **The container gets whatever that key can reach.** Operators typically pass their personal push
   key, so a container that needs to push one repository receives credentials for everything that key
   authorises.

Inverting it fixes both at once: **the container generates its own agent SSH key pair, the operator obtains
the PUBLIC key through the CLI and registers it wherever the push must land** — a per-repository
deploy key, an account key, a mirror, anything. The private half is created in the container and never
leaves.

> **This is strictly narrower than what it replaces.** A per-container deploy key authorises one
> repository. That is not a side benefit — it is the point that makes the extra registration step
> worth paying for, and no amount of care with `--push-key` can achieve it.

### What this does NOT change

The HTTPS + `GH_TOKEN` path is untouched — this is the SSH remote. `--known-hosts` / `PUSH_KNOWN_HOSTS`
stay: those let the container verify **github.com**, which is the opposite direction and is public
data.

## Clarifications

### Session 2026-08-16 (later)

- Q: Is it the agent's SSH identity, or git's? → A: **The agent's — generated at
  `~/.ssh/id_ed25519`.** That is what the thing is, and it is also *less* code: git shells out to
  `ssh`, which picks up the conventional identity automatically, so `core.sshCommand` and its
  `PUSH_RUNTIME` scaffolding disappear entirely rather than being rewired. `IdentitiesOnly` and the
  pinned `UserKnownHostsFile` move to `~/.ssh/config` — the standard mechanism, same effect. The
  container's `ssh` volume is already mounted at `~/.ssh`, so FR-003's persistence requirement is met
  by the existing volume with no new path. Every outbound SSH the agent makes — git, `ssh`, `scp`,
  `rsync` — now uses one identity the operator has registered, rather than git alone having a
  credential nothing else can use.

### Session 2026-08-16

- Q: How is "already registered" established (FR-011)? → A: **Probe the forge from inside the
  container.** The operator's machine cannot answer — it holds no private key, which is the point of
  the feature. Running the probe where the key is has a second benefit: it inherits the same egress the
  push will, so a *not registered* answer is predictive rather than a guess about network conditions
  the agent will never face. It must fail **soft** — denied egress, offline or a forge outage yields
  *unknown* and never blocks a deploy. Not cached: registration lives on the forge and a stored answer
  goes stale the moment a key is revoked.
- Q: SSH clone-on-start needs a key before the container exists, and the container now makes its own.
  What happens? → A: **Two-phase — boot, register, redeploy.** `up` starts the container, generates
  the key, does **not** clone, and prints the key with the exact next command. This relaxes FR-014's
  empty-workspace refusal **for this case only**: that refusal exists so nobody receives a silently
  useless container, and here the container is *deliberately pending and says so*. Refusing SSH
  clone-on-start outright was rejected — it deletes a working capability, and `GH_TOKEN` is
  github.com-scoped, so operators on any other forge would have no path at all.

### Session 2026-08-15

- Q: Does the public/private argument from Feature 018 transfer directly? → A: **No, and the
  difference is the whole design.** For inbound identity the container proves itself *to us*, so we
  need only its public key. For outbound auth the container proves *our* identity *to a remote*, and
  signing requires possessing a private key. It cannot be eliminated — only **relocated** so it is
  born where it is used.
- Q: Where does the generated key live? → A: **On the persisted `ssh` volume**, alongside the host key.
  A key under `/run` would die with the container and force re-registration on every recreate, which
  makes the feature unusable.
- Q: But Feature 003 forbids exactly that. → A: **Yes, and this feature amends that rule rather than
  quietly breaking it.** The rule exists to stop *operator-supplied* secrets being copied somewhere
  they outlive the operator's control. A key the container generated itself and never exports has no
  such origin; the volume is its home, exactly as for the host key. **The amendment is scoped to
  self-generated material** — injected secrets stay ephemeral.
- Q: What happens before the key is registered? → A: **Pushes fail, and the tool must say so up
  front.** Commit-and-push is a hard constraint of this project, so an agent discovering this mid-run
  is unacceptable. The deploy surfaces the public key and states that pushing will not work until it
  is registered.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The container makes its own push key and I register its public half (Priority: P1)

The operator deploys, obtains the container's agent SSH **public** key through the CLI, registers it as a
deploy key (or wherever the push must land), and the agent pushes.

**Why this priority**: it is the feature. Everything else is consequence.

**Independent Test**: deploy, read the public key from the machine-readable interface, register it on a
repository, and confirm the agent can push while no private key exists on the operator's machine.

**Acceptance Scenarios**:

1. **Given** a newly created environment, **When** it starts, **Then** it has a agent SSH key pair it
   generated itself, and the private half exists only inside the container.
2. **Given** a running environment, **When** the operator asks for its agent SSH key, **Then** they get the
   **public** key in a form they can paste into a deploy-key field.
3. **Given** the public key is registered on the remote, **When** the agent pushes, **Then** the push
   succeeds using that key.
4. **Given** the environment is recreated (`down` then `up`), **When** the agent pushes, **Then** it
   still succeeds — the key persisted, so no re-registration was needed.

---

### User Story 2 - No agent SSH private key on the operator's disk (Priority: P1)

The tool neither takes, stores, stages nor injects an agent SSH private key.

**Why this priority**: P1 alongside US1 because it is the other half of the same change, and because it
removes an existing exposure rather than adding a capability.

**Independent Test**: create an environment by every path the tool offers, then confirm no file under
the operator's state or config directories contains private key material.

**Acceptance Scenarios**:

1. **Given** any environment created by any path, **When** the operator inspects the state directory,
   **Then** no agent SSH private key file exists.
2. **Given** an operator who uses a removed channel, **When** they run the command, **Then** it fails
   with a message explaining that the agent SSH key is generated in the container and its public half
   registered.
3. **Given** an upgrade from a version that staged one, **When** the operator next deploys, **Then**
   the stale private key file is removed and its removal is stated.

---

### User Story 3 - I am told what to register, before the agent needs it (Priority: P2)

The operator learns the public key and the fact that pushing is blocked until it is registered, at
deploy time rather than from a failed push.

**Why this priority**: not required for the mechanism to work, but without it the feature trades a
security win for a confusing failure — and this project's first constraint is that agents commit **and
push** every change.

**Independent Test**: deploy an environment whose repository is an SSH remote with the key
unregistered, and confirm the output names the key and the consequence.

**Acceptance Scenarios**:

1. **Given** a deploy of an environment that will push over SSH, **When** it completes, **Then** the
   output includes the public key and states that pushes fail until it is registered.
2. **Given** an environment whose key is already registered, **When** the operator deploys again,
   **Then** they are not nagged about registering a key that already works.

---

### Edge Cases

- **`down --purge`** destroys the volume, so the key is regenerated and the old registration becomes
  dead. The operator must be told, or pushes fail for a reason nothing announced.
- **Several environments pushing to one repository** each hold a different key, so each needs its own
  registration. Not a defect — it is per-container least privilege — but it must be stated.
- **A remote that permits only one deploy key** (a repository already using one) — the operator needs
  to know the constraint is the remote's, not the tool's.
- **An operator who cannot register a key at all** (a locked-down remote) — must be told plainly that
  the SSH push path is unavailable to them and that the HTTPS + token path exists.
- **Key generation fails** — must not fail the deploy silently into an environment that cannot push.
- **A pre-existing staged `.push_key`** from an older version — must be removed, and its removal
  stated.
- **The public key requested for an environment that is stopped or on an unreachable host** — the
  answer must not depend on reaching the container.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST NOT take, store, stage or inject an outbound SSH **private** key. The push
  keypair MUST be generated inside the container and the private half MUST NOT leave it.
- **FR-002**: **Every** channel that supplies a agent SSH private key MUST be removed: `up --push-key`,
  `redeploy --push-key`, the `SSH_PUSH_KEY_B64` env-file variable, and `target: push_key` in a
  project's `.agent-container/` spec. Using one MUST fail with a message explaining the replacement. A
  declared `push_key` MUST be **refused**, never ignored.
- **FR-003**: The generated key MUST persist across recreation, so a registered key keeps working
  without re-registration. **This amends Feature 003's rule that outbound key material never lands on a
  volume; the amendment is scoped to material the container generated itself.**
- **FR-004**: The operator MUST be able to obtain an environment's agent SSH **public** key through the
  existing machine-readable interface, in a form that can be registered directly.
- **FR-005**: Obtaining the public key MUST NOT depend on the environment's host being reachable — the
  answer comes from what the tool captured, or an explicit statement that none was captured.
- **FR-006**: A deploy of an environment that pushes over SSH MUST state the public key and that pushes
  fail until it is registered — unless it is already known to be registered (FR-011).
- **FR-007**: `down --purge` MUST warn that the agent SSH key will be regenerated and the existing
  registration will stop working.
- **FR-008**: Key generation failure MUST be surfaced and MUST NOT leave the operator believing the
  environment can push.
- **FR-009**: An upgrade MUST remove any agent SSH private key file staged by an earlier version, and MUST
  say that it did.
- **FR-010**: No agent SSH private key material may be written anywhere on the operator's machine by this
  feature (Constitution III).
- **FR-011**: The tool MUST NOT nag about registering a key on every deploy once pushing demonstrably
  works. Registration MUST be established by **probing the forge from inside the container** — the
  operator's machine holds no private key and so cannot answer the question. The probe MUST **fail
  soft**: a forge that cannot be reached yields *unknown*, never *not registered*, and MUST NOT block
  or fail the deploy. Registration MUST NOT be cached: it lives on the forge, and a stored "registered"
  goes stale the moment the operator revokes the key.
- **FR-012**: The HTTPS + token push path and the outbound `known_hosts` channel (which verifies the
  **remote**, not the container) MUST be unaffected.
- **FR-013**: Clone-on-start over an **SSH** URL MUST become two-phase: the container starts, generates
  its key, does **not** clone, and states the key and the next command. This relaxes FR-014's
  empty-workspace refusal for **this case only** — the container is deliberately pending and says so,
  which serves that refusal's intent rather than defeating it. HTTPS clone-on-start is unchanged.

### Key Entities *(include if feature involves data)*

- **Container push identity**: the keypair the container generates for outbound authentication. The
  private half lives only on the container's persisted volume; the public half is what the operator
  registers.
- **Captured agent SSH public key**: the tool's local copy of that public key, used to answer FR-004
  without reaching the container.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No file on the operator's machine contains agent SSH private key material after any deployment
  path — **100%**.
- **SC-002**: A registered public key lets the agent push successfully — verified with a real push, not
  inferred from configuration.
- **SC-003**: A recreated environment (`down` then `up`) pushes without re-registration — **zero**
  re-registrations required.
- **SC-004**: The public key obtained through the CLI is accepted verbatim by a deploy-key field —
  **zero** manual reformatting.
- **SC-005**: A deploy that will push over SSH with an unregistered key states the consequence —
  **zero** silent setups that fail at first push.
- **SC-006**: Obtaining the public key succeeds for a stopped environment and for an unreachable host —
  **100%**.
- **SC-007**: Every removed channel fails with an explanatory message — **zero** bare
  unrecognised-argument errors.
- **SC-008**: A container's push key authorises only what the operator registered it for — verified by
  confirming a second repository is **not** reachable with it.

## Assumptions

- **Outbound authentication genuinely requires a private key in the container.** Unlike inbound
  identity (Feature 018), it cannot be reduced to a public key — only relocated to where it is used.
- **The operator can register a public key** on the remote they push to. Where they cannot, the HTTPS +
  token path remains.
- **Registration is a one-time manual step per environment**, and automating it (calling a provider's
  API) is out of scope — it would require provider credentials with rights to manage keys, which is a
  larger grant than the thing being replaced.
- **The `ssh` volume is the container's own storage**, not the operator's disk; material generated
  there and never exported is not an exposure of the kind Constitution III addresses.
- **Removing documented interfaces is a breaking change** and is treated as one.

## Out of Scope

- Automating key registration with any provider's API.
- Changing the HTTPS + `GH_TOKEN` push path.
- The outbound `known_hosts` for the push remote (Feature 003) — it verifies the remote, is public
  data, and is unaffected.
- Rotating or expiring the generated key on a schedule.
- Sharing one push identity across several containers — the per-container key is the point.

## Dependencies

- **Feature 003 (credentialing)**: owns `--push-key` and the "never on a volume" rule this feature
  amends for self-generated material.
- **Feature 018 (attach host verification)**: the precedent, the argument, and the mechanism — reading
  a public key out of a container through the runtime already exists.
- **Feature 009 (agent-operable CLI)**: FR-004's machine-readable exposure.
- **Constitution III (least exposure)**: FR-001 and FR-010 — this feature *removes* an exposure and
  narrows a grant.
- **Constitution VII (continuous deployment)**: FR-002 is breaking.
