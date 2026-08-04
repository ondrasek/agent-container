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

## 3. Assets

| Asset | Where it lives | Worst case if lost |
|---|---|---|
| Model provider API keys | injected to `/run/agent-container/apikeys/…`, never a volume | billing abuse; prompt and source access under the operator's identity |
| `GH_TOKEN` | env + git credential helper (`entrypoint.sh`) | repository write across everything the token scopes |
| SSH push key | staged `0600`, injected to `/run/agent-container/push_ed25519_key` | as above |
| SSH host key / `authorized_keys` | compose configs, `/run/agent-container/` | container impersonation; operator session hijack |
| Workspace source | `/workspace` volume | disclosure; malicious commits pushed under the operator's identity |
| Prompt context | in flight to the provider | source disclosure to a provider nobody chose |
| The declarative spec | host-side `.agent-container/` | the agent re-governing its own constraints |
| The host | — | everything |

## 4. Trust boundaries

1. **Operator machine → container host** — SSH / docker context. Build contexts and injected
   material cross it, possibly over the network to a remote daemon.
2. **Host → container** — compose `configs`, volumes, environment. The credential-injection
   boundary.
3. **Container → network** — the egress boundary (Feature 012).
4. **Container → git remote** — the *sanctioned* exfiltration path, by design (Hard Constraint #1).
5. **Agent → its own governing spec** — Feature 006 FR-020.

## 5. Threats and current posture

### T1 — Credential theft from the image or generated artifacts

**Mitigated.** Secrets are never baked into the image, never passed on argv, never printed. Tool-
injected material lands under `/run/agent-container/…` — **never on a volume** — and vanishes with
the container. The repository holds a **locator, never a value** (Feature 008); a `source: file`
credential that is git-tracked inside the project is refused with remediation. A sentinel test
asserts no credential value reaches any generated artifact (compose model, proxy config, `--json`).

**Residual, accepted**: an on-volume `auth.json` written by *operator-interactive login* is exempt
by design — it is the operator's own session, and the agent can read it.

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

**Partially mitigated — Feature 012 Phase A.** Declared providers are enforced by an allowlisting
forward proxy; an undeclared host gets a real `403`, not "the agent was configured not to". All
four supported agents were verified to honour proxy settings **by running them**, not by reading
documentation.

**Not mitigated, and this is the honest core of the current posture:**

- an agent that **unsets `HTTPS_PROXY`** is not stopped — enforcement depends on its cooperation;
- a shell can override the variables via **`~/.agent-env/env`**, sourced with `set -a` by every
  interactive shell from a volume that survives teardown. The tool can neither inspect it (it is
  inside the container) nor prevent it (the agent owns its shell);
- **non-HTTP protocols and non-standard ports are entirely uncontrolled** — the proxy only sees
  what is pointed at it;
- **DNS is an open exfiltration channel.** The payload rides in the *question*
  (`<base64>.attacker.com`), so even a faithful upstream resolver carries it out.

Feature 012 Phase B (US4/US5, planned) closes all four via `NET_ADMIN` on the **proxy** container
plus a shared network namespace, default-deny, and forced allowlist-only resolution. **Until it
lands, the declaration is an intention, not a boundary** — and the tool says so in its own output.

### T5 — Laundering egress through an operator sidecar

**Not mitigated.** Any sidecar the agent can reach that has unrestricted egress **is** a bypass:
`redis REPLICAOF <host> <port>`, `postgres COPY … FROM PROGRAM`, any service that fetches a URL on
request. The agent need not escape anything — it need only ask something that already has the
access. Addressed by FR-023 in Phase B; until then, a declaration can read `enforced: true` while a
two-line redis command walks straight out.

### T6 — Exfiltration through the sanctioned git push

**Not mitigated, and largely unmitigable.** Hard Constraint #1 requires every agent to commit *and*
push, because the container is ephemeral. An agent that can push can push **content of its
choosing**. Narrowing this without breaking the constraint is an open problem; the current answer
is that the remote is operator-declared and the history is reviewable.

### T7 — Privilege escalation inside the container

**Mitigated by design.** Rootless by decision: no `sudo`, no root at runtime, sshd runs as `dev` on
2222, the runtime is immutable, and every system dependency is baked at build (agents never
`apt install`). Phase B's `NET_ADMIN` lands on the **proxy** container, which runs no untrusted
code — the agent container's capability set stays empty and SC-011 asserts it.

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
- teardown that stranded the proxy container and **exited 0**.

**Standing countermeasures**: structural guards get *proof-that-they-can-fail* tests; honesty
statements are tested for **absence of overclaim**; and claims about mechanism are established by
running them, not by reading documentation.

## 6. Risk summary

| # | Threat | Posture | Owner |
|---|---|---|---|
| T1 | Credential theft from artifacts | **Mitigated** | 003, 008, 011 |
| T2 | Build-context leakage | **Mitigated** | 009, 011 |
| T3 | Agent re-governs itself | **Mitigated** | 006 |
| T7 | In-container privilege escalation | **Mitigated** | Constitution II |
| T10 | Loss of work | **Mitigated** | Constitution I |
| T11 | Parallel-container collision | **Mitigated** | Constitution IV |
| T4 | Egress to an unchosen provider | **Partial** — Phase A only | 012 |
| T12 | Silent control failure | **Partial** — process, not guarantee | all |
| T5 | Sidecar egress laundering | **Not mitigated** | 012 Phase B |
| T6 | Exfiltration via git push | **Not mitigated** — inherent | — |
| T9 | Agent CLI supply chain | **Not mitigated** | — |
| T8 | Container escape / host | **Out of scope** | host operator |

## 7. Accepted residual risks

- **The operator is trusted absolutely.** There is no multi-tenant model and no defence against the
  operator's own machine being compromised.
- **A sanctioned channel can carry anything.** A declared provider and a declared git remote are
  both full-bandwidth egress to a hostile agent.
- **The proxy governs *where*, never *what*.** TLS is never terminated (Constitution III), so no
  content inspection is possible — deliberately, because a decrypting proxy would see every
  `Authorization` header and create a new plaintext credential location inside the component meant
  to reduce exposure.
- **`auth.json` from interactive login is readable by the agent.**

## 8. Maintenance

Update the row, and the affected threat, in the same change that ships the feature.

| Feature | Reconciled | Threats touched |
|---|---|---|
| 001–011 | ✅ | baseline: T1, T2, T3, T7, T10, T11 |
| 012 Phase A (US1/US2) | ✅ | T4 → partial; T10 push check (FR-003c) |
| 012 Phase B (US4/US5) | ⬜ | expected: T4 → mitigated, T5 → mitigated |
| 012 US3 (egress records) | ⬜ | expected: T12 |
| 013 doctor / preflight | ⬜ | |
| 014 host inventory | ⬜ | |
| 015 kill switch | ⬜ | expected: T4, T6 |
| 016 run observability | ⬜ | expected: T12 |
| 017 control plane | ⬜ | **introduces a new trust boundary** — re-run §4 |
