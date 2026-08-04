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

> **The hard constraint.** The **agent** container is rootless and immutable at runtime
> (Constitution II): no `sudo`, no capabilities added, nothing installed after build. Nothing this
> feature does may change that.
>
> **What that constraint does *not* forbid** (corrected 2026-08-05, US4): packet filtering by a
> *different* container. Constitution II is per-container — the rule is that the container running
> **untrusted agent code** holds no more privilege than its work requires. A proxy sidecar running
> no untrusted code may hold `NET_ADMIN` and program the network namespace the agent joins, while
> the agent itself gains nothing. This is the Istio/Linkerd sidecar pattern, and it was verified by
> probe (research R11).
>
> The earlier reading of this constraint — that packet filtering was out of scope *by construction*
> — conflated "the agent container" with "any container", and in doing so ruled out the only
> mechanism that makes enforcement independent of the agent's cooperation.

## Clarifications

### Session 2026-08-05 — US4/US5 clarification

- Q: How is a non-HTTP destination declared, given FR-018 needs host **and** port granularity and
  the schema has only `providers` (vendor names) and `allow` (bare hosts)? → A: **A single unified
  list of typed entries, replacing both.** `egress.allow` becomes a list whose entries are one of:

  ```yaml
  egress:
    allow:
      - provider: anthropic                     # tool supplies the hosts
      - provider: openai
        hosts: [llm.corp.internal]              # REPLACES the tool's mapping (FR-001b)
      - host: "*.githubusercontent.com"         # HTTPS, via the proxy
      - host: github.com
        port: 22                                # non-HTTP: a netfilter rule, not a proxy entry
    enforcement: advisory
  ```

  **The port is what selects the mechanism**, and that is the property that makes one list
  coherent rather than merely shorter: an entry **without** a port is HTTP/HTTPS and becomes a line
  in the proxy's allowlist; an entry **with** a port is anything else and becomes an explicit
  netfilter rule. The operator declares *destinations*; the tool decides which of its two
  enforcement surfaces each one needs.

  **Accepted cost — this re-specs syntax already implemented and tested on this branch.**
  `providers:`/`allow:` as separate keys, their validation, `resolve_provider_hosts` and their
  tests all change. Chosen over the compatible options because the alternative was a schema where
  `allow` meant two different things and a bare host silently implied 80+443 while
  `host:port` implied only that port — an inconsistency operators would trip over for as long as
  the tool exists. Pre-1.0, and the cost is paid once.

### Session 2026-08-04 — scope corrected after a design probe

- Q: The mechanism is a forward proxy on `HTTPS_PROXY`. That intercepts **every** HTTPS request,
  not only model-provider ones — so the earlier "controlling egress unrelated to model providers
  is out of scope" could not be honoured by the thing being built. Which gives? → A: **The scope
  gives. The declaration governs ALL egress, and the operator declares everything the environment
  needs.** Truthful to the mechanism; the alternative was a permanent hidden allowlist that makes
  the declaration mean less than it says.

  **What forced it.** Verified by probe: with `providers: [anthropic]`, `git ls-remote
  https://github.com/…` returns `CONNECT tunnel failed, response 403` while the declared provider
  still answers. `image/entrypoint.sh` configures `credential.https://github.com.helper` from
  `GH_TOKEN`, so **HTTPS push is the documented default** — and a silently unenforceable push
  breaks the project's first hard constraint, *"every agent must commit AND push every change"*.
  The failure is maximally cruel: the agent works perfectly all session and fails **only at push
  time**, exactly when work would otherwise have been preserved. SSH push survives (`ssh` ignores
  `https_proxy`), so it is invisible to anyone testing with a push key and fatal to anyone using
  the documented token path.

  Rejected — an unconditional built-in baseline (always permit `github.com` et al.): it keeps the
  constraint safe but makes the declaration untruthful, and "I declared only `anthropic`" would
  quietly mean "anthropic plus whatever we decided you also need". The whole feature exists to end
  that kind of silence.

### Session 2026-07-29

- Q: How is undeclared egress actually detected and prevented, given the container cannot add
  privileges? → A: **An egress proxy sidecar.** A helper container sharing the environment's
  compose project and lifecycle can allowlist the declared providers with **no container
  privileges**. The agent is pointed at it through
  standard proxy environment variables. This turns enforcement from *"the agent was configured
  not to"* into *"the request was refused"*, and makes the egress record real rather than
  dependent on what an agent chooses to report.
- Q: What does an environment declaring **no** providers mean? → A: **Unrestricted, but
  disclosed.** Behaviour is unchanged from today, except the operator is told once that the agent
  has a built-in default it can reach without their credential. The gap being closed was silence,
  not permissiveness; enforcement stays opt-in and existing environments keep working.
- Q: When a declaration cannot be honoured for the chosen agent, refuse or warn? → A: **Refuse
  only in strict mode.** An `enforcement` setting selects `advisory` (default — deploy, state the
  limitation) or `strict` (refuse). Noted tradeoff, accepted knowingly: the safe behaviour is the
  one an operator must remember to ask for.
- Q: Where does the declaration live? → A: **The declarative spec**
  (`.agent-container/environments.yaml`), beside the credentials that authorise the providers. No
  new file and no new resolution path.

**Consequence worth stating**: the proxy answer makes the third question narrower than it looked.
With a proxy in place, enforcement is real for *any* agent that honours proxy environment
variables — the agent's own configuration stops being the mechanism. "Cannot be constrained"
therefore means **the agent bypasses the proxy**, not "the agent lacks a provider setting".

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

### User Story 4 - Enforcement the agent cannot switch off (Priority: P1)

An operator's declaration holds **even when the agent actively tries to evade it**. The agent
cannot reach an undeclared destination by unsetting an environment variable, editing its own
configuration, or running a script that does either.

**Why this priority**: US1's proxy binds only clients that *choose* to honour proxy environment
variables. An agent that can be prompted into `unset HTTPS_PROXY`, or into writing that line to
`~/.agent-env/env`, defeats the entire control — and a prompt-injected agent is precisely the
threat this container exists to contain. US1 protects against **accident and misconfiguration**;
US4 protects against **the agent itself**. Without it the declaration describes an intention rather
than a boundary.

**Independent Test**: with a declaration in force, unset every proxy variable inside the container
and attempt to reach an undeclared host. It must fail. Then attempt the same on a **non-standard
port** (8080, 1337) and confirm those fail too.

**Acceptance Scenarios**:

1. **Given** a declaration in force, **When** the agent unsets all proxy environment variables and
   connects directly, **Then** the attempt **fails** — enforcement does not depend on the agent's
   cooperation.
2. **Given** the same, **When** the agent writes proxy overrides into `~/.agent-env/env` and opens
   a new shell, **Then** the attempt still fails.
3. **Given** the same, **When** the agent contacts an undeclared host on a **non-standard port**
   (e.g. `8080`), **Then** it fails — the control is not port-specific, so it cannot be sidestepped
   by choosing an unusual one.
4. **Given** enforcement is active, **When** the operator inspects the agent container's
   privileges, **Then** they are **unchanged** — no capability is added to the container that runs
   untrusted code.

---

### User Story 5 - Every protocol and port is declared, or it fails (Priority: P1)

Whatever the environment is permitted to reach — HTTP, HTTPS, SSH, FTP, gRPC, a database, a
non-standard port — the operator **declares it**. Anything not declared fails closed.

**Why this priority**: US4's mechanism is only as strong as its default. Allowing everything except
HTTP/HTTPS would leave the widest possible hole: an agent reaches a malicious endpoint on `8080`,
or exfiltrates over SSH, and the declaration says nothing about either. **Default-deny is what
makes US4 an enforcement boundary rather than a speed bump**, and it is P1 for the same reason US4
is — a partial boundary invites the shape of traffic that evades it.

**Independent Test**: declare one HTTPS provider and nothing else. Confirm that provider works and
that SSH, FTP and an arbitrary high port all fail — then declare SSH to one host and confirm only
that host on that port becomes reachable.

**Acceptance Scenarios**:

1. **Given** a declaration listing only HTTPS providers, **When** any other protocol or port is
   attempted, **Then** it **fails** — declared-or-denied, with no implicit allowance.
2. **Given** an operator declares a non-HTTP destination (SSH to a git remote, say), **When** the
   agent uses it, **Then** it succeeds — and **only** that host and port, not the protocol
   generally.
3. **Given** name resolution is required for any declared destination to work at all, **When** the
   environment starts, **Then** DNS functions — a dependency the declaration does not have to state
   because nothing reachable works without it.
4. **Given** a declaration the mechanism cannot enforce, **When** the operator deploys, **Then** the
   behaviour follows the existing `enforcement` setting (FR-007b) — refuse under `strict`, deploy
   and say so under `advisory`.
5. **Given** an environment with **no** declaration, **When** it starts, **Then** behaviour is
   unchanged and unrestricted (FR-004) — default-deny applies to environments that opted in, never
   retroactively to those that did not.

---

### Edge Cases

- **An agent with no configurable provider list** — the limit of what can be enforced for that
  agent must be stated plainly, not implied to be equivalent to the others.
- **A declared provider the agent cannot use** (no credential for it) — must fail naming the
  missing credential, not the declaration. Met by FR-003b.
- **An agent that ignores the mechanism** — if enforcement can be bypassed by the agent itself,
  that limit must be documented; a control presented as stronger than it is, is worse than none.
- **Enforcement without new privileges is not absolute** — the difference between *"the agent is
  configured not to"* and *"the network will not carry it"* must be explicit to the operator.
- **A provider reached indirectly** (a proxy, a gateway, a self-hosted endpoint) — declaring
  "anthropic" must not accidentally permit or forbid an unrelated endpoint. Met by FR-001a's
  explicit host list, which **replaces** the tool's mapping rather than extending it (FR-001b).
- **Environments predating this feature** — must keep working; pre-1.0, no compatibility is
  promised beyond that.
- **Air-gapped or offline use** — declaring zero providers must be a coherent state, not a
  degenerate one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An operator MUST be able to declare, per environment, the set of model providers
  that environment is permitted to reach.
- **FR-001a**: A provider entry MUST support an optional explicit **host list**, so an operator
  reaching a provider **indirectly** — a corporate gateway, a self-hosted endpoint, a
  vendor-compatible deployment — can express it. Without this, such an operator could only leave
  the declaration empty and get **no enforcement at all**, which would give the least protection
  to the deployments most likely to want it.
- **FR-001b**: Where an explicit host list is given, it **REPLACES** the tool's mapping for that
  entry; it MUST NOT be added to it. An operator who routes through a gateway is usually doing so
  to close the direct vendor path — treating the list as additive would silently leave that path
  open while the declaration reads as constrained. The provider name remains the human-meaningful
  label the declaration is read by.
- **FR-001c**: The declaration MUST be able to express **non-provider hosts** — git remotes,
  package registries, anything else the environment legitimately reaches. The enforcement
  mechanism is a forward proxy, which governs **all** HTTPS egress and cannot be narrowed to
  model providers; so an environment that declares anything must be able to declare everything it
  needs. Provider **names** stay the readable shorthand for model vendors; a separate list carries
  plain hosts.
- **FR-001d**: A non-provider host entry MUST support matching **a domain and its subdomains**,
  since real dependencies span them (`*.githubusercontent.com`). Without it an operator would
  enumerate hosts they cannot know in advance, and would reach for an over-broad workaround.
- **FR-001e**: **The tool MUST NOT maintain a hidden always-permitted baseline.** If a host is
  reachable, the declaration says so. A built-in exemption would make the permitted set differ
  from the declared set — reintroducing, inside the feature, exactly the silence it exists to end.
- **FR-003c**: When an environment is configured to **push over HTTPS** and the effective
  allowlist does not cover that remote's host, the tool MUST say so **at deploy time**, naming the
  host to add — refusing under `strict`, warning under `advisory`.

  This protects the project's first hard constraint (*commit AND push every change*) at the only
  moment it can still be protected. Both facts are known before anything runs: the remote is in
  the environment's configuration and the allowlist is in the declaration. Discovering it instead
  at push time means discovering it **after** the work exists and **before** it is safe — the one
  ordering the constraint exists to prevent. This requirement is what makes FR-001e's
  no-hidden-baseline rule safe to hold.
- **FR-002**: The declaration MUST live in the **declarative spec**
  (`.agent-container/environments.yaml`), beside the credentials that authorise those providers —
  no new file and no new resolution path.
- **FR-003**: An attempt to reach a provider outside the declared set MUST NOT succeed silently.
  The operator MUST learn of it at **run time**, when the proxy refuses the request.
- **FR-003a**: One case **is** knowable before anything runs and MUST be reported at **deploy
  time**: the selected agent's **built-in default provider is not in the declared set**. Both
  facts are known without executing the agent, so waiting for a runtime refusal would be a choice
  to withhold. This is the concrete content of the earlier vague "at deploy time where that is
  possible" — the agent picks its provider at run time, so no *general* deploy-time detection
  exists, and claiming otherwise would be an untestable requirement.
- **FR-003b** *(rewritten 2026-08-04)*: A credential that cannot be resolved MUST fail naming
  **that credential and its source**, before any container is touched. No failure message on the
  egress path may attribute a credential problem to the `egress` declaration. **The tool MUST NOT
  infer that a declared provider requires a particular credential** — no such association exists,
  and inventing one would produce false failures.

  **Why the earlier wording could not be built.** It presupposed the tool could tell that a
  declared provider needs a given credential. It cannot: `PROVIDERS` maps provider→hosts,
  `CRED_PROVIDER` maps credential-name→provider for *delivery routing only* and covers two of five
  providers, and `AGENT_BUILTIN_DEFAULT` is the inverse relation entirely. Any inference would
  false-positive on a provider reached without a credential — which is the exact case Feature 010
  discovered and this feature exists to surface. So the requirement becomes a **prohibition** on
  misattribution, which is both implementable and the thing the operator actually needed.
- **FR-004**: An environment declaring **no** providers MUST be **unrestricted**, exactly as
  today — and the operator MUST be told once that the agent may reach a built-in default without
  their credential. Enforcement is opt-in; the defect being fixed is silence, not permissiveness.
- **FR-005**: For every supported agent, the tool MUST be able to report **what that agent can
  reach**, including any built-in default provider, without the operator consulting the agent's
  own documentation.
- **FR-006**: When an agent has a built-in default provider that operates without an operator
  credential, the operator MUST be told **once and clearly**, rather than discovering it from
  traffic or from behaviour.
- **FR-007**: Enforcement MUST NOT require adding privileges, capabilities or runtime
  installation to the agent container (Constitution II). It MUST be delivered as an **egress
  proxy sidecar** — a helper container in the environment's own compose project, so it shares that
  project's lifecycle including teardown. It MUST be emitted into the compose model **the tool
  generates**, not into the operator's sidecar override file: that file is validated services-only
  and forbidden from redefining the agent service, and is operator-owned by design (planning
  research R4, which corrected an earlier assumption that the override channel was the route).
- **FR-007a**: The agent MUST be pointed at the proxy through standard proxy environment
  variables, and the proxy MUST refuse any host outside the declared set.
- **FR-007b**: An `enforcement` setting MUST select between **`advisory`** (default — deploy, and
  state that the declaration is not enforced for this agent) and **`strict`** (refuse to deploy
  when the declaration cannot be enforced). The effective mode MUST be visible before deploying.
- **FR-008**: The **strength** of the enforcement MUST be stated honestly. A proxy refuses
  requests from clients that honour it; it does **not** stop a process that ignores proxy settings
  and opens a direct connection, because **this feature does not do packet filtering**. The tool
  MUST NOT imply a stronger guarantee than that, and MUST say which agents are known to honour the
  proxy.
- **FR-008b** *(corrected 2026-08-04)*: The statement MUST describe that limit as a **scope
  decision, not an impossibility**. Packet filtering *is* achievable here: `NET_ADMIN` on the
  **proxy** container plus a shared network namespace (`network_mode: service:egress`) intercepts
  unconditionally while the **agent** container gains no capability at all — the standard sidecar
  pattern. Constitution II is per-container (*"a container runs untrusted agent code; it MUST hold
  no more privilege than **its** work requires"*), and the capability would land on a container
  running no untrusted code.

  Earlier drafts of this spec asserted that packet filtering "needs privileges Constitution II
  forbids". **That was wrong** — it conflated *the agent container* with *any container in the
  deployment*. Saying so matters beyond accuracy: a false impossibility claim is an argument
  against ever building the stronger mechanism, planted inside the requirement that exists to keep
  the tool honest.
- **FR-008a**: The honesty statement MUST also disclose that **a shell inside the container can
  override the proxy settings**, because `~/.agent-env/env` is sourced with `set -a` by every
  interactive shell — *after* the container environment, from a volume that survives teardown.
  The tool cannot inspect it at deploy time (it is inside the container) and cannot prevent it
  (the agent owns its shell). Omitting this would make FR-008 assert a guarantee that a single
  line in a persistent file silently revokes — the precise shape of overclaim this feature was
  written to eliminate, reappearing in the statement meant to prevent it.
- **FR-009**: No provider declaration may expose a credential value, and declaring a provider
  MUST NOT imply storing its credential in the project (Constitution III, and the Feature 011
  rule that the repo holds a locator, never a value).
- **FR-010**: Undeclared egress events MUST be recorded such that they remain available after the
  container is removed (Constitution I — the container is ephemeral). Egress events are their
  **own schema** — a different producer (the proxy, not the agent) and a different lifetime
  (continuous, not at-run-end); Feature 016's FR-011a already establishes that a distinct concern
  gets a distinct schema. What this requirement needs is the **durable per-container store and its
  ingestion machinery**, which introduces a **tenth** per-container volume — an identity migration
  under Constitution IV, to be paid **once** by whichever feature ships it first. Feature 016 is
  the expected first mover, since that machinery is its subject. **This requirement is therefore
  delivered after that store exists, not before**, and US3 carries P2 accordingly.
- **FR-011**: An environment declaring **zero** providers MUST be a coherent, supported state.
- **FR-012**: Behaviour for environments created before this feature MUST remain working, and any
  change in their effective permissions MUST be stated rather than silently applied.
- **FR-013**: The permitted set MUST be visible through the tool's existing machine-readable
  interface, so an agent operating the CLI can determine it without parsing prose.

#### Transparent enforcement (US4/US5, added 2026-08-04)

- **FR-016**: Enforcement MUST NOT depend on the agent honouring proxy environment variables.
  Outbound traffic MUST be routed to the proxy **by the network stack**, so unsetting a variable,
  editing agent configuration, or running a script that does either **changes nothing**.
- **FR-017**: The **default MUST be deny**. Any port or protocol not declared MUST fail —
  explicitly including non-standard HTTP ports (`8080`), which would otherwise be the widest hole
  in the mechanism: an agent reaching a malicious endpoint on an unusual port while the declaration
  claims to constrain it.
- **FR-018**: The declaration MUST be able to express **non-HTTP destinations** (SSH, FTP, gRPC, a
  database) as host **and port**, so an operator can permit exactly what the environment needs and
  nothing adjacent. Permitting a protocol generally is not sufficient granularity.
- **FR-018a**: All destinations MUST be declared in **one list** (`egress.allow`) of typed entries
  — `{provider}`, `{provider, hosts}`, `{host}`, or `{host, port}` — superseding the separate
  `providers:` and `allow:` keys. **The presence of a port selects the enforcement surface**: no
  port means HTTP/HTTPS through the proxy allowlist; a port means an explicit netfilter rule. The
  operator declares destinations; the tool decides which surface each needs.
- **FR-018b**: This supersedes FR-001/FR-001c's two-key syntax, which is **removed, not deprecated**
  — one way to say a thing. The replacement semantics of an explicit `hosts:` (FR-001b) survive
  unchanged, as does the `*.domain` form (FR-001d).
- **FR-019**: **No capability may be added to the agent container** (Constitution II). The
  privilege required to program the network stack MUST sit on the **proxy** container, which runs
  no untrusted code. The agent joins that container's network namespace and gains nothing.
- **FR-020**: Name resolution MUST keep working, since no declared destination is reachable without
  it. It is a dependency of the mechanism, not a permission the operator has to think about.
- **FR-021**: Where transparent enforcement cannot be delivered on a host, the existing
  `enforcement` setting governs (FR-007b) — refuse under `strict`, deploy and state the limitation
  under `advisory`. **FR-004 is unaffected**: an environment with no declaration stays unrestricted.
  Default-deny applies to environments that opted in, never retroactively to those that did not.
- **FR-022**: FR-008's honesty statement MUST be **revised, not merely extended**, once transparent
  enforcement is in force. The current wording says packet filtering "needs privileges this
  container deliberately does not have" — which is true of the **agent** container and false of the
  deployment. Left standing it would argue against the mechanism that supersedes it, and would
  understate a guarantee the tool actually delivers. Understating is a smaller sin than
  overclaiming, but it is still an inaccurate statement of what the operator is getting.

### Key Entities *(include if feature involves data)*

- **Provider**: a named model endpoint an agent can reach (e.g. the vendor an API key belongs
  to). Identified by a stable name; distinct from the *credential* that authorises it.
- **Provider declaration**: the per-environment set of permitted providers, part of the
  environment's configuration. Each entry is either a bare **name** (the tool supplies the hosts)
  or a name with an explicit **host list** that replaces them (FR-001a/FR-001b).
- **Built-in default provider**: a provider an agent will use with no operator configuration —
  the thing this feature exists to surface.
- **Egress event**: a record that a provider was reached, or an attempt was made, including
  whether it fell inside the declared set and whether it was permitted or refused.
- **Egress proxy**: the sidecar that enforces the declaration and produces egress events; shares
  the environment's compose project and lifecycle.
- **Enforcement mode**: `advisory` (default) or `strict` — whether an unenforceable declaration
  warns or refuses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every supported agent, an operator can determine the complete set of providers
  it may reach **without reading that agent's documentation** — verified for all four.
- **SC-002**: An environment that declares a provider set never reaches an undeclared provider
  **via a client that honours the proxy** without the operator being informed — **zero** silent
  occurrences. A process that ignores proxy settings and opens a direct connection is **outside
  this criterion**, as FR-008 states; measuring it would require packet filtering, which
  Constitution II forbids. Scoped deliberately: an unbounded "never" here would be an overclaim
  sitting in the success criteria of a feature whose subject is not overclaiming.
- **SC-003**: An agent with a built-in default provider is disclosed to the operator in **100%**
  of environments where no provider is declared.
- **SC-004**: The enforcement strength is stated for every supported agent — including whether
  that agent is known to honour the proxy — with **zero** cases where the tool implies a stronger
  guarantee than it delivers.
- **SC-004a**: In `strict` mode, an environment whose declaration cannot be enforced is refused —
  **zero** deployments that proceed with an unenforceable declaration.
- **SC-005**: No new privilege, capability or runtime installation is required — verified by the
  container running exactly as rootlessly as before.
- **SC-006**: An undeclared-egress event remains discoverable after the container is removed —
  **100%** of runs. Measured once FR-010 is delivered; until the durable store exists, this
  criterion is **not yet in force** rather than silently failing.
- **SC-007**: No credential value is exposed by the declaration mechanism — **100%** of runs.
- **SC-008** *(US4)*: With a declaration in force, an agent that unsets every proxy variable and
  connects directly **fails** — **zero** successful bypasses. This is the criterion that separates
  a boundary from an intention.
- **SC-009** *(US5)*: An undeclared port or protocol fails — verified for a **non-standard HTTP
  port**, SSH and FTP, with **zero** reachable undeclared destinations.
- **SC-010** *(US5)*: A declared non-HTTP destination is reachable **only** at the declared host and
  port — **zero** cases where declaring one destination admits another.
- **SC-011** *(US4)*: The agent container's capability set is **identical** to an undeclared
  deployment's — **zero** added privileges on the container running untrusted code.

## Assumptions

- **Enforcement is proxy-level, not packet-level — by scope, not by necessity.** A sidecar proxy
  genuinely refuses undeclared hosts (a real `403`, not "the agent was configured not to"), but it
  binds only clients that honour proxy settings. A process that ignores them and dials directly is
  not stopped. **This feature chooses not to do packet filtering; it is not prevented from it.**
  `NET_ADMIN` on the proxy container plus `network_mode: service:egress` would intercept
  unconditionally with the agent container holding no capability — Constitution II is
  per-container, and the capability lands where no untrusted code runs. Deferred because it
  demands SNI peeking (a `CONNECT`-based proxy cannot read a transparently redirected TLS stream),
  moves the published-port binding to the egress service (an identity migration, Constitution IV),
  and makes every non-HTTP protocol an explicit allow. See FR-008b.
- **The compose project already carries helpers.** Feature 002 established that a helper service
  in the environment's compose project shares its lifecycle, so teardown of the environment tears
  down the proxy with it. This feature adds its service to the model the tool **generates**; the
  operator's own override file continues to layer on top, untouched and still operator-owned.
- **Provider identity is by name, not by endpoint.** Operators think in vendors; the mapping from
  a name to the hosts it implies is the tool's business, and is expected to change as vendors
  change theirs.
- **What differs per agent is proxy adherence, not provider configuration.** With a proxy doing
  the enforcing, an agent's own provider settings stop being the mechanism. The per-agent question
  becomes "does it honour proxy environment variables", which must be established by running each
  agent rather than assumed from documentation.
- Declaring providers is **opt-in**; an operator who declares nothing is not broken, but they
  are informed (FR-004, FR-006).
- The container remains **rootless and immutable at runtime**; nothing here changes what is baked
  at build time.

## Out of Scope

- Network-level packet filtering, firewalls, or anything requiring added capabilities. A proxy
  is in scope precisely because it needs none.
- Auditing the *content* of what an agent sends — this feature governs *where*, not *what*.
- Per-request cost or token accounting (that is the observability feature).
- Choosing or switching providers on the operator's behalf.

## Dependencies

- **Feature 002 (lifecycle verbs / sidecars)**: the shared-lifecycle guarantee that tears the proxy
  down with the environment, and the operator override channel this feature must **not** disturb.
- **Feature 006 (agent-as-code)**: the declarative spec FR-002 places the declaration in.
- **Feature 003 / 008 (credentialing, credential managers)**: providers and credentials are
  related but distinct; the declaration must not become a second place a secret can live.
- **Feature 010 (opencode)**: the agent whose verified default-provider behaviour motivated this.
- **Feature 011 (filesystem layout)**: the declaration follows the established project/user
  configuration layering, and the repo-holds-a-locator rule.
- **Feature 009 (agent-operable CLI)**: FR-013's machine-readable exposure.
- **Feature 016 (run observability) — for FR-010 only, and not a one-way arrow.** Both features
  need the same durable per-container store and ingestion machinery, and the tenth volume it
  introduces should be paid for **once**. Whichever ships it first builds it; the other consumes
  it. 016 is the expected first mover because that machinery is its subject, whereas here it
  serves a single P2 story. **US1 and US2 — this feature's entire P1 scope — depend on none of
  it.**
- **Constitution II (rootless, immutable runtime)**: the boundary that shapes the whole design.
- **Constitution III (least exposure)**: the principle this feature extends from "where a
  credential rests" to "where data goes".
