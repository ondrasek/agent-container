# Data Model: Egress and Provider Control

**Feature**: 012-egress-provider-control | **Date**: 2026-07-30

Entities, their fields, and the rules that make a declaration valid. The wire shapes are in
[contracts/egress-contract.md](./contracts/egress-contract.md).

---

## 1. Provider

A named model endpoint an agent can reach. **Identified by a stable name, never by endpoint** —
operators think in vendors, and the name→hosts mapping is the tool's business (research R6).

| Field | Type | Notes |
|---|---|---|
| `name` | string | the operator-facing identifier (`anthropic`, `openai`, …) |
| `hosts` | list of hostnames | what the name permits. **Tool-owned by default**, versioned with the tool; **operator-overridable** per entry (FR-001a) |

**Not a field**: any credential. A provider is distinct from the credential that authorises it
(FR-009). The two are related in the spec file only by sitting in the same environment block.

### Rules

- A **bare** name must be one the tool knows. An unknown name **dies naming it**, and lists the
  known set — an operator must not discover a typo when a request is refused at run time.
- A name carrying an explicit `hosts:` list need **not** be known to the tool: that is the point of
  the escape hatch (FR-001a). The name is then a label, and the hosts are authoritative.
- An explicit `hosts:` **REPLACES** the tool's mapping for that entry, never extends it (FR-001b,
  research R6a). Additive semantics would leave the direct vendor path open for the operator who
  routed through a gateway precisely to close it.
- `hosts` entries are **hostnames** — no scheme, no path, no port. A URL must die naming the field
  rather than being silently accepted and never matching.
- The effective mapping — tool-supplied or operator-supplied — is exposed through the
  machine-readable interface (FR-005/FR-013) so an operator can read what a declaration permits
  **before** deploying.

---

## 2. Provider declaration

The per-environment set of permitted providers. Lives in the declarative spec beside the
credentials that authorise them (FR-002) — no new file, no new resolution path.

```yaml
environments:
  - name: acme
    host: local
    container: { agent: claude }
    credentials:
      - { name: ANTHROPIC_API_KEY, source: onepassword, vault: Personal, item: anthropic, field: key }
    egress:
      providers:
        - anthropic                       # short form — the tool supplies the hosts
        - name: openai                    # long form — an indirect endpoint (FR-001a)
          hosts: [llm.corp.internal]      #   REPLACES the tool's mapping (FR-001b)
      allow:                              # non-provider hosts (FR-001c)
        - github.com                      #   git push — see FR-003c
        - "*.githubusercontent.com"       #   domain + subdomains (FR-001d)
      enforcement: advisory               # advisory (default) | strict
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `egress.providers` | list of names **or** `{name, hosts}` mappings | absent | absent ≠ empty — see below |
| `egress.allow` | list of hosts, optionally `*.`-prefixed | `[]` | FR-001c/FR-001d — everything that is not a model vendor |
| `egress.enforcement` | `advisory` \| `strict` | `advisory` | FR-007b |

**`providers` vs `allow` is a readability split, not a privilege split.** Both feed one allowlist.
`providers` carries vendor *names* the tool resolves to hosts and can drift with; `allow` carries
plain hosts the operator owns. Merging them into one list would force `github.com` to masquerade as
a provider and make the declaration harder to read, not easier.

**There is no hidden baseline** (FR-001e). If a host is reachable, it is in one of these two lists.
The proxy governs **all** HTTPS egress — that is why `allow` has to exist at all.

The two entry forms are interchangeable within one list. The short form is the common case and
keeps the declaration readable; the long form appears exactly where an indirect endpoint makes it
necessary, and is self-documenting there.

### The three states, which are genuinely different

| State | YAML | Meaning |
|---|---|---|
| **Undeclared** | no `egress:` key | **Unrestricted, but disclosed** (FR-004). Behaviour identical to today; no proxy is deployed; the operator is told once that the agent has a built-in default it can reach without their credential |
| **Declared, non-empty** | `providers: [anthropic]` | Only those providers' hosts are reachable; everything else is refused |
| **Declared, empty** | `providers: []` | **Zero providers is a coherent state** (FR-011) — the air-gapped case. The proxy is deployed and refuses everything |

Conflating "undeclared" with "empty" would turn every existing environment into an air-gapped one
on upgrade. They are distinct by construction, and the schema must not coerce one into the other.

**The fourth state, and why it is refused.** `egress:` present with `enforcement:` but **no**
`providers` key is neither declared nor undeclared. Reading it as unrestricted would let
`enforcement: strict` sit in a file enforcing nothing; reading it as empty would air-gap on a key
the operator added for an unrelated reason. Both are silent, so **it is refused** — naming the
missing `providers` key. An operator wanting "no egress at all" writes `providers: []`, which says
so.

**Presence must live in the type, not in a caller's discipline.** `resolve_provider_hosts` returns
`[]` for both `None` and `{"providers": []}`, so any consumer taking `dict | None` and deriving the
allowlist from the return value alone will render an **undeclared** environment air-gapped — the
exact upgrade catastrophe above. Every consumer must branch on *presence* before resolving.

### Validation (extends `validate_environment`)

- `egress` must be a mapping; unknown keys inside it die naming the key — matching the existing
  spec's behaviour for `container` and `credentials`.
- `providers` must be a **list**. A bare string is a common mistake and must die naming the field,
  not iterate the characters.
- Each entry is either a **string** or a **mapping** with `name` (required) and `hosts` (required
  when the mapping form is used — a mapping with only `name` is the short form written the long
  way, and should die telling the operator to use the string).
- A bare-string entry's name must be known (see Provider); a mapping entry's name need not be.
- Unknown keys inside a provider mapping die naming the key.
- `enforcement` is enum-checked through the existing `_enum_field` helper.
- Validation happens **before any action**, making no partial change — the existing spec contract.

---

## 3. Built-in default provider

A provider an agent will use with **no operator configuration**. The thing this feature exists to
surface (FR-006). Verified for `opencode` by Feature 010's probe.

| Field | Type | Notes |
|---|---|---|
| `agent` | agent name | one of the supported four |
| `has_builtin_default` | boolean | whether it answers with no operator credential |
| `provider` | provider name or `unknown` | what it reaches, where determined |

**This is a test fixture, not a comment.** An agent added to `AGENTS` without a recorded value
must fail the cross-file agreement test, exactly as the existing supported-agent list does. The
failure mode being prevented is a new agent silently inheriting "no default" because nobody
probed it.

---

## 4. Proxy adherence record

Which agents are **known to honour proxy environment variables** — the fact FR-008 requires the
tool to state honestly, and the fact that decides whether `strict` can deploy.

| Agent | Honours proxy | Established by |
|---|---|---|
| `claude` | yes | research R1 — ran it |
| `codex` | yes | research R1 — ran it |
| `pi` | yes | research R1 — ran it |
| `opencode` | yes | research R1 — ran it |

Also a **test fixture**. A fifth agent defaults to *not known to honour*, so `strict` refuses it
until someone probes it — the safe default, and the opposite of what a hand-maintained comment
would give.

---

## 5. Enforcement mode

| Mode | Declaration enforceable | Declaration **not** enforceable |
|---|---|---|
| `advisory` (default) | deploy with the proxy | **deploy**, stating plainly that the declaration is not enforced for this agent |
| `strict` | deploy with the proxy | **refuse**, naming the agent and why |

"Not enforceable" means the agent is not on the adherence list, or the proxy cannot be started.
With R1's result, all four supported agents are enforceable today — so `strict` refuses only on a
proxy failure or an unprobed new agent.

The effective mode must be visible **before** deploying (FR-007b).

---

## 6. Egress event

A record that a provider was reached or an attempt was made.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO-8601 | when |
| `host` | hostname | the `CONNECT` target — **the only thing the proxy can see** (R2) |
| `provider` | provider name or `null` | resolved from `host` where the mapping knows it |
| `declared` | boolean | inside the declared set |
| `decision` | `permitted` \| `refused` | what the proxy did |

**What is deliberately absent**: request bodies, headers, tokens, model names, prompt content. The
proxy does not terminate TLS (R2), so it cannot see them — and that is the point. This entity's
narrowness is Constitution III holding.

**Storage**: see plan R9. An egress-record volume of this feature's own would be a **tenth**
per-container volume and therefore an identity migration. These events instead reuse the shared
durable store and its ingestion machinery — under **their own schema**, not as rows in a run
record. Whichever feature ships that store first pays the migration once; Feature 016 is the
expected first mover. Until it exists, FR-010 is deferred with US3.

**Silence means nothing happened** (spec US3 scenario 3) — no periodic heartbeat, no empty
records, no "0 events" noise.

---

## Relationships

```text
Environment ──1:0..1── Provider declaration ──0..n── Provider ──1:n── hostname
     │                        │
     │                        └── Enforcement mode
     │
     ├──0..n── Credential          (related, never merged — FR-009)
     ├──1:1─── Agent ──1:0..1── Built-in default provider
     │                └──1:1──── Proxy adherence record
     └──0..1── Egress proxy ──0..n── Egress event
```

The one relationship that must **not** exist is Provider → Credential. Declaring a provider must
not imply storing its credential in the project (FR-009, and Feature 011's rule that the repo holds
a locator, never a value). They are neighbours in the file, not a hierarchy.

---

# Phase B additions (US4/US5)

Phase A's entities above remain correct **until Phase B lands** (plan, opening decision). What
follows supersedes them at that point, not before.

## 7. Destination (supersedes Provider declaration, FR-018a/018b)

One list, `egress.allow`, whose entries are one of four shapes:

| Shape | Example | Surface |
|---|---|---|
| `{provider}` | `- provider: anthropic` | proxy allowlist (tool supplies hosts) |
| `{provider, hosts}` | `- provider: openai`<br>`  hosts: [llm.corp.internal]` | proxy allowlist (hosts **replace**, FR-001b) |
| `{host}` | `- host: github.com` | proxy allowlist |
| `{host, port}` | `- host: github.com`<br>`  port: 22` | **netfilter rule** |

**The port is the discriminator, and that is what makes one list coherent** rather than merely
shorter: an entry without a port is HTTP/HTTPS and joins the proxy's allowlist; an entry with a
port is anything else and becomes an explicit rule. The operator declares *destinations*; the tool
decides which of its surfaces each needs. A separate `ports:` key would force the operator to
classify their own traffic by mechanism — the tool's job, and a leak of implementation into the
declaration.

### Rendering is per-surface, and the renderings differ

**A shared "hostname pattern" abstraction would be wrong** (research R12a). The same entry renders
three ways:

| Surface | `github.com` | subdomains |
|---|---|---|
| squid acl | `github.com` | `.github.com` (**leading dot**) |
| tinyproxy regex *(Phase A)* | `^github\.com$` | `^([A-Za-z0-9_-]+\.)*github\.com$` |
| dnsmasq | `server=/github.com/<upstream>` | same, covers subdomains |

And in squid a **quoted** entry is a *file path*, not a value — quoting an allowlist entry, the
natural instinct when generating config, yields an acl with no entries and a silently empty
allowlist.

## 8. Enforcement surface

| Surface | Enforces | Failure seen by the agent |
|---|---|---|
| **netfilter** | every port and protocol; default-deny | connection refused/dropped |
| **proxy (squid)** | HTTP/HTTPS by SNI, no decryption | `403` — *nameable* |
| **resolver (dnsmasq)** | which names resolve at all | NXDOMAIN (see FR-020e) |

The three are generated from **one** list so they cannot drift apart. That is the argument for
unifying the schema — not brevity.

## 9. Boundary membership (FR-023)

| Member | Default | Why |
|---|---|---|
| agent container | **inside**, always | the thing being constrained |
| egress sidecar | is the boundary | holds `NET_ADMIN` |
| operator sidecars | **inside** | one the agent can reach with free egress **is** a bypass — `redis REPLICAOF`, `postgres COPY … FROM PROGRAM`, anything that fetches a URL. The agent needn't escape the namespace; it need only ask something that already has the access |

A sidecar may be placed **outside** deliberately (FR-023a) — but it must then be **named in the
enforcement statement** (FR-023b), or `enforced: true` quietly means "except for these three
containers".
