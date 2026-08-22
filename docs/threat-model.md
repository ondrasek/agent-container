# Threat model and risk assessment

**Living document.** Reconcile after every feature that changes a trust boundary, a credential
path, or the network surface. The [maintenance table](#8-maintenance) at the foot is the contract:
a feature that lands without updating it has not landed.

Read [`docs/layout.md`](layout.md) for where things live, [`docs/credentials.md`](credentials.md)
for how secrets are delivered, and [`docs/egress.md`](egress.md) for the network boundary.

## 1. What this system is, in security terms

An **always-on container running untrusted code that holds real credentials and can reach the
network**. Constitution II states it plainly: *"A container runs untrusted agent code."*

Every control below follows from taking that literally. The agent is not an occasional bug to
defend against — it is a **hostile actor by assumption**, because a prompt-injected agent is
indistinguishable from a malicious one, and this container exists precisely to bound what either
can do.

## 2. Actors and trust

| Actor | Trust | Notes |
|---|---|---|
| **Operator** | trusted | single operator assumed; multi-tenant is explicitly out of scope |
| **Agent process** | **untrusted** | may be prompt-injected via repository contents, fetched pages, MCP responses, issue text |
| **Content the agent reads** | **untrusted** | the realistic injection vector — not the operator's prompt |
| **Host / VPS provider** | semi-trusted | sees the daemon, the volumes, and anything written to disk |
| **Model provider** | semi-trusted | sees every prompt, and therefore the source |
| **Network path** | untrusted | TLS is assumed; the network is not |
| **Agent CLI vendors** | semi-trusted | installed as npm globals at build; a compromised release runs as the agent |
| **Operator sidecar** | semi-trusted | operator-authored, but the agent shares its network namespace and can drive it; one placed outside the egress boundary carries that trust into unrestricted egress |

## 3. Assets

| Asset | Where it lives | Worst case if lost |
|---|---|---|
| Model provider API keys | injected to `/run/agent-container/apikeys/…`, never a volume | billing abuse; prompt and source access under the operator's identity |
| `GH_TOKEN` | env + git credential helper (`entrypoint.sh`) | repository write across everything the token scopes |
| Agent SSH key pair | **generated in the container**, `0600` on the per-container `ssh` volume; the private half never reaches the operator's disk (019) | repository write wherever the PUBLIC half was registered — one repository, if registered as a deploy key |
| SSH host key / `authorized_keys` | compose configs, `/run/agent-container/` | container impersonation; operator session hijack |
| Workspace source | `/workspace` volume | disclosure; malicious commits pushed under the operator's identity |
| Prompt context | in flight to the provider | source disclosure to a provider nobody chose |
| The declarative spec | host-side `.agent-container/` | the agent re-governing its own constraints |
| Run records | `$XDG_DATA_HOME/agent-container/runs/` (`0600`); pending on the `-runs` volume | disclosure of what ran where, against which repository — and of any credential the operator typed into a `--task` (T15) |
| The egress boundary itself | `egress` sidecar: netfilter rules, `CAP_NET_ADMIN`, squid + unbound | unconstrained egress for every container in the environment, and no name resolution at all |
| The host | — | everything |

## 4. Trust boundaries

1. **Operator machine → container host** — SSH / docker context. Build contexts and injected
   material cross it, possibly over the network to a remote daemon.
2. **Host → container** — compose `configs`, volumes, environment. The credential-injection
   boundary. **Feature 016 made it two-way.** Every other flow across 1 and 2 runs outward from the
   operator: material is injected, and what the container produces goes to a git remote (boundary 4)
   or to logs nobody stores. A run record runs the other way — the container authors a file, and the
   tool ingests it into a **durable store on the operator's machine**. So the container is now an
   input to something the operator keeps, and everything ingestion accepts is data the untrusted
   side wrote (T16).
3. **Container → network** — the egress boundary (Feature 012). **Phase B moved this boundary out of
   the agent container.** The agent joins the egress sidecar's *network* namespace holding an empty
   capability set; the rules that govern it are installed by a container it does not share a
   filesystem or a process table with. The boundary is no longer a setting the confined party owns.
   Two further consequences of that shape:
   - **The inside is a set of containers, not one.** Every operator sidecar is inside by default
     (FR-023); `egress.sidecars_outside` is the only exit, by declaration, and each name is disclosed
     in the enforcement statement (FR-023b).
   - **Traffic between containers inside the boundary is loopback and is not filtered.** That is not
     a gap — it is what "inside" means. Placing a sidecar inside is a decision to let the agent
     drive it (T5, T14).
4. **Container → git remote** — the *sanctioned* exfiltration path, by design (Hard Constraint #1).
5. **Agent → its own governing spec** — Feature 006 FR-020.
6. **Control plane → the fleet** — Feature 017, and **the widest boundary in this document**. A
   container that manages containers: it holds a keypair whose public half the operator authorises on
   permitted hosts, so what crosses this boundary is not material but AUTHORITY. Three things about
   its shape matter more than its existence:
   - **It inverts boundary 1.** Boundaries 1 and 2 run outward from the operator's machine; this one
     puts the operator's machine-level reach *inside a container*, on the far side of a boundary
     built to confine one. The confining direction is unchanged — the control plane cannot escape its
     container — but what it can *reach* from inside is no longer a subset of what a container had.
   - **The boundary is the AUTHORISATION, not the declaration.** `control_plane_hosts` is intent an
     operator can see before deploying; actual reach is wherever the public key is authorised, which
     lives outside the container on purpose. Treating the declared scope as the boundary would be a
     control that does not control, and `revoke` — withdrawing the key — is therefore the only
     concrete narrowing.
   - **It is recursive, and not gated.** A control plane can deploy another (T17), so standing keys
     can be minted from inside the system. Scope is where the key is authorised, so a parent cannot
     constrain a child even in principle; the answer is visibility — `provenance` on every inventory
     entry — rather than an enforcement point that could not enforce.

   **Boundary 3 governs its egress like any other container's**, including the telemetry export this
   feature added (T19). That is not a courtesy: an enforced declaration that omits the collector
   blocks export, and export is fail-open precisely so the work is not blocked by its own
   observability.

Which mechanism governs a destination is selected by the declaration, not by a mode switch: an entry
without a port is enforced by the proxy allowlist, an entry with a port by an explicit netfilter rule
(FR-018a). Both mechanisms are deployed together; Phase A was not superseded and removed.

## 5. Threats and current posture

### T1 — Credential theft from the image or generated artifacts

**Mitigated.** Secrets are never baked into the image, never passed on argv, never printed. Tool-
injected material lands under `/run/agent-container/…` — **never on a volume** — and vanishes with
the container. The repository holds a **locator, never a value** (Feature 008); a `source: file`
credential that is git-tracked inside the project is refused with remediation. A sentinel test
asserts no credential value reaches any generated artifact (compose model, proxy config, `--json`).

**Residual, accepted**: an on-volume `auth.json` written by *operator-interactive login* is exempt
by design — it is the operator's own session, and the agent can read it.

**Residual, accepted, and new with 019**: the agent's SSH **private** key lives on the per-container
`ssh` volume. It is not injected — the container generates it, and no channel carries it — but it
does outlive its container, which is what the rest of this asset class does not do. That is
load-bearing rather than an oversight: a key regenerated on each boot would silently invalidate
whatever the operator registered on the forge, and the symptom would arrive days later as a push
that stopped working. **`down --purge` and `ssh-key rotate` are the revocation boundary**, and both
say so in their output — nothing else would tell the operator the registration is now dead.

**Residual, and the sentinel does not reach it**: a **run record** is a generated artifact the
sentinel deliberately does not cover, because one of its fields is operator free text and FR-002
requires it. That exemption is bounded by a closed field set rather than by a filter — see T15.

### T2 — Secrets leaking through the build context

**Mitigated by construction.** The build context **is** `image/`, not the checkout, so narrowness
is structural rather than an allowlist maintained in step with the Dockerfile. Measured during
Feature 009: an unprotected context shipped **2234 files / 23.4 MB** — including a planted `.env`
and an API key — to a daemon that may be remote.

### T3 — The agent rewrites the spec that governs it

**Mitigated.** The tool reads the declarative spec **only host-side**; the in-container copy is
delivered read-only via compose `configs`. The host-side-only read is load-bearing; the read-only
delivery is defence-in-depth. A configuration that would expose the spec writable (a `bind`
workspace over the project config directory) is refused.

### T4 — The agent reaches a model provider nobody chose

**Mitigated — Feature 012 Phase B — with one residue, T13, that is named rather than absorbed.**
Enforcement is packet-level and **no longer depends on the agent's cooperation**. The sidecar
installs `-P OUTPUT DROP` *before* exec'ing either daemon, redirects 80/443 to squid, and exempts
squid's and unbound's own traffic by uid. squid **peeks the ClientHello SNI and splices** — never
bumps — so the client verifies the real server certificate and no `Authorization` header is ever
readable by the proxy (Constitution III, R2). Resolution is allowlist-only (`unbound`,
`local-zone "." refuse` plus a `forward-zone` per declared name).

Phase A's four open bullets, each **re-measured** under Phase B:

- **unsetting `HTTPS_PROXY`** — changes nothing. Undeclared host, every proxy variable unset:
  still `curl` exit 35. Under Phase A that same probe returned 0. **That difference is the phase.**
- **`~/.agent-env/env`** — still the agent's own file, and now inert: proxy variables are no longer
  what routes the traffic.
- **non-HTTP protocols and non-standard ports** — default-denied. Ports 8080 and 1337, and ssh to
  an undeclared host on 22, are dropped. A port is reachable only because the declaration names it.
- **DNS** — closed by refusing to ask, which is the only thing that closes a channel whose payload
  rides in the *question*. An undeclared or tunnelling-shaped name gets **`REFUSED`, not
  `NXDOMAIN`**: "policy forbids asking" must be distinguishable from "no such host", and NXDOMAIN
  is a cacheable negative that would outlive the declaration error that caused it.

**The resolver hole this uncovered is worth recording**, because it existed only in the deployment
shape that actually ships. Compose always creates a user-defined network, where the daemon runs an
embedded resolver at `127.0.0.11` that the agent reaches over **loopback** and that forwards the
query *outside* the namespace — past every rule of ours. Pointing `/etc/resolv.conf` at unbound
would have been advisory (and is not even writable as `dev`); the fix rewrites the packet: a DNAT
of `127.0.0.11:53` to unbound **inserted at position 1** — appended it lands behind the daemon's own
rule and never fires — plus a filter `DROP` for the ephemeral high port the daemon's resolver also
answers on.

**Residual:** the name check does not constrain the destination address — see T13.

### T5 — Laundering egress through an operator sidecar

**Mitigated by default placement; the exception is declared, never silent.** Any sidecar the agent
can reach that has unrestricted egress **is** a bypass: `redis REPLICAOF <host> <port>`,
`postgres COPY … FROM PROGRAM`, any service that fetches a URL on request. The agent need not escape
anything — it need only ask something that already has the access. So every operator sidecar joins
the boundary **by default** (FR-023) and meets the same default-deny the agent does, and there is no
automatic allowance for the project network to reach sidecars — that would be the hidden baseline
FR-001e forbids, arriving by a different route (FR-023c).

**Residual, and declared**: `egress.sidecars_outside` deliberately places a named sidecar outside,
for the cases that genuinely need their own egress. Anything it can reach is reachable *through* it.
The tool names each one in its enforcement statement (FR-023b) instead of letting `enforced: true`
quietly cover it.

### T6 — Exfiltration through the sanctioned git push

**Not mitigated, and largely unmitigable.** Hard Constraint #1 requires every agent to commit *and*
push, because the container is ephemeral. An agent that can push can push **content of its
choosing**. Narrowing this without breaking the constraint is an open problem; the current answer
is that the remote is operator-declared and the history is reviewable.

### T7 — Privilege escalation inside the container

**Mitigated by design.** Rootless by decision: no `sudo`, no root at runtime, sshd runs as `dev` on
2222, the runtime is immutable, and every system dependency is baked at build (agents never
`apt install`). **Phase B put a real `CAP_NET_ADMIN` into the deployment**, and it lands on the
**egress sidecar**, which runs no untrusted code. The agent container's capability set is measured
as `[]` and SC-011 asserts it; the two containers share a *network* namespace only, not a
filesystem, a process table, or a capability set. This is the Istio/Linkerd sidecar pattern: the
privilege exists precisely where the untrusted code is not. The sidecar's own exposure is T14.

### T8 — Container escape / host compromise

**Out of scope.** This project's controls do not defend the kernel or the container runtime.
Rootless operation reduces blast radius; runtime and kernel patching are the host operator's
responsibility.

### T9 — Supply chain of the agent CLIs

**Not mitigated.** The agent CLIs are npm globals installed at build time. A compromised release
executes with the agent's full access — credentials, workspace, network. Version pinning and
provenance verification are unaddressed.

### T10 — Loss of work

**Mitigated by construction.** Constitution I: containers are disposable, durable state lives in
git, and every agent commits *and* pushes. Feature 012 had to add a deploy-time check (FR-003c)
because an enforced egress declaration silently broke HTTPS `git push` — a control that would have
failed **only at push time**, exactly when the work would otherwise have been preserved.

### T11 — Collision between parallel containers

**Mitigated.** Constitution IV: names, ports and volumes derive deterministically from one
identifier, and the computed values are a **stable contract** guarded by an identity-lock test.
Changing one is a migration, not an edit.

### T12 — Silent failure of a control

**Partially mitigated — and this is the recurring defect class in this codebase.** Observed and
fixed instances:

- a YAML guard that returned nothing for flow style and quoted keys, so a sidecar override could
  set `agent.environment.NO_PROXY` and defeat the egress control past a guard reporting no problem;
- unanchored proxy filter patterns, making `api.anthropic.com.attacker.net` reachable from a
  declaration naming `anthropic`;
- a hostname length that split one filter line into two *unanchored* patterns;
- an allowlist delivered by a mechanism (`configs: file:`) that is a bind mount and therefore
  cannot reach a remote daemon — documented backwards in two places that corroborated each other;
- teardown that stranded the proxy container and **exited 0**;
- **the allowlist enforced by the one component that cannot see the hostname**: on the intercept
  port, `http_access deny all` closed the connection before `ssl_bump` could peek the SNI, so every
  *declared* host broke while every refusal test still passed — broken-closed, which looks exactly
  like working;
- the ACL scoping that fix written as `localport 3129`, which never matches because an intercepted
  connection reports the **original** port 443; the scoping silently became a no-op, indistinguishable
  from a working rule when observed from outside the container (`myportname` matches);
- `local-zone "." refuse` shadowing every `forward-zone`, producing an allowlist-only resolver that
  resolved **nothing** — and passing every refusal check while doing so;
- a `pytest -k` selection spelled `nonstandard` for a test named `non_standard`, matching **no
  test** and reported as "all egress tests pass". A filter that matches nothing and a filter whose
  tests all pass look identical;
- a port-owner migration detector that answered `False` whenever enforcement was off, so `redeploy`
  — the one command that moves the port binding — was the one command that could not survive it.
  "No migration needed" is also the correct answer in the common case, which is what hid it.

**Standing countermeasures**: structural guards get *proof-that-they-can-fail* tests; honesty
statements are tested for **absence of overclaim**; and claims about mechanism are established by
running them, not by reading documentation.

### T13 — A declared *name* does not constrain the destination *address*

**Not mitigated. Inherent to splicing, measured, and stated in the tool's own output.** squid
connects the spliced session to **the address the client chose** — its access log records
`ORIGINAL_DST`, the destination the netfilter REDIRECT captured, not an address squid resolved for
itself from the SNI. Name and destination are therefore **decoupled**: a process that opens a
connection to an arbitrary address while presenting a *declared* name in its ClientHello satisfies
the allowlist and is spliced to whatever it dialled.

**What it does and does not grant.** It does not grant discovery — the agent cannot resolve a name
the declaration does not permit, so it must already hold a literal address. It does grant
**delivery**: bytes to an attacker-controlled IP, under the cover of a declared name.

**Why it is open rather than closed by wording.** Closing it means pinning each connection's
destination to the addresses the allowlist-only resolver actually handed out for that name — real
shared state between unbound and squid, and a control that would break on every short-TTL,
multi-address or CDN-fronted provider. An enforcement that fails on a declared provider's own
address rotation gets switched off, not tightened. The mechanism is named here so the next attempt
starts from the real obstacle.

**Not silent.** The transparent-mode strength statement says it in the tool's output — *"the
connection is spliced to the address the CLIENT chose, so a process that opens a connection to an
arbitrary address while presenting a declared name is not stopped by the name check"* — and a test
asserts that clause is present, on the same absence-of-overclaim principle as the rest of FR-022.

### T14 — The enforcement sidecar is new surface and a new dependency

**Newly introduced by Phase B. Accepted, with the failure direction checked rather than assumed.**
The environment now contains a container holding `CAP_NET_ADMIN` and running two network daemons,
and **every name lookup in the environment depends on it**.

- **It fails closed, and that was measured, not argued.** The rules are installed *before* either
  daemon is exec'd, so no window exists in which the agent is unconstrained. The observable cost is
  the mirror image: for ~3 s after `up` returns, a *declared* destination is refused because squid
  and unbound are not yet serving, and that refusal is indistinguishable from a policy refusal from
  inside the container. The boundary holds; the **diagnosis** is what suffers — which is why the
  sidecar carries a healthcheck probing **both** daemons and the agent (and every sidecar inside the
  boundary) waits on `service_healthy` rather than on "started".
- **A compromised sidecar is a compromised boundary.** Nothing here defends squid or unbound against
  their own vulnerabilities; they are distribution packages and share T9's supply-chain posture.
- **What the agent gains from the arrangement**: reachability of the sidecar's listening ports over
  loopback. Nothing more — the namespace is shared for networking only.

### T15 — The task text is recorded verbatim, and it is the one field a credential can arrive in

**Newly introduced by Feature 016. Accepted as a NAMED, BOUNDED exposure — stated, not filtered.**
A run record keeps the task the operator gave (FR-002), and a task is free text an operator types,
so it can contain a credential. No other field is a place the tool would put one: `repository` is
SHAs and paths read out of git, `usage` is refused unless it is numbers under identifier-shaped
keys, and every remaining field is composed by the tool or the entrypoint from what it already
knew.

**The bound is a table, not a filter.** `RECORD_FIELD_PROVENANCE` in `bin/agent-container` maps
every field to `tool` · `git` · `agent` · `operator` and has **exactly one `operator` row**. That
closure is the whole of the no-credentials claim, which is why a test asserts the table itself:
add a second free-text field and the claim becomes false while every other test still passes.

**What that closure is, exactly.** It is a statement about which fields *exist* and where the tool
*puts* values in them. Ingestion checks the field set of a record the container wrote and warns
about anything undeclared; it does not re-derive the values, which are the container's word — so
the claim is "the tool writes a credential into no field but `task`", not "no byte of a stored
record can be a credential regardless of what ran inside" (T16).

**Pattern redaction was rejected, for the reason this document catalogues under T12.** A redactor
that misses one value converts an operator's caution into misplaced confidence — a check that
passes while the thing it names is broken — and its existence licenses exactly the habit the
warning exists to discourage. Saying *the task is recorded verbatim; do not put a credential in
one* is weaker protection and strictly better information. The rule is stated in
[`docs/observability.md`](observability.md) and where a task is given.

**Where a task text ends up.** Durably in `$XDG_DATA_HOME/agent-container/runs/` on the operator's
machine, written `0600`; in transit on the `-runs` volume, where the host operator and the agent
itself can both read it — the same exposure as anything on a volume, and the reason the durable
store is not one. Ingestion warns when a stored record carries a field the build does not declare,
because the claim above covers only the fields it does.

### T16 — A run record is an account of a run, not evidence against the agent

**Newly introduced by Feature 016. Accepted, and the limit is stated rather than implied.** The
pending record lives at `/var/lib/agent-container/runs` on a volume owned `dev:dev` (`0700`) — and
the agent runs as `dev`. It is out of `/home/dev`, so no ordinary shell or agent-config write
touches it by accident, but **that is separation from accident, not from intent**: a process
running as the agent can rewrite or delete its own pending record before the tool ever sees it.

**What that does and does not undermine.** Against a crash, a SIGKILL, a failed agent or an
operator's own hand, the record is exactly what it claims — which is every case the feature was
built for. Against a *hostile* agent, the values inside a well-formed record are the container's
word, so a record must never be read as proof that a run did or did not push, change a file, or
touch a repository.

**Ingestion distrusts the boundary even where it must trust the content.** The drain is the only
door records enter the store by that the tool did not compose itself, so member names from the
tarball are **refused rather than repaired** (a directory component, a `..`, or a name that is not
a run id), oversized members are skipped, a record whose `schema` is not this build's is left on
the volume rather than misread, and nothing the parser distrusted is ever handed to the clear step
that removes files. `host` and `environment` are stamped by the **tool**, keyed off the volume it
drained — so a forged record cannot claim to belong to another environment or another host.

**Not closed by permissions.** Making the directory unwritable by the agent means a second uid
inside the container writing the record, which is a setuid helper or a privileged process in the
one place this project has none (Constitution II, T7). That trade — real privilege inside the
untrusted container, to harden a summary against an adversary who by then already holds the
credentials and the push — is not worth making, so the limit is documented instead.

## 6. Risk summary

| # | Threat | Posture | Owner |
|---|---|---|---|
| T1 | Credential theft from artifacts | **Mitigated** — the tool now writes **no** private key to the operator's disk | 003, 008, 011, 018, 019 |
| T2 | Build-context leakage | **Mitigated** | 009, 011 |
| T3 | Agent re-governs itself | **Mitigated** | 006 |
| T4 | Egress to an unchosen provider | **Mitigated** — packet-level, Phase B | 012 |
| T5 | Sidecar egress laundering | **Mitigated** — inside the boundary by default | 012 |
| T7 | In-container privilege escalation | **Mitigated** | Constitution II |
| T10 | Loss of work | **Mitigated** | Constitution I |
| T11 | Parallel-container collision | **Mitigated** | Constitution IV |
| T12 | Silent control failure | **Partial** — process, not guarantee | all |
| T14 | Enforcement sidecar: surface + dependency | **Accepted** — new in Phase B | 012 |
| T15 | Task text recorded verbatim | **Accepted** — bounded by a closed field set; now also EXPORTED by default | 016, 017 |
| T16 | A record is an account, not evidence | **Accepted** — agent-writable in transit | 016 |
| T17 | A standing key spanning two privilege levels | **Accepted** — the feature's premise; bounded by authorisation, revocable by `revoke`/`--purge` | 017 |
| T18 | The passphrase transits the tool | **Accepted** — one print, scoped to the call; the narrow Constitution III exception | 017 |
| T19 | Telemetry export as a new outbound channel | **Accepted** — governed by a 012 declaration; fail-open by design | 017 |
| T13 | Declared name ≠ declared address | **Not mitigated** — inherent to splicing | 012 |
| T6 | Exfiltration via git push | **Not mitigated** — inherent | — |
| T9 | Agent CLI supply chain | **Not mitigated** | — |
| T8 | Container escape / host | **Out of scope** | host operator |

## 7. Accepted residual risks

- **The operator is trusted absolutely.** There is no multi-tenant model and no defence against the
  operator's own machine being compromised.
- **A sanctioned channel can carry anything.** A declared provider and a declared git remote are
  both full-bandwidth egress to a hostile agent.
- **The boundary governs *where*, never *what*.** TLS is never terminated (Constitution III), so no
  content inspection is possible — deliberately, because a decrypting proxy would see every
  `Authorization` header and create a new plaintext credential location inside the component meant
  to reduce exposure. Whatever a declared destination will carry, it carries.
- **And *where* is a name, not an address** (T13). Splicing preserves the client's chosen
  destination; the allowlist checks the name it presented.
- **Everything inside the boundary can reach everything else.** The shared network namespace makes
  agent↔sidecar traffic loopback, unfiltered by construction. Putting a sidecar inside is a decision
  to let untrusted code drive it.
- **`auth.json` from interactive login is readable by the agent.**
- **A task is recorded exactly as it was typed** (T15). The tool does not redact it, because a
  redactor that misses one value is worse than none. Do not put a credential in a task.
- **A run record is the container's account of itself** (T16). It is trustworthy against crashes
  and kills — the cases it exists for — and it is not evidence against an agent that chose to edit
  it before the tool drained the volume.

## 8. Maintenance

Update the row, and the affected threat, in the same change that ships the feature.

| Feature | Reconciled | Threats touched |
|---|---|---|
| 001–011 | ✅ | baseline: T1, T2, T3, T7, T10, T11 |
| 012 Phase A (US1/US2) | ✅ | T4 → partial; T10 push check (FR-003c) |
| 012 Phase B (US4/US5) | ✅ | T4 → mitigated (packet-level); T5 → mitigated (sidecars inside by default); T7 re-stated — `NET_ADMIN` now exists, on the sidecar; §4 boundary 3 rewritten; **new: T13** (name ≠ address, measured), **T14** (sidecar as surface and dependency); T12 +6 instances |
| 012 US3 (egress records) | ⬜ | expected: T12 |
| 013 doctor / preflight | ✅ | **ADDS NO CHANNEL and RETRIEVES NO SECRET, which is the stronger half of the claim.** `doctor` is strictly read-only (FR-002): it never calls `migrate_flat_state`, `drain_host_records` or `record_inventory_creation`, and a structural test walks the transitive closure of `__code__.co_names` from the command and asserts those helpers are **unreachable** — not merely uncalled on the paths a test happened to exercise. It **touches a credential path** (T1's asset class) but only reads DECLARATIONS: for `env` it checks whether a variable is set, for `file` whether a path exists, and for `keychain`/`onepassword`/`bitwarden`/`command` only whether the resolver BINARY is on PATH. `resolve_credential_value`, `_run_resolver` and `_keychain_lookup` are all unreachable from it, so no value is ever retrieved — which is stronger than "never printed", because a value never read cannot leak through a log, a traceback, or a `--json` field somebody adds later. That also satisfies FR-009: resolving a manager credential IS the prompt, and a diagnostic that makes an operator approve a secret access to answer "is this configured" is one they will not run twice. **Newly introduced:** the report enumerates which credentials each environment DECLARES and which hosts are registered, so like Feature 014's inventory it is a **reconnaissance aid** on the operator's own machine — no secret, but a map, and one an operator will run casually and often. Nothing is written, so unlike 014 it leaves no durable artifact behind; the exposure lasts as long as the terminal scrollback. Also: an image label now carries the building CLI's version (FR-012a), which is a small, deliberate disclosure to anyone who can inspect the image — they can already read its entire filesystem. **Left open, deliberately:** the FR-012a stamp means an image discloses the tool version that built it; and `doctor` MAY start an SSH socket-forward for a provisioned host (R2, settled) — it creates none of the artifact kinds FR-002 names and outlives nothing, but a stricter reading of "changes nothing" would forbid spawning any process at all, so the line drawn is stated rather than assumed. |
| 015 kill switch | ✅ | **Turns Feature 014's record into an ACTION**, and nothing new is persisted: no credential is read, written or transported, and the only writes are to 014's own entries. **Newly introduced, as built:** one command now stops — or with `--destroy` removes, together with their volumes — every environment across every host, so an attacker with CLI access on the operator's machine has a single-command denial-of-service, and 014's inventory is now a TARGET LIST as well as a reconnaissance aid. **Mitigations actually implemented:** `--destroy` refuses without an explicit confirmation and refuses outright on a non-TTY without `-y`; the stopping form is recoverable by construction (Constitution I — durable work is pushed, not held on a volume); and the action never touches a container outside a RECORDED deployment, so an imitated container name is not enough to be affected (asserted live against a real impostor). **Left open, deliberately:** the confirmation is the only barrier on `--destroy`, and anyone who can run the CLI can also pass `-y` — this tool assumes a single trusted operator (Constitution scope), so that is a boundary this feature inherits rather than one it creates. Also: the compose PROJECT LABEL is the ownership boundary, so a container an operator attached to one of our projects by hand is stopped along with it; accepted, because acting only on the agent container would leave the egress sidecar running while the report claimed everything had stopped. |
| 014 host inventory | ⬜ | |
| 015 kill switch | ⬜ | expected: T4, T6 |
| 016 run observability | ✅ | **new: T15** (task text recorded verbatim, bounded by a closed field set), **T16** (a record is the container's account, agent-writable in transit); T1 restated — a record is a generated artifact the no-credential sentinel deliberately does not cover; §3 new asset (run records); §4 boundary 2 is now two-way — the container is an input to a store the operator keeps |
| 020 key collection | ⬜ | **expected: T1 restated, and a NEW asset in §3** — a declared list that decides WHO CAN LOG IN to every environment the tool creates. Whoever can write it grants themselves access to the whole fleet on the next deploy, which is a narrower file than the tool has previously had to defend: the inventory (014) is a reconnaissance aid, this is an authorisation source. Expected to hold PUBLIC halves only, so reading it leaks nothing — the exposure is WRITE, not read, and its mitigation is filesystem permissions on the operator's own config dir, i.e. the boundary that already protects `.port` and the compose file. **To confirm at reconciliation:** that a removed key actually loses access (FR-006 — the current union-with-persisted assembly retains every key ever injected, so a naive implementation would make this row's revocation claim false), that a private key placed there is refused rather than transmitted, and whether a project-level collection can be introduced by a repository the operator merely cloned. |
| 017 control plane | ✅ | **INTRODUCES A NEW TRUST BOUNDARY, and it is the largest one this tool has.** §4 gains a fourth boundary: a container that manages containers. **What it holds:** a keypair whose public half the operator authorises on permitted hosts, so a session in it reaches a sandbox shell AND machine-level daemon access — the same key stops and destroys, not only inspects. **new: T17** — a STANDING key, not a per-deployment one, deliberately: a key that could not reach containers created later would defeat the point. Whoever holds the volume *and* the passphrase holds both privilege levels. **Mitigations actually implemented:** the private half is generated IN-CONTAINER and passphrase-encrypted at rest (the only encrypted key in this tool), so possessing the volume alone is not enough; the key is LOCKED whenever no operator is attached and no ssh-agent is started at boot; `StrictHostKeyChecking yes` rather than the agent image's `accept-new`, because this container reaches hosts the tool already pinned and first-contact acceptance from here would accept an unpinned host silently; reach is bounded by where the public key is AUTHORISED, which is outside the container by construction, so the declared scope is intent and the authorisation is the boundary; `revoke` withdraws the key fleet-wide in one command and `--purge` is the other revocation boundary; and the image installs NO agent CLI or runtime (FR-015a), enforced by a census parameterised over every Dockerfile that fails on one it has no expectation for. `panic` from inside EXCLUDES its own container and says so as a first-class outcome — not to protect the container but to protect the REPORT, which would otherwise never be delivered because the reporter is the first casualty. **new: T18** — the PASSPHRASE crosses the tool once. This is the one place the tool touches a secret it did not receive from the operator, and it is a stated exception to Constitution III rather than a silence: generated in-container, read out of the container log once, printed, never returned, stored, logged, recorded or put in a `--json` payload; the reader returns a BOOLEAN, and a malformed block prints nothing rather than risk printing an adjacent line into a password manager. The alternatives are worse — operator-supplied means argv or an env file, and printing to the container log alone makes it durable where nothing rotates it. **No recovery** (FR-017), stated before the deploy rather than discovered after the loss. **new: T19** — telemetry export is a NEW OUTBOUND CHANNEL from every container, not only from control planes. It is governed by a Feature 012 declaration like any other egress, so an enforced boundary that does not declare the collector will block it — and export is FAIL-OPEN, so the work continues and the gap is reported rather than the container being blocked by its own observability. **T15 is widened, and this is the part to read twice:** the exported payload carries the TASK TEXT BY DEFAULT, so a collector outside the operator's trust domain inherits every task an operator typed. That is deliberate — a task is not a credential channel (FR-009f0), credentials arrive by injection, and withholding the field would design around an operator error the tool already provides the correct alternative for — but it means POINTING THIS AT A SHARED BACKEND SHARES THE TASKS. The exclusion is by NAME, never by pattern: a redactor that misses one value converts caution into false confidence, whereas omitting a named field either happens or it does not. `run_id` exports regardless, so excluding the task is cheap rather than lossy. **Left open, deliberately:** a compromised control plane acts with full authority until its key is withdrawn, and nothing detects the compromise — the mitigation is revocation, not prevention. Nesting is supported and NOT gated: a control plane can deploy another, so standing keys can grow from inside the system; scope is where the key is authorised, so a parent cannot constrain a child even in principle, and the answer is VISIBILITY (`provenance` on every inventory entry, persisted so a stopped control plane is still identifiable) rather than an enforcement point that could not enforce. `accepted` on a record means the configured endpoint returned success FOR THAT RECORD and never arrival at a backend — establishing that would need the backend's own API, the vendor coupling FR-009d forbids — so the export state is a claim about what the client saw, not about what a backend holds. And anyone who can reach the runtime can read the encrypted key off the volume; the passphrase is what stands between that and use, which is the same single-trusted-operator boundary the rest of this document assumes. |
| 014 host inventory | ✅ | **Adds a DURABLE record on the operator's machine** naming every environment and host the tool created — so §3 gains an asset that outlives every container, every host and the registry itself. What it holds: names, host short names, timestamps, an outcome, and a provisioned flag. What it CANNOT hold: anything an operator typed — the field set is closed and there is no free-text field, so unlike Feature 016's run records (whose `task` carries operator text) the no-credential property here is structural rather than stated, and a test keeps it that way. **Newly introduced:** a durable map of an operator's infrastructure sitting in `$XDG_DATA_HOME`, readable by anything running as that user — it is not secret, but it is a reconnaissance aid where no such file existed before, and it deliberately survives the `--purge` that removes everything else. **Left open:** reconciliation reads live hosts, so it inherits their trust; and `unrecorded` is reported for any container matching the tool's naming convention, which an attacker on the same daemon can imitate to make their container appear in the tool's output — the wording is careful to call it an observation, not an ownership claim, and that wording is asserted by a test. |
| 018 attach host verification | ✅ | **REMOVES an exposure rather than adding one.** Five private-host-key channels are gone (`up`/`keys`/`redeploy --host-key`, `SSH_HOST_ED25519_KEY_B64`, declarative `target: host_key`), plus a dead legacy bind path; the 0644 staged key that survived `--purge` is no longer written and an upgrade DELETES any left behind and says so. §3 loses that asset; T1 has one fewer place a private key can be written. **Newly introduced:** a tool-owned `known_hosts` under derived host state now decides whether an attach is trusted. Whoever can write it can make a substituted container verify — mitigated only by filesystem permissions on the operator's own state dir (0700), i.e. the same trust boundary that already protects `.port` and the compose file. It holds PUBLIC keys only, so reading it leaks nothing. **Left open, deliberately:** the absent-pin prompt (FR-013) accepts a key captured at attach time, which cannot detect a container that was REPLACED — the pin would be the replacement's own key. This is trust-on-first-use and is labelled as such in the prompt itself, with the fingerprint shown and `list --json` named as the non-TOFU alternative; `--trust-unpinned` lets an operator take it unattended, and no terminal means refuse rather than assume yes. A **mismatch** is never a prompt. |
| 019 agent SSH key pair | ✅ | **REMOVES an exposure and NARROWS a grant; adds no channel.** Four private-key channels are gone (`up`/`redeploy --push-key`, `SSH_PUSH_KEY_B64`, declarative `target: push_key`), together with `INJECT_PUSH_KEY_PATH`, `stage_push_injection`'s push arm and `clone_credential_precheck`; each refuses with an explanation rather than a bare "no such option". The 0644 staged key that survived `--purge` is no longer written and an upgrade DELETES any left behind and says so. With 018, **T1 now has no place at all where this tool writes a private key**, and a test walks BOTH the state dir and the user config dir with no exclusions — the `*.push_key` carve-out 018 needed is gone. The grant narrows too: `--push-key` was in practice the operator's PERSONAL key, so the container received everything that key authorised; a per-container key registered as a deploy key authorises one repository, asserted by a NEGATIVE arm (an unregistered second repository refuses it). **Newly introduced:** §3 trades an injected asset for a persisted one — the private key sits on the `ssh` volume, which outlives its container, so `--purge` and `ssh-key rotate` become the revocation boundary and both now warn that the previous registration is dead. Also `~/.ssh/config` is now tool-managed: the block is appended if ABSENT and never rewritten, so an agent's own entries survive, and a config the agent wrote first still gains `StrictHostKeyChecking` — without which every SSH it attempts hangs on a prompt it cannot answer. The FR-011 probe is outbound traffic a 012 declaration governs; it is bounded at 10s and fails **soft** (`unknown`, never `not-registered`) and never blocks a deploy, verified against a real enforced boundary. **Left open, deliberately:** an SSH clone-on-start on a FIRST boot cannot succeed — the forge has never seen the key — so that invocation exits `3` leaving a working container. An automated caller reading only the status would `down` and retry, destroying the key it was about to register; mitigated by wording, not by the code, since the code is what causes the wrong reaction. Anyone who can reach the runtime can read the key off the volume, which is the same single-trusted-operator boundary the rest of this document assumes. |
