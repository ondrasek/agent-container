# Feature Specification: Verified Attach, Without a Private Host Key on Disk

**Feature Branch**: `018-attach-host-verification`

**Created**: 2026-08-14

**Status**: Draft

**Input**: Operator observation: "Why would we pre-generate a host private key? We need to capture the
host public key for injection elsewhere, but that's it." — and, on verification: "it verifies using
the public key, not the private key material."

## Overview

**`attach` does not verify what it connects to, and the tool holds a private key that buys nothing.**

Two facts about today's behaviour, both established by reading the code:

1. The attach command is plain `ssh dev@<host> -p <port> -t tmux attach`. There is no
   `StrictHostKeyChecking`, no tool-managed `known_hosts`, no pinning. Whether the container you
   reach is the container you created rests on the operator's ordinary trust-on-first-use.
2. `--host-key` lets an operator supply a **private** SSH host key, which is staged on the operator's
   machine as `<state>/<host>/<name>.host_key` at mode **0644**, survives `--purge`, and is injected
   into the container. Because nothing verifies against it, its only realised effect is that a
   recreated container keeps its identity so `known_hosts` does not complain.

So the tool carries the cost of a plaintext private key on disk and gets no verification in return.

**SSH host verification needs only the public key.** The server proves possession of its private key
by signing during the handshake; the client checks that signature against the public key in
`known_hosts`. The private material never needs to leave the container — and the container already
generates its own host key, as `dev`, on the persisted `ssh` volume.

This feature closes the loop the cheap way: **capture the public key over the runtime, pin it, and
delete the private-key injection.**

> **The channel is the whole security argument.** The public key must be read through the container
> runtime — a channel the operator already controls and already trusts to create containers. Reading
> it with `ssh-keyscan` would mean asking the connection you are trying to authenticate to state its
> own identity, which is trust-on-first-use wearing a hat.

## Clarifications

### Session 2026-08-14

- Q: Does client-side verification need the private host key? → A: **No.** `known_hosts` holds public
  keys only. The server signs during the handshake and the client verifies that signature. Injecting
  a private key therefore buys exactly one thing: knowing the public key *before the container
  exists*.
- Q: Is that foreknowledge worth keeping? → A: **No.** It would matter only for distributing
  `known_hosts` to a machine that will never talk to the container's daemon. This tool assumes a
  single operator, and capture-after-start covers that operator's own machines. The residual case is
  hypothetical, and the way to serve it would be to generate a keypair and inject the private key —
  i.e. reinstate exactly what is being removed.
- Q: Where does the public key come from? → A: **Through the container runtime**, not `ssh-keyscan`.
  The operator already controls that daemon, so it is an independent authenticated channel; keyscan
  asks the untrusted party.
- Q: What happens to `--host-key`? → A: **Removed**, as a breaking change. It delivers no verified
  benefit and its cost is a private key at 0644 on the operator's disk that `--purge` does not remove.
- Q: Does capturing the key at attach time verify anything? → A: **No, and this is the load-bearing
  distinction.** A pin is a witness, and its value comes entirely from being **older than the thing it
  checks**. At deploy time the tool knows the container is the one it just created; at attach time the
  runtime can only say *"the container currently called X"*, never *"the container you created"*. So an
  attacker who replaced the container would have their own key captured and then verified against
  themselves. Capture-at-use is trust-on-first-use through a different door — and the attacker who
  replaced the container owns what is behind that door too.
- Q: So what happens when nothing is pinned? → A: **Warn, say what accepting cannot detect, and ask.**
  Capture on an explicit yes. It is a trust decision the operator makes knowingly — not a verification
  the tool performs and not something it does silently. Refusing outright was rejected: the only
  re-pin path would be `redeploy`, which `--force-recreate`s the container and kills the operator's
  running agent, so a deleted cache file would cost a working session.
- Q: Does a **mismatch** ever prompt? → A: **Never.** Absent and changed are different situations with
  different answers: absent has no prior claim to contradict, a mismatch contradicts one the tool
  made itself. Turning a mismatch into a prompt would delete the feature.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Attach verifies what it connects to (Priority: P1)

When the operator attaches, ssh verifies the container's host identity against a key the tool
captured over the runtime. A changed identity is refused, not silently accepted.

**Why this priority**: it is the security property the feature exists to add. Everything else is
consequence.

**Independent Test**: attach to a fresh environment (succeeds, verified), then replace the
container's host key and attach again (refused, and the message says why).

**Acceptance Scenarios**:

1. **Given** a newly created environment, **When** the operator attaches, **Then** the connection is
   verified against a captured key and no trust-on-first-use prompt appears.
2. **Given** an environment whose host key has changed, **When** the operator attaches, **Then** the
   connection is **refused** with a message naming the mismatch.
3. **Given** no key is pinned for the environment, **When** the operator attaches, **Then** the tool
   **warns that it cannot verify what it is about to connect to, states what accepting does not
   detect, and asks** — capturing and pinning only on an explicit yes, and refusing on a no.
4. **Given** a recreated environment with a legitimately new host key, **When** the operator
   attaches, **Then** the tool recognises its own recreation and re-pins rather than presenting a
   scary mismatch it caused itself.

---

### User Story 2 - No private host key on the operator's disk (Priority: P1)

The tool neither generates, stores, stages nor injects a private SSH host key. The container's host
key is created inside the container and never leaves it.

**Why this priority**: P1 alongside US1 because it is the other half of the same change, and because
it removes an existing exposure rather than adding a feature.

**Independent Test**: create an environment with every flag the tool offers, then confirm no file
anywhere under the operator's state or config directories contains private key material.

**Acceptance Scenarios**:

1. **Given** any environment created by any path, **When** the operator inspects the state directory,
   **Then** no private host key file exists.
2. **Given** an operator who passes the removed `--host-key` flag, **When** they run the command,
   **Then** it fails with a message explaining that host identity is now captured, not supplied.
3. **Given** an upgrade from a version that staged one, **When** the operator next deploys, **Then**
   the stale private key file is removed rather than left behind.

---

### User Story 3 - The captured key is available for use elsewhere (Priority: P3)

The operator can obtain a container's host public key in a form suitable for a `known_hosts` entry,
so it can be placed on another machine or in a configuration they manage.

**Why this priority**: the operator's stated reason for capture — *"we need to capture the host public
key for injection elsewhere"* — but it is additive, and US1 already pins for the local case.

**And it is the only non-TOFU answer for a second machine.** An entry copied from the machine that
deployed descends from the deploy, so it predates what it checks; a fresh capture on the second machine
does not. That makes US3 the *preferred* path whenever FR-013's prompt would otherwise appear — a
detail worth stating, because the prompt is easier and weaker.

**Independent Test**: obtain the entry for a running environment and confirm a second client using
only that entry connects verified.

**Acceptance Scenarios**:

1. **Given** a running environment, **When** the operator asks for its host key, **Then** they get a
   `known_hosts`-format line for it.
2. **Given** a stopped environment, **When** the operator asks, **Then** the answer is the captured
   key or a clear statement that none was captured — never a silent empty result.

---

### Edge Cases

- **The container has not generated its key yet** (captured too early) — must retry or report, never
  pin an empty value.
- **`--purge` then recreate** — the host key legitimately changes; the tool caused it, so it must
  re-pin rather than warn about a mismatch of its own making.
- **Two environments on one host** share an address and differ only by port — the pinned entry must
  distinguish them, or one container's key verifies another's connection.
- **A remote host** — capture must work over a remote context, where the operator's machine shares no
  filesystem with the daemon.
- **The operator's own `~/.ssh/known_hosts` already has a conflicting entry** for that address and
  port — the tool must not silently rewrite the operator's file.
- **Capture fails** (daemon unreachable mid-`up`) — must not fail the deploy, but must not silently
  leave attach unverified either.
- **Nothing pinned, and no terminal to ask** (a script, a pipe, an agent-driven invocation) — must
  refuse rather than assume yes.
- **Nothing pinned because the operator is on a second machine** — the prompt is the fallback, not the
  intended path: US3 gives them the entry from the machine that deployed, and that pin has real
  provenance where a fresh capture does not.
- **A pinned entry the operator wants to inspect before answering** — the prompt must show a
  fingerprint, or there is nothing to compare it against and the question is theatre.
- **An operator who genuinely wants foreknowledge** of the identity — must be told plainly that it is
  no longer supported and why.
- **A pre-existing staged private key** from an older version — must be removed, and its removal
  stated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST NOT generate, store, stage or inject a private SSH host key. The
  container's host key MUST be created inside the container and MUST NOT leave it.
- **FR-002**: `--host-key` MUST be removed. Passing it MUST fail with a message stating that host
  identity is captured rather than supplied, and why.
- **FR-003**: On deploy the tool MUST capture the container's host **public** key **through the
  container runtime**, not by querying the SSH endpoint. Reading it from the endpoint being
  authenticated is not verification.
- **FR-004**: `attach` MUST verify the connection against the captured key, and MUST refuse a
  mismatch rather than prompting or accepting.
- **FR-005**: The pinned entry MUST distinguish environments that share an address and differ by
  port. Two containers on one host must not verify each other's connections.
- **FR-006**: The tool MUST NOT modify the operator's own `~/.ssh/known_hosts`. It MUST manage its own
  file.
- **FR-007**: When the tool itself caused the identity to change (recreation after `--purge`), it MUST
  re-pin without presenting a mismatch warning it caused. When it did **not** cause the change, it
  MUST refuse (FR-004).
- **FR-008**: A capture failure MUST NOT fail the deploy, MUST be surfaced, and MUST NOT leave
  `attach` silently unverified — an unverified attach must say so.
- **FR-009**: Capture MUST work over a **remote** context, where the operator's machine shares no
  filesystem with the daemon.
- **FR-010**: The operator MUST be able to obtain a captured key as a `known_hosts`-format line
  (US3), through the existing machine-readable interface.
- **FR-011**: An upgrade MUST remove any private host key file staged by an earlier version, and MUST
  say that it did.
- **FR-012**: No private key material may be written anywhere on the operator's machine by this
  feature (Constitution III).
- **FR-013**: When **no key is pinned** for an environment, `attach` MUST warn, MUST state that
  accepting is a trust decision that **cannot detect a container that was replaced**, and MUST ask
  before proceeding. On an explicit yes it captures (FR-003) and pins; on a no it refuses. It MUST NOT
  capture silently, and MUST NOT present this as verification.
- **FR-014**: A **mismatch** MUST NOT prompt, ever (FR-004). Absent and changed are different
  situations: absent has no prior claim to contradict; a mismatch contradicts one the tool made itself.
- **FR-015**: Where no answer can be obtained — no terminal, or a non-interactive invocation — the
  tool MUST refuse rather than assume yes. An operator MAY pre-accept explicitly on the command line,
  which MUST be as loud in the output as the prompt would have been.
- **FR-016**: The prompt MUST show the key's fingerprint, so the operator can compare it against
  another source before answering. A prompt with nothing to compare is a formality.
- **FR-017**: `attach --print` and `--ssh-config` MUST NOT prompt — they emit a command and connect to
  nothing. When no key is pinned they MUST say so, and say that the emitted command will refuse.

### Key Entities *(include if feature involves data)*

- **Captured host identity**: the container's host public key, the address and port it answers on, and
  when it was captured.
- **Tool-managed `known_hosts`**: the file `attach` verifies against, owned by the tool and never the
  operator's own.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No file on the operator's machine contains private host key material after any
  deployment path — **100%**.
- **SC-002**: `attach` to an unmodified environment is verified, with **zero** trust-on-first-use
  prompts.
- **SC-003**: `attach` to an environment whose host key changed **without** the tool's involvement is
  **refused** — **zero** silent acceptances.
- **SC-004**: `attach` after a tool-caused recreation succeeds without a mismatch warning — **zero**
  false alarms.
- **SC-005**: Two environments on one host never verify each other's connections — **zero**
  cross-verifications.
- **SC-006**: Capture succeeds against a **remote** context — verified, not assumed from a local run.
- **SC-007**: The operator's own `~/.ssh/known_hosts` is byte-identical before and after any tool
  operation — **100%**.
- **SC-008**: A capture failure leaves a deploy successful and an explicit statement that attach is
  unverified — **zero** silently unverified attaches.
- **SC-009**: An unpinned environment never connects without an explicit answer — **zero** silent
  captures, and **zero** captures presented as verification.
- **SC-010**: A mismatch is refused without a prompt in **100%** of cases, whether or not a terminal is
  present.
- **SC-011**: A non-interactive `attach` against an unpinned environment refuses — **zero** assumed
  yeses.

## Assumptions

- **Verification needs only the public key.** The server signs during the handshake; the client checks
  that signature. This is why the private key can stay in the container.
- **The runtime is a trusted channel.** The operator already controls the daemon that creates
  containers, so reading the public key through it is independent of the connection being
  authenticated. `ssh-keyscan` is not, and is therefore not an acceptable source.
- **In-container generation already works.** The entrypoint creates the host key as `dev` on the
  persisted `ssh` volume, so identity is already stable across `down`/`up`. This feature adds capture
  and pinning, not generation.
- **Foreknowledge of identity is not needed.** It would matter only for a machine that never talks to
  the daemon; a single-operator tool does not have that case, and serving it would mean reinstating
  private-key injection.
- **Removing a flag is a breaking change** and is treated as one (Constitution VII).

## Out of Scope

- Changing how the container generates its host key.
- Managing the operator's own `~/.ssh/known_hosts`.
- Verifying anything other than the container's SSH host identity — the outbound push credential and
  its `known_hosts` (Feature 003) are a different direction and unaffected.
- Certificate authorities or signed host certificates.
- Distributing captured keys between operator machines.

## Dependencies

- **Feature 002 (lifecycle)**: `attach`, and the deploy paths where capture must hook.
- **Feature 003 (credentialing)**: the outbound push key and its `known_hosts` — the *opposite*
  direction, and the precedent that ephemeral secrets live under `/run` rather than on a volume.
- **Feature 009 (agent-operable CLI)**: FR-010's machine-readable exposure.
- **Feature 011 (filesystem layout)**: where the tool-managed `known_hosts` lives.
- **Feature 016 (run observability)**: the removal of the staged key file interacts with `--purge`'s
  cleanup, which 016 touched.
- **Constitution III (least exposure)**: FR-001 and FR-012 — this feature *removes* an exposure.
- **Constitution VII (continuous deployment)**: FR-002 is breaking.
