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
| `hosts` | list of hostnames | what the name permits; **tool-owned**, versioned with the tool |

**Not a field**: any credential. A provider is distinct from the credential that authorises it
(FR-009). The two are related in the spec file only by sitting in the same environment block.

### Rules

- The name must be one the tool knows. An unknown name **dies naming it**, and lists the known
  set — an operator must not discover a typo when a request is refused at run time.
- `hosts` is not operator-declarable in this feature. Letting operators write raw hostnames moves
  vendor drift onto them and makes the declaration unreadable (R6, alternative rejected).
- The mapping is exposed through the machine-readable interface (FR-005/FR-013) so an operator can
  read what a name permits **before** deploying.

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
      providers: [anthropic]      # the declaration
      enforcement: advisory       # advisory (default) | strict
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `egress.providers` | list of provider names | absent | absent ≠ empty — see below |
| `egress.enforcement` | `advisory` \| `strict` | `advisory` | FR-007b |

### The three states, which are genuinely different

| State | YAML | Meaning |
|---|---|---|
| **Undeclared** | no `egress:` key | **Unrestricted, but disclosed** (FR-004). Behaviour identical to today; no proxy is deployed; the operator is told once that the agent has a built-in default it can reach without their credential |
| **Declared, non-empty** | `providers: [anthropic]` | Only those providers' hosts are reachable; everything else is refused |
| **Declared, empty** | `providers: []` | **Zero providers is a coherent state** (FR-011) — the air-gapped case. The proxy is deployed and refuses everything |

Conflating "undeclared" with "empty" would turn every existing environment into an air-gapped one
on upgrade. They are distinct by construction, and the schema must not coerce one into the other.

### Validation (extends `validate_environment`)

- `egress` must be a mapping; unknown keys inside it die naming the key — matching the existing
  spec's behaviour for `container` and `credentials`.
- `providers` must be a list of strings. A bare string is a common mistake and must die naming the
  field, not iterate the characters.
- Each name must be known (see Provider).
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

**Storage**: see plan R9. An egress-record volume would be a **tenth** per-container volume and
therefore an identity migration. These events should be rows in Feature 016's store, which pays
that cost once. Until then, FR-010 is deferred with US3.

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
