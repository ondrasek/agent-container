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

### Session 2026-07-30

- Q: What happens when a stop-everything action is invoked from inside the control plane? → A:
  **It refuses to act on itself, excludes itself from the run, and says so.** The control plane is
  the one container whose stopping makes the report undeliverable, so acting on itself is the only
  case where FR-010's "never leave the outcome unknown" cannot be honoured. Excluding itself
  guarantees it; the operator stops it from their own machine or from another control plane.
- Q: Same image as agent containers, or narrower? → A: **Narrower** — the CLI, ssh, tmux and git,
  with **no agent CLIs**. This is the one container holding keys to everything, so carrying less
  worth stealing matters more here than anywhere else, and it makes "no agents in the control
  plane" a property rather than a documented rule. Accepted cost: a second image to build, version
  and stamp.
- Q: What if the operator loses the passphrase? → A: **No recovery — redeploy and re-authorise.**
  The passphrase is the only thing protecting a key that can reach everything, so a recovery path
  would by definition be a way to obtain that key without it. Redeploying mints a fresh keypair;
  the operator authorises the new public key and withdraws the old, which is the revocation flow
  FR-008 already requires.

### Session 2026-08-18

- Q: FR-003a settles push-vs-pull, but pulls the inventory from **where**? Feature 014's inventory
  is a durable file on the operator's machine, which a container on a VPS cannot read.
  → A: **It queries the permitted hosts live on connect; the live view IS its truth.** No new
  channel is needed — the control plane's key already grants exactly the daemon access required —
  and syncing the operator's file would need a laptop→container path that FR-003a rules out and a
  locked control plane could not receive anyway. **Consequence accepted:** the control plane cannot
  show an environment whose host is unreachable or gone, which the laptop's durable inventory can.
  SC-002 narrows accordingly rather than pretending the two views are identical.
- Q: Nested control planes were listed as "prevented or deliberately supported, not accidental" —
  which? → A: **Deliberately supported, unconstrained.** A control plane is just another
  environment, so it may deploy one. The edge case demanded a DECISION rather than a particular
  answer, and recording it here is what makes nesting deliberate instead of accidental.
  **Why this is safer than it first looks:** FR-007b already requires authorising a public key to be
  an explicit act, never implicit in deployment — so a nested control plane starts with **zero
  reach**. Deploying one is not granting it anything; someone with existing access must still
  authorise its key. What nesting adds is the ability to MINT a standing key from inside a control
  plane, which is why FR-014a requires it to be visible as such.
- Q: FR-016 said a version-mismatched control plane "MUST behave predictably" — which is
  unfalsifiable. What does it do, and is the comparison semver-aware? → A: **Semver precedence, and
  the asymmetric case is refused.** `major_on_zero = false`, so **pre-1.0 a breaking change lands as
  MINOR** — that is the channel that matters, and PATCH differences (plus post-1.0 minor) are
  ignored entirely, not even warned about. A breaking-channel difference is **advisory** when the
  control plane is NEWER (the normal state after any upgrade) and **REFUSED** when the environment
  is newer than the control plane, which is where interfaces it does not know about may exist.
  Unreadable version on either side ⇒ **unknown**, never assumed compatible.
  Comparing by precedence rather than equality is what makes this usable: an equality check would
  fire on every patch bump and become noise, and a warning nobody reads is the failure mode
  Feature 013's severity split exists to avoid. (013's own `image-freshness` DOES use equality,
  deliberately — "was this image built by exactly this CLI" is a different question from "can these
  two versions interoperate".)
- Q: Are actions attributable to the control plane that performed them, and does that include
  reads? → A: **Yes, both — written where the action lands, then DRAINED to the operator's durable
  store.** Every management action a control plane performs, mutating or read-only, records which
  control plane performed it. It is appended on the affected host, because the control plane
  deliberately keeps no durable store of its own (FR-003a).
  **But appended-on-the-host is not where it ends.** A trail that lives only on the hosts dies with
  them, which is the exact problem Feature 014 was created to solve — an entry must outlive its
  host. So attribution rides the drain Feature 016 already built: written locally, ingested by the
  CLI on next contact, durable on the operator's machine. That centralises the trail without any
  new store and without it leaving the operator's own machines.
  Accepted cost: read attribution means write traffic on every enumeration, and a host that cannot
  be written to must degrade to reporting the gap rather than failing the read — the operator asked
  a question, and refusing to answer it because bookkeeping failed would be the wrong trade.

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
   environments their laptop would show **for every permitted host that answers**, and any host that
   did not answer is named as unreachable rather than omitted.
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
- **A permitted host that does not answer** — the live view is the control plane's only source
  (FR-003a), so an unreachable host means a genuinely incomplete list. It must be named as
  unreachable, never omitted silently: a short list that looks complete is worse than an error.
- **A stale control plane** — one whose tool version predates the environments it manages. Refused
  for those environments (FR-016), not for all work: a control plane stale against one environment
  may be current for the rest, and blanket refusal would strand the operator.
- **A control plane one PATCH behind** — must be silent. This is the common case after any `fix`
  release, and reporting it would train the operator to ignore the report that matters.
- **A host registry that has drifted** — distinct from a version mismatch and not covered by
  FR-016; the live query (FR-003a) is what reconciles it.
- **Loss of the SSH key** to the control plane — recovery must not require rebuilding every
  managed host; withdrawing and re-authorising a public key is enough (FR-008).
- **Loss of the passphrase** — no recovery by design (FR-017); redeploy and re-authorise. Stated
  when the passphrase is printed, not after it is lost.
- **A phone-sized screen** — output that assumes a wide terminal is unusable for the actual
  motivating case.
- **An interrupted mobile connection** mid-operation — must not corrupt state; the session ends,
  the operation's outcome must still be knowable.
- **Nested control planes** — supported deliberately (FR-014a). A nested one inherits **no** reach:
  it mints its own key and gains capability only where that key is authorised. What it does add is
  key-minting from inside a session, so the count and provenance of standing keys must be visible.
- **A control plane reached by hopping through another** — stopping the intermediate ends the
  session mid-operation. Governed by FR-013 (the outcome must stay knowable), but worth naming: it
  is the one nesting arrangement where an action can cut the operator's own path back.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST be able to deploy a **control-plane environment** whose purpose is
  management rather than running an agent.
- **FR-002**: An operator MUST be able to reach it over SSH from a device with **no tool
  installed and no configuration**, and find a working, configured CLI.
- **FR-003**: The control plane MUST be able to enumerate and act on the operator's environments
  across the hosts it is permitted to reach.
- **FR-003a**: It MUST obtain its environment list by **querying the permitted hosts live on
  connect**, never by receiving pushes and never by syncing the operator's durable inventory file.
  A locked control plane cannot receive, and making it receivable would require agent containers to
  hold credentials into it — inverting the trust direction. The live view is the control plane's
  truth; it therefore CANNOT report an environment whose host is unreachable or gone, and MUST say
  which permitted hosts did not answer rather than presenting a partial list as complete.
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
- **FR-009a**: Every management action performed from a control plane — **mutating and read-only
  alike** — MUST record **which control plane performed it**. The record is appended where the
  action lands (the control plane holds no durable store of its own, FR-003a) and MUST be **drained
  to the operator's durable store on next contact**, by the same mechanism Feature 016 already uses
  for run records. A trail that lives only on the hosts dies with them, which is the problem Feature
  014 exists to solve.
- **FR-009b**: A host that cannot be written to MUST NOT fail the action. The attribution gap MUST
  be reported instead — the operator asked a question, and refusing to answer because bookkeeping
  failed inverts the priority. An unrecorded action MUST be visible as unrecorded, never silently
  absent from the trail.
- **FR-009c**: Attribution MUST NOT introduce a new field that can carry operator free text.
  Feature 016's `task` is already the one field a credential can arrive in (threat model T15), and
  that exemption is bounded by a closed field set; the control-plane identifier MUST be drawn from
  the same closed vocabulary — a name and a host, nothing an operator types.
- **FR-010**: An action invoked from inside a control plane that would stop or destroy **its own
  container** MUST **refuse to act on itself**, exclude it from the run, and report that exclusion
  explicitly — naming how the operator can stop it instead (from their own machine, or another
  control plane). The control plane is the one container whose stopping makes the report
  undeliverable, so self-exclusion is what makes "the outcome is never unknown" achievable at all.
- **FR-011**: Output MUST be usable on a **narrow screen** — the motivating case is a phone.
- **FR-012**: A stopped or rebooted control plane MUST be usable again **without
  reconfiguration**: its key persists on its volume, and the operator supplies the passphrase on
  the next connect. Recovery MUST NOT require the operator's own machine.
- **FR-013**: An interrupted session MUST NOT corrupt state, and the outcome of an in-flight
  operation MUST remain knowable afterwards.
- **FR-014**: Multiple control planes MUST be individually identifiable and MUST NOT conflict.
- **FR-014a**: A control plane MAY deploy another control plane; nesting is **supported, not
  refused**. A nested control plane is an ordinary environment in every respect — it mints its own
  keypair (FR-007) and gains reach only where its public key is explicitly authorised (FR-007b), so
  it begins with **no** access and none is inherited from its parent. Because nesting means a
  standing key can be minted from inside a control plane rather than only from the operator's own
  machine, the inventory listing (FR-009) MUST make the parent-child relationship visible, so the
  operator can see how many standing keys exist and where each came from.
- **FR-015**: The image MUST remain **rootless and immutable at runtime**; the control plane adds
  no privileges (Constitution II).
- **FR-015a**: The control plane MUST run a **narrower image** than agent containers — the CLI,
  ssh, tmux and git, and **no agent CLIs or their runtimes**. This makes "no agents in the control
  plane" structural rather than documentary: an agent that is not installed cannot be run. The
  cost is a second image, which MUST be built, versioned and freshness-stamped on the same terms
  as the agent image.
- **FR-017**: A lost passphrase MUST have **no recovery path**. Any such path would be a way to
  obtain the key without the passphrase. Recovery is **redeploy** — a fresh keypair, its public
  half authorised, the previous one withdrawn via FR-008. The tool MUST state this at deploy time,
  when the passphrase is printed, rather than leaving an operator to discover it after the loss.
- **FR-016**: A control plane MUST compare its own tool version against the version an environment
  was created with **by semver precedence, never by equality**, and act on the difference:
  - a **PATCH** difference (and, once past 1.0, a MINOR one) is **ignored** — not reported at all,
    because it cannot carry a breaking change and a warning nobody needs is one nobody reads;
  - a **breaking-channel** difference (MINOR while pre-1.0, MAJOR after) is **advisory** when the
    control plane is the newer side — the normal state after any upgrade — and MUST NOT block;
  - the same difference in the other direction, where the **environment is newer than the control
    plane**, MUST be **refused**: that is the only case where the environment may carry interfaces
    the control plane does not know about, and it is the one the operator cannot detect by eye;
  - an unreadable version on either side MUST be reported **unknown** and MUST NOT be treated as
    compatible.

  The refusal MUST name the remedy — redeploy the control plane from the newer CLI — since the
  operator reading it is on a phone and cannot investigate.

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
  own machine — **zero** divergence for hosts that are both **in scope and reachable**. A host that
  did not answer MUST be reported as such, so an incomplete list is never mistaken for an empty one.
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
- **SC-009**: The control-plane image contains **zero** agent CLIs — verified by inspecting the
  built image, not by reading its build definition.
- **SC-010**: A stop-everything action invoked from inside reports its own container as
  **excluded** — **zero** runs in which the control plane's own outcome is unknown.
- **SC-011**: Every control plane in the listing shows whether it was deployed from the operator's
  machine or from another control plane, and which — **100%**. Nesting makes the number of standing
  keys grow from inside the system, and a count nobody can see is a count nobody audits.
- **SC-013**: Every action performed from a control plane is attributable to it after the fact —
  **100%** of actions, read and mutating — and the trail survives the destruction of the host the
  action was performed on, because it is drained to the operator's store. **Zero** actions that are
  absent from the trail without being marked unrecorded.
- **SC-012**: A control plane one PATCH version from an environment reports **nothing** about
  versions — **zero** advisories. A breaking-channel difference in the risky direction (environment
  newer) is refused — **100%**, with the remedy named. Both halves are measured, because a rule that
  only ever warns and a rule that only ever refuses are equally wrong and each passes half a test.

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
- **An external or cloud-hosted telemetry destination.** Attribution drains to the operator's own
  machine (FR-009a). Shipping it off-box would export the one record class that can contain
  operator-typed text — threat model T15 — turning a bounded, accepted risk into an exported one
  (Constitution III), and would be the largest dependency the project has ever taken
  (Constitution VI). It also crosses a new trust boundary, which the Constitution requires
  reconciling in the threat model, so it belongs in a feature of its own rather than as a clause
  here. Noted as a candidate, not deferred silently.
- Multi-user or multi-tenant access control — single operator remains assumed.
- Running agents inside the control plane — enforced by FR-015a's narrower image, not merely
  declared here.
- Cross-operator or shared control planes.
- Automatic or unattended deployment of control planes.

## Dependencies

- **Feature 013 (`doctor`)**, **014 (inventory)**, **015 (kill switch)**, **016
  (observability)**: the management surface it exposes. It should be specified last and built
  last for exactly this reason.
- **A second image has consequences beyond this feature.** Feature 013's version stamp must be
  applied to both images, and the existing cross-file test asserting the Dockerfile installs
  exactly the supported agents must learn that the control-plane image installs **none** — it
  would otherwise fail, correctly, on a second Dockerfile that omits them.
- **Feature 001 / 002 (hosts, lifecycle)**: the registry it carries and the verbs it offers.
- **Feature 003 / 008 (credentialing)**: the operator-interactive carve-out FR-007 relies on —
  on-volume credentials are permitted when they originate from an operator-interactive act, which
  is exactly what generating a passphrase-protected key at deploy is.
- **Feature 014 (inventory)**: pulled on connect (FR-003a), never pushed.
- **Feature 005 (shell integration)**: the attach path this reuses.
- **Constitution II (rootless, immutable runtime)**: FR-015.
- **Constitution III (least exposure)**: the principle this feature strains hardest, and the
  reason FR-004/FR-006/FR-008 exist.
