# Implementation Plan: Egress and Provider Control

**Branch**: `012-egress-provider-control` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-egress-provider-control/`

## Summary

This feature ships in **two phases with two different enforcement mechanisms**. That is not drift;
it is the shape the problem turned out to have.

| Phase | Stories | Mechanism | Status |
|---|---|---|---|
| **A** | US1, US2 | proxy env vars + an allowlisting forward proxy | **delivered** (60 tasks) |
| **B** | US4, US5 | netfilter in a shared network namespace + forced DNS | **this plan** |

**Phase A protects against accident and misconfiguration. Phase B protects against the agent
itself.** An agent that can be prompted into `unset HTTPS_PROXY` defeats Phase A entirely, and a
prompt-injected agent is precisely what this container exists to contain. Phase A's declaration
describes an intention; Phase B makes it a boundary.

US3 (FR-010, egress records) remains deferred behind the shared durable store — unchanged.

## The decision this plan settles first

**FR-018b takes effect with Phase B, not now.** It marks the two-key `providers:`/`allow:` syntax
"removed, not deprecated" — but that syntax is what Phase A shipped, tested and released. Reading
FR-018b as immediate would mean the delivered code is broken by its own spec while nothing yet
replaces it.

So Phase A's syntax stays correct and supported **until Phase B lands**, and Phase B carries the
migration as part of its own work. This resolves analysis finding C2, and it is recorded here
rather than in a commit message because it governs every task in this plan.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell, Compose v2.

**New runtime dependencies**, all in the egress sidecar and none in the agent container:

| Component | Why this one |
|---|---|
| **squid** (replacing tinyproxy) | SNI peeking. A transparently redirected TLS stream is **not** a `CONNECT` request, so tinyproxy has no hostname to read. `ssl_bump peek` + `splice` reads the ClientHello's SNI and splices through **without terminating TLS** — R2 and Constitution III hold |
| **dnsmasq** | allowlist-only resolution (~1 MB, Alpine) |
| **iptables** | the redirect and default-deny rules |

**Privilege**: `NET_ADMIN` on the **egress** container only. The agent container's capability set
is unchanged, and SC-011 asserts it.

**Testing**: hermetic pytest for rule/config generation; acceptance for every evasion scenario —
those cannot be unit-tested, because the claim is about what a *hostile process* cannot do.

**Constraints**:

- **No capability on the agent container** (FR-019) — the whole point.
- **Default-deny** (FR-017) — anything else leaves the widest hole.
- **No TLS termination** (R2, unchanged) — peek-and-splice, never bump.
- **DNS must keep working** (FR-020), or nothing declared is reachable.
- **SSH must survive**, or `git push` dies — the Hard Constraint #1 collision, arriving from the
  opposite direction to Phase A's.

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS** — rules are generated per deploy; nothing persists |
| **II. Least Privilege** | **PASS, and better served than Phase A.** The container running untrusted code gains **nothing**; `NET_ADMIN` lands on a container running none. Constitution II is per-container. Phase A left the agent able to opt out of its own control; Phase B removes that |
| **III. Least Exposure** | **PASS, conditional on peek-and-splice.** `ssl_bump bump` would decrypt and see every `Authorization` header. This gate flips the moment anyone reaches for it |
| **IV. Deterministic Identity** | **AT RISK — see below** |
| **V. Durable Spec** | **PASS** — clarified before planning |
| **VI. Least Dependencies** | **PASS with a named cost.** squid is 66 MB against tinyproxy's 4 MB. R10's evaluation is **superseded, not contradicted** — the criteria changed, and squid uniquely satisfies the new one |
| **VII. Continuous Deployment** | **PASS** — `feat!`, breaking, minor pre-1.0 |

### Constitution IV — the one real risk

Under `network_mode: service:egress` the agent service **cannot publish ports**; the `2200+hash`
binding moves to the egress service. The port *number* is unchanged, so `port_for_name` and every
consumer still agree — but **which service owns the binding is part of the deployed shape**, and
every running Phase A environment has it on `agent`.

That is a **migration, not an edit**. T040's baseline check compares names and numbers and would
**not** catch it — which is exactly why it needs stating here rather than being discovered.

## Project Structure

```text
image/egress/            Dockerfile — squid + dnsmasq + iptables (replaces tinyproxy)
                         entrypoint: install rules, then exec squid
bin/agent-container      one declaration -> THREE generated surfaces:
                           proxy allowlist · netfilter rules · dnsmasq config
bin/tests/               generation (hermetic) + evasion (acceptance)
docs/egress.md           rewritten: enforcement becomes a boundary
```

## Design decisions carried into tasks

1. **One declaration, three surfaces.** `egress.allow` drives the proxy allowlist, the netfilter
   rules and the resolver, generated together from one list so they cannot drift apart. That is the
   argument for the unified schema (FR-018a) — not brevity.
2. **The port selects the surface** (FR-018a). No port → HTTP/HTTPS via the proxy; a port → an
   explicit netfilter rule. The operator declares *destinations*; the tool picks the mechanism.
3. **Env vars are kept and demoted** (FR-021/FR-022). A redirected TLS stream can only be refused
   by closing the socket; a `CONNECT`-aware client gets a nameable `403`. So the variables stop
   being the enforcement and become **the diagnostic layer** — the difference between "connection
   reset" and "refused: api.openai.com not declared".
4. **Sidecars join the boundary by default** (FR-023). Any sidecar the agent can reach that has
   free egress **is** a bypass — `redis REPLICAOF`, `postgres COPY … FROM PROGRAM`, anything that
   fetches a URL on request. The agent needn't escape the namespace; it need only ask something
   that already has the access.
5. **DNS is allowlist-only and forced** (FR-020a/b). Forwarding faithfully to Cloudflare still
   resolves `<payload>.attacker.com` — **the exfiltration is in the question, not the answer**.
   Only refusing to ask closes it, and port 53 is redirected so the agent cannot pick its own
   resolver.
6. **SSH is declared, not assumed.** Default-deny means `git push` over SSH fails unless port 22 is
   declared. Phase A's FR-003c check gains an SSH arm, or Hard Constraint #1 breaks the other way —
   and this time SSH is the casualty rather than the survivor.

## Phasing

**B1 — the image.** squid with peek-and-splice, dnsmasq, iptables. **Prove SNI filtering works
without decryption before anything else**; if it does not, the phase has no mechanism and
everything after it is wasted.

**B2 — generation.** The unified schema (FR-018a/b, carrying Phase A's migration) and the three
surfaces from one list.

**B3 — enforcement.** Shared namespace, the port-owner migration, `NET_ADMIN` placement.

**B4 — evasion acceptance.** Every SC-008…SC-015 scenario, driven by a deliberately *hostile*
container rather than a cooperative one.

**B5 — honesty.** FR-022's rewrite of the strength statement. It becomes much stronger, so it must
be re-tested for overclaim **in the other direction** — the Phase A test asserts absence of
"guarantee"/"blocks all", and some of that will now be defensible. Which parts, exactly, is the
question B5 answers.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| squid, 66 MB vs 4 MB | the only candidate that reads SNI without decrypting | tinyproxy — structurally cannot; a redirected stream carries no `CONNECT` |
| `NET_ADMIN` on a container | the only unconditional mechanism | Phase A's env vars — the agent can unset them |
| dnsmasq, a third daemon | DNS is an exfiltration channel a host allowlist does not close | trusting an upstream resolver — the payload is in the question |
| The port binding moves | forced by the shared namespace | keeping it on `agent` — impossible; a shared netns has one port owner |
| Two mechanisms coexist | env vars give nameable errors a socket close cannot | deleting them — every refusal becomes an opaque connection reset |
