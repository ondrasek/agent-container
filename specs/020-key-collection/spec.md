# Feature Specification: Public-key collection, auto-injected

**Feature**: `020-key-collection` | **Created**: 2026-08-23 | **Status**: Draft

**Input**: User description: "Public key collection auto-inject. The user can create a 'collection' of
ssh public keys that would be auto-injected (overridable on project level) to any created/managed
agent or control plane. For example, I have my iPhone, iPad and Macbook — I want to connect to my
containers from all three devices. I will collect ssh public keys from all three and store them
somewhere for the agent-container cli to find."

## Why this exists

Today every device is authorised **per deployment**, by hand:

```sh
agent-container up acme --authorized-key ~/.ssh/iphone.pub \
                        --authorized-key ~/.ssh/ipad.pub \
                        --authorized-key ~/.ssh/macbook.pub
```

Three flags, remembered correctly, on every `up` and every `redeploy`, for every environment. The
failure is not that it is tedious — it is that **forgetting is silent**. A container deployed without
the iPhone key works perfectly until the operator is holding the iPhone, which is exactly when they
cannot fix it. Feature 017 makes this sharper: a control plane exists to be reached from a phone.

## User Scenarios & Testing *(mandatory)*

### US1 — Every new environment is reachable from every device (P1)

The operator registers their three device keys once. Every subsequent `up` — agent or control plane,
any host — is reachable from all three with no per-deployment flags.

**Independent test**: register three keys, `up` an environment naming no keys, and connect with each
of the three private halves.

### US2 — A project can override the collection (P1)

A project directory can declare its own collection, which **replaces** the user-level one for
environments deployed from that project. A shared or client project should not silently inherit an
operator's personal devices.

**Independent test**: with a user-level collection of three keys and a project-level collection of
one, an environment deployed inside the project admits only the project's key.

### US3 — Removing a device removes its access (P1)

The operator loses the iPad. Removing it from the collection and redeploying must end that device's
access to the redeployed environment.

**Independent test**: deploy with two keys, remove one from the collection, `redeploy`, and confirm
the removed key is refused.

### US4 — The operator can see what will be admitted, before deploying (P2)

Which keys an environment will admit is visible **before** it is created, and afterwards.

**Independent test**: with a collection declared, a pre-deploy statement names each key that will be
admitted; a query names the same set for a running environment.

### Edge cases

- **A malformed or non-public-key line** in the collection — refused with the offending entry named,
  never silently dropped. A key that does not work is indistinguishable from a key that is absent.
- **A PRIVATE key placed in the collection by mistake** — refused loudly. This is the one mistake
  whose cost is not recoverable by editing a file.
- **An empty collection** (declared, no entries) — distinct from **no collection declared**. The first
  says "admit nobody"; the second says "no declaration exists". They must not be conflated
  (Constitution VIII).
- **Both `--authorized-key` and a collection** — the flag is additive to the resolved collection, and
  the resulting set is stated. Neither silently wins.
- **A key already authorised on a long-lived container** that is later removed from the collection —
  see FR-006; the current union-with-persisted behaviour makes this the feature's hardest requirement.
- **A duplicate key** across the collection and a flag, or listed twice — admitted once, no error.

## Requirements *(mandatory)*

### Functional

- **FR-001**: The operator MUST be able to declare a **collection** of SSH public keys that is
  auto-injected into every environment the tool creates or recreates, with no per-deployment flag.
- **FR-002**: The collection MUST be resolvable at **both configuration levels** — user and project —
  with **project replacing user entirely**, not merging. Merging would mean a project could not
  *narrow* the set, only widen it, and narrowing is the point of US2.
- **FR-003**: The collection MUST apply to **both roles** — agent environments and control planes.
  A control plane is the case the feature exists for.
- **FR-004**: Every key in a declared collection MUST be **validated as an SSH public key** before
  deployment, and a malformed entry MUST **refuse the deploy** naming the entry. A key that silently
  fails to admit is a lockout discovered from the device that cannot fix it.
- **FR-005**: A **private key** in the collection MUST be refused with an explicit statement that it
  is private, and MUST NOT be transmitted anywhere.
- **FR-006**: Removing a key from the collection and recreating the environment MUST **end that key's
  access**. The tool MUST NOT rely on the container's existing `authorized_keys` union, which today
  preserves every key ever injected — under that behaviour a collection could add access and never
  remove it, and the operator would believe otherwise.
- **FR-007**: The set of keys an environment will admit MUST be **stated before deployment** and
  **queryable afterwards**, identified by something an operator can recognise (comment/fingerprint),
  never by opaque blob alone.
- **FR-008**: `--authorized-key` MUST remain and be **additive** to the resolved collection. The
  resulting set MUST be stated so neither source appears to have won silently.
- **FR-009**: An **undeclared** collection MUST behave exactly as today (no auto-injection), and MUST
  be distinguishable from a **declared-empty** collection, which admits nobody.
- **FR-010**: Public keys MUST travel as **non-secret configuration** and MUST NOT be treated as
  secrets. They are public by construction; classifying them as secrets would imply protections that
  mislead about what they are.
- **FR-011**: The collection MUST be **operator-editable as plain text** without a tool command, and
  the tool MUST read whatever is there rather than requiring registration through it.
- **FR-012**: A collection referencing a **missing file** MUST refuse the deploy before any runtime
  call, naming the path.

### Key entities

- **Key collection** — an ordered set of SSH public keys, declared at user or project level, each
  with an operator-recognisable label.
- **Resolved admit set** — what an environment will actually admit: the winning collection plus any
  `--authorized-key`, deduped. This is the thing FR-007 states and FR-006 constrains.

## Success Criteria *(mandatory)*

- **SC-001**: An operator registers three device keys **once** and deploys an environment with **zero**
  key flags; all three devices connect.
- **SC-002**: A project-level collection of one key yields an environment that admits **exactly one**
  key — the other two are refused.
- **SC-003**: A key removed from the collection is refused by the environment after recreation, in
  **100%** of attempts. Zero keys retain access after removal.
- **SC-004**: A malformed entry refuses the deploy **before** any container is created, and the message
  names the offending entry.
- **SC-005**: A private key in the collection is refused, and **zero** bytes of it reach any container,
  log, or generated artifact.
- **SC-006**: The admit set is visible before deployment and after, and the two agree for an unchanged
  collection.
- **SC-007**: An undeclared collection changes nothing about today's behaviour — an environment
  deployed with `--authorized-key` alone admits exactly that key.

## Assumptions

- **Public keys are not secrets.** They ride the non-secret configuration channel, as Feature 017's
  host registry does.
- **The two-level contract is Feature 011's** — same filename at both levels, project winning. No new
  layout location is introduced.
- **Devices are identified by the key's own comment** where present; the tool does not invent a
  device registry.
- **Rotation is out of scope.** Replacing a key is editing the collection and recreating; there is no
  scheduled rotation.
- **`ssh-agent` forwarding, certificate authorities and OIDC-based SSH are out of scope.** A CA would
  make this feature unnecessary, and choosing one is a larger decision than this feature.

## Dependencies

- **Feature 011** (two-level configuration) — the resolution contract.
- **Feature 017** (control plane) — the motivating consumer, and the precedent for injecting
  non-secret configuration inline.
- **Feature 019** (agent SSH key pair) — unaffected. That key is the container's own outbound
  identity; this feature is about inbound authorisation.

## Out of scope

- Distributing or generating device private keys.
- Any per-environment allow/deny beyond project-level override.
- Revoking access on a **running** container without recreating it.
