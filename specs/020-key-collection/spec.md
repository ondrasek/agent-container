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

## Clarifications

### Session 2026-08-23

- Q: When the operator removes a key, then `stop` and `start` rather than `redeploy`, what must happen? → A: `start` compares the resolved collection against what the deployment was created with; on drift it warns, names which keys differ, and points to `redeploy`. Resume semantics unchanged.
- Q: Does the post-deploy admit-set query observe the container or re-resolve the config? → A: Both, reported side by side. Disagreement is stated, not inferred; an unreachable container yields `undetermined` for the observed set, never a claim of agreement.

- Q: Where does a key injected by the existing `keys` command live relative to the collection's managed region? → A: Inside it. The collection is the sole authority, and a `keys` grant lasts only until the next recreate. This changes what `keys` currently means.

- Q: Does a declared-but-empty collection warn, prompt, or pass silently? → A: Warn and proceed, naming the file. The declaration is honoured; the operator is told the environment will admit nobody.

- Q: Which command answers "what will this environment admit?" → A: A new `keys` subgroup — `keys show <name>` for one environment, `keys ls` across them. Consequence, decided from the codebase's own noun-plus-verb idiom rather than asked: the existing grant form `keys <name> --authorized-key` moves to `keys add <name> --authorized-key`, because `show`/`ls`/`add` are all legal environment names and a bare positional beside a subcommand would make an environment named `show` unreachable.


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
- **A key granted by `keys` on a running environment, then a recreate** — the grant is **gone**
  (FR-015). Deliberate: a grant the collection cannot revoke is the one thing FR-006 forbids, and
  `keys` today creates exactly that.
- **A key added by hand from inside the environment** — **survives** recreation (FR-016). The tool
  replaces only the region it wrote.
- **The collection is edited, then `stop` + `start` rather than `redeploy`** — `start` resumes and does
  not re-resolve, so the environment still admits the set it was created with. The container's own
  boot rewrites its key block, which makes that stale set *look* freshly authoritative. `start` MUST
  therefore report the drift (FR-013); staying silent would reproduce the exact failure FR-006 exists
  to fix, one command over.

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
- **FR-013**: `start` MUST compare the resolved collection against the set the deployment was
  **created with** and, when they differ, **warn** and name the differing keys and `redeploy` as the
  remedy. `start` MUST NOT re-resolve or re-apply the collection — it is a resume, and re-applying
  would silently turn it into a deploy. The warning is what keeps a stale admit set from passing as a
  current one.
- **FR-014**: The post-deploy query MUST report **both** the **projected** admit set (re-resolved from
  the collection) and the **observed** admit set (read from the environment itself), and MUST state
  when they **disagree**. When the environment cannot be reached, the observed set MUST be reported as
  **`undetermined`** — never as agreement, and never silently replaced by the projection. A query that
  answered from the projection alone would compare a projection with itself and report agreement it
  never checked.
- **FR-019**: A **stopped** environment MUST report its observed set as **`undetermined`**, not as
  empty. Observation requires reaching inside a running environment; a stopped one has not been
  examined, and "nobody is authorised" is a materially different claim from "we did not look". An
  **empty** observed set MUST therefore mean a running environment whose managed region is genuinely
  empty. Three states again, and the same rule as FR-009: absent, empty and unexamined do not collapse.
- **FR-020**: A query spanning **many** environments MUST report each one's outcome independently and
  MUST NOT fail the whole listing because one environment could not be reached. An unreachable
  environment appears as `undetermined` **in its own row**, and the query's exit status MUST NOT claim
  success for environments it never examined.
- **FR-015**: A key injected by the `keys` command into a running environment MUST land **within the
  tool-managed region** of the environment's authorised keys, so that recreating the environment
  removes it. **The tool MUST NOT create a grant it cannot revoke.** `keys` MUST state at injection
  that the grant lasts **until the next recreate**. This is a **change to the existing behaviour** of
  `keys`, which today appends to the persisted file permanently — a grant removable only by `--purge`,
  which destroys the environment's own SSH identity. That path is the documented opposite of FR-006 and
  MUST NOT survive this feature.
- **FR-016**: Content the tool did not write — a key added by hand from inside the environment — MUST
  be preserved across recreation. FR-015 constrains what the **tool** grants; it does not make the tool
  the owner of a file an operator may also edit. The tool's region is delimited and replaced; anything
  outside it is not the tool's to remove.
- **FR-017**: A **declared-empty** collection MUST be **honoured and warned about**, naming the file
  and saying the environment will admit nobody. It MUST NOT prompt and MUST NOT refuse: an empty
  declaration is a legitimate instruction for a headless environment, and refusing without a tty would
  break unattended deploys that intend exactly this. The **undeclared** path MUST NOT gain this warning
  — today an environment deployed with no keys at all is silent, and FR-009 requires that stay true.
  The asymmetry is deliberate: the warning exists because a hand-edited file can be **truncated by
  accident**, and where there is no file there is nothing to truncate.
- **FR-018**: The admit-set query MUST be exposed as a **`keys` subgroup** — `keys show <name>` for
  one environment and `keys ls` across them — following the noun-plus-verb idiom every other group in
  this tool already uses (`ssh-key show`, `host ls`, `runs list`). The existing grant form
  `keys <name> --authorized-key` MUST move to **`keys add <name> --authorized-key`**. This is required,
  not cosmetic: `show`, `ls` and `add` are all legal environment names, so a bare positional beside a
  subcommand would make an environment named `show` permanently unreachable through this group. The
  query MUST NOT be attached to `ssh-key show`, which reports the environment's **outbound** identity —
  the opposite direction, and conflating the two in one output is the confusion this feature is careful
  to avoid elsewhere.

### Key entities

- **Key collection** — an ordered set of SSH public keys, declared at user or project level, each
  with an operator-recognisable label.
- **Resolved admit set** — what an environment will actually admit: the winning collection plus any
  `--authorized-key`, deduped. This is the thing FR-007 states and FR-006 constrains. It exists in two
  forms that must never be conflated: **projected** (computed from the collection) and **observed**
  (read from the environment). Before deployment only the projection exists; afterwards both do, and
  FR-014 requires both be reported.

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
- **SC-006**: The admit set is visible before deployment and after. For an unchanged collection the
  **projected and observed** sets agree, and that agreement is established by reading the
  **environment** — not by re-resolving the same file twice. A test in which the observed set is
  fabricated from the projection MUST fail.
- **SC-007**: An undeclared collection changes nothing about today's behaviour — an environment
  deployed with `--authorized-key` alone admits exactly that key.
- **SC-008**: After removing a key and running `stop` then `start`, the operator is told the admit set
  is out of date and which key differs, in **100%** of such resumes. No resume reports agreement while
  admitting a removed key.
- **SC-009**: A key granted with `keys` is admitted immediately and is **refused after a recreate**,
  in **100%** of attempts. No tool-created grant outlives the collection.
- **SC-010**: A key added by hand inside the environment is still admitted after a recreate. The tool
  removes what it wrote and nothing else.
- **SC-011**: A declared-empty collection deploys successfully, warns once naming the file, and the
  environment admits nobody. The same deploy with **no** collection declared produces **no** such
  warning — the two runs are distinguishable in output, not merely in behaviour.
- **SC-013**: A stopped environment's observed set reads `undetermined`, and is distinguishable in
  output from a running environment whose region is empty. Neither is ever reported as the other.
- **SC-014**: With one environment unreachable and three reachable, a listing reports four rows — three
  with observed sets and one `undetermined` — and does not abort after the failure.
- **SC-012**: An environment named `show` is fully usable through the `keys` group — its admit set is
  queryable and a key can be granted to it. No legal environment name is made unreachable by the
  command layout.

## Assumptions

- **Public keys are not secrets.** They ride the non-secret configuration channel, as Feature 017's
  host registry does.
- **The two-level contract is Feature 011's** — same filename at both levels, project winning. No new
  layout location is introduced.
- **Devices are identified by the key's own comment** where present, and by **fingerprint** where the
  comment is absent; the tool does not invent a device registry. A key with no comment is legal and must
  remain usable — it is merely harder for the operator to recognise, which is their choice to make.
- **A project-level collection is committed to the repository unless the project ignores it.** Nothing
  in this feature ignores it, and public keys are public, so this is safe rather than a leak — but it is
  a consequence worth stating: a committed collection means every collaborator's environments admit that
  set, which is what makes US2's "client project" case work, and also means adding a personal key there
  shares it. An operator who wants per-collaborator collections ignores the file and each keeps their own
  at user level.
- **Rotation is out of scope.** Replacing a key is editing the collection and recreating; there is no
  scheduled rotation.
- **`ssh-agent` forwarding, certificate authorities and OIDC-based SSH are out of scope.** A CA would
  make this feature unnecessary, and choosing one is a larger decision than this feature.

## Dependencies

- **Feature 011** (two-level configuration) — the resolution contract.
- **Feature 017** (control plane) — the motivating consumer, and the precedent for injecting
  non-secret configuration inline.
- **The `keys` command** — behaviour changes under FR-015. Not a dependency so much as a casualty:
  it is the one existing surface that creates inbound access, and it cannot keep doing so on terms the
  collection cannot undo.
- **Feature 019** (agent SSH key pair) — unaffected. That key is the container's own outbound
  identity; this feature is about inbound authorisation.

## Out of scope

- Distributing or generating device private keys.
- **In scope, and stated here because it looks out of scope:** the existing `keys` command changes
  behaviour (FR-015). Its grants become recreate-scoped rather than permanent. This is a **breaking
  change to a shipped command**, as does FR-018 renaming its grant form to `keys add`. Both must be
  released as such — pre-1.0, that is a MINOR bump, and the
  commit and release notes must say plainly that a `keys` grant no longer survives a recreate.
- Any per-environment allow/deny beyond project-level override.
- Revoking access on a container without recreating it — whether **running** or merely **resumed**
  via `start`. `start` reports the drift (FR-013) rather than acting on it.
