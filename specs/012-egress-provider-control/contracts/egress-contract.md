# Contract: Egress and Provider Control

**Feature**: 012-egress-provider-control | **Date**: 2026-07-30

The interfaces this feature exposes. Entities and validation rules are in
[../data-model.md](../data-model.md).

---

## C1 — Spec schema addition

`validate_environment` gains one optional key.

```yaml
egress:
  providers:                       # optional; entries are names OR {name, hosts}
    - anthropic                    #   short form — tool supplies the hosts
    - name: openai                 #   long form — indirect endpoint (FR-001a)
      hosts: [llm.corp.internal]   #   REPLACES the tool's mapping (FR-001b)
  enforcement: advisory            # optional; advisory | strict
```

| Case | Behaviour |
|---|---|
| `egress` absent | unrestricted; no proxy; disclosure emitted (C4) |
| `egress.providers: []` | proxy deployed, refuses everything (FR-011) |
| `egress` not a mapping | `die` naming the file and field |
| `providers` a bare string | `die` naming the field — **must not** iterate characters |
| unknown name in **short** form | `die` naming it, listing the known set |
| unknown name in **long** form | **accepted** — the hosts are authoritative and the name is a label (FR-001a) |
| long form without `hosts` | `die` — that is the short form written the long way |
| `hosts` entry with a scheme, path or port | `die` naming the field — a URL must not be silently accepted and then never match |
| unknown key inside a provider mapping | `die` naming the key |
| unknown key inside `egress` | `die` naming the key |
| `enforcement` outside the enum | `die` via `_enum_field` |

**Replacement, not extension (FR-001b)**: where `hosts` is given, the tool's mapping for that entry
is **discarded**. Additive semantics would leave the direct vendor path open for an operator who
routed through a gateway to close it — a silent over-permission while the declaration reads as
constrained.

**Guarantee**: validation runs **before any action** and makes no partial change — the existing
declarative-spec contract, unchanged.

---

## C2 — Compose model

The generated model (`build_compose_model`) gains a **second service** when a declaration is
present and enforceable.

```yaml
services:
  agent:
    environment:
      HTTPS_PROXY: http://egress:<port>
      HTTP_PROXY:  http://egress:<port>
      NO_PROXY:    <tool-controlled, minimal>
  egress:
    image: <proxy image>
    # allowlist derived from the declaration
```

| Guarantee | Why |
|---|---|
| The proxy is in the **generated** file, never `<name>.services.yaml` | that file is validated services-only and forbidden from redefining `agent`; it is operator-owned (research R4) |
| The operator override still rides as the second `-f`, on top | an operator can override the proxy — see the disclosure rule below |
| No new volume | a tenth per-container volume is an identity migration (research R9) |
| `down` / `redeploy` / `wipe` tear the proxy down | it is in the same project; nothing new to remember |
| Absent a declaration, the model is **byte-identical to today** | FR-004/FR-012 — existing environments keep working |

### Operator override of the proxy — permitted, never silent

The override file is **operator-owned and host-side**; Feature 006 already establishes that an
agent cannot reach it. So an operator redefining the `egress` service is not an attack — it is the
same authority as choosing not to declare egress at all. Forbidding it would be theatre.

**But it must never be silent.** If the merged override redefines the `egress` service:

| Requirement | Why |
|---|---|
| The tool MUST report it at deploy | the operator may not remember what an old override file does |
| `enforced` MUST read **false** in prose and `--json` | the tool did not define the running proxy and cannot vouch for its allowlist |
| Under `strict`, deployment MUST be **refused** | strict means "refuse when the declaration cannot be enforced", and a proxy we did not define is exactly that |

Claiming enforcement for a proxy the tool did not configure would be the overclaim SC-004 exists to
prevent — inside the very mechanism meant to deliver it.

**Detection must not use the column-0 regex scanner.** `_yaml_service_keys` returns `[]` for
`services: {egress: {...}}` (flow style) and for a quoted `"egress":` key, so both slip past. PyYAML
is already the project's one sanctioned dependency; `yaml.safe_load` closes this exactly.

**Behaviour change to state, not discover**: a foreground headless run passes
`--abort-on-container-exit --exit-code-from agent`, which stops every service when any one exits.
A crashing proxy therefore aborts the agent run. Fail-closed and correct; still a change.

---

## C3 — The proxy's own contract

| Requirement | Rationale |
|---|---|
| **MUST NOT terminate or inspect TLS** | it would see every `Authorization` header, creating a new plaintext credential location inside the component meant to improve least-exposure (research R2, Constitution III) |
| Allowlists on the **`CONNECT` target** | the hostname is visible before TLS is established; decryption is unnecessary |
| **MUST refuse with a status code, never drop** | a refusal returns an HTTP status the client reports immediately; dropping gives the 30–40s hangs the probe saw for `claude` and `opencode`. Verified by asserting **a status is returned**, never by timing — "fast" has no threshold (research R1a) |
| Requires **no added capability** on the agent container | Constitution II; the proxy is a separate container |
| Injects **no CA certificate** into the agent image | a durable trust change to an image meant to be immutable |

**Scope, stated**: the proxy can enforce *which host*, never *which model* or *what was sent*. The
feature governs **where**, not **what** — exactly the spec's claim.

---

## C4 — Disclosure output

**When**: once, at deploy, for an environment with no declaration whose agent has a built-in
default provider (FR-006, SC-003).

Must state:

1. that the agent can reach a provider **without the operator's credential**;
2. **which** provider, where the tool knows it;
3. that declaring `egress.providers` is how to constrain it.

**Must not**: repeat on every command, or appear when a declaration exists. The defect being fixed
is silence; the failure mode being avoided is noise that trains operators to ignore it.

---

## C5 — Enforcement-strength statement

Wherever the tool reports enforcement, it MUST state (FR-008, SC-004):

- a proxy **refuses requests from clients that honour it**;
- it does **not** stop a process that ignores proxy settings and dials directly, because this
  feature does not do packet filtering — a **scope decision, not an impossibility** (FR-008b);
- **which agents are known to honour the proxy** — from the adherence fixture, currently all four.

**Prohibited**: any phrasing implying a stronger guarantee than that. This is the requirement most
easily satisfied in appearance and violated in substance.

---

## C6 — `NO_PROXY` precedence

The tool sets `NO_PROXY` itself, to the minimum needed for in-container traffic.

| Case | Behaviour |
|---|---|
| declaration enforced, operator supplies **any** `NO_PROXY` | **refused**, naming the file and the variable |
| no declaration | the tool sets nothing; today's behaviour |

**No subset comparison is attempted, deliberately.** Deciding whether one `NO_PROXY` is "wider"
than another means comparing `*`, `.suffix` forms, bare hostnames, IP literals, CIDR blocks and
port suffixes — forms that are not even consistent between HTTP clients. A comparison that erred
in the **permissive** direction would produce exactly the silent bypass this contract exists to
prevent, and would pass every test one would naturally think to write.

Refusing outright is unambiguous, **fails closed** (a refused deploy, never a silent bypass), and
is testable as present-or-absent. It costs an operator nothing real: `NO_PROXY` for in-container
traffic is the tool's job. An operator with a genuine need should say so, and a declared way to
express it can be added — deliberately, not by defeating the check.

**This is the feature's most likely silent-failure mode** (research R3) and has a test of its own,
not a line in the docs.

---

## C7 — Machine-readable exposure

**Landing site**: `plan`/`status` under `--json`, as `data.environments[]`. Those commands emitted
*nothing* on stdout before this feature — a separate `fix(#009)` commit gave them a payload, since
FR-013 names "the existing machine-readable interface" and `status` is where an operator asks what
an environment is permitted to reach. They take **no** environment name; the caller filters.

The existing `--json` envelope (Feature 009) gains, per environment:

| Field | Meaning |
|---|---|
| `egress.declared` | whether an `egress:` block exists at all |
| `egress.unrestricted` | **the field that disambiguates an empty `destinations` list.** Undeclared and `allow: []` both have no destinations and are *opposites*; a caller must never infer which from emptiness |
| `egress.providers` | the provider labels resolved out of `allow` |
| `egress.destinations` | the **effective** allowlist: `{label, host, port, source}` per entry. `source` (`tool`/`declaration`) must reflect an operator `hosts:` override rather than the tool's default (FR-001b), or the JSON would state a permission set the boundary does not enforce. `port` says WHICH SURFACE enforces the entry — `null` is the proxy allowlist, an integer is a netfilter rule (FR-018a), and the two have very different reach. Replaced a flat `egress.hosts`, which is no longer emitted by either branch |
| `egress.enforced` | whether the declaration is actually in force. **Distinct from `declared`** — an advisory declaration that cannot be enforced is `declared: true, enforced: false`, with `not_enforced_reason` |
| `egress.mechanism` | **WHICH enforcement was obtained** (T151/FR-021): `transparent` (packet-level default-deny) or `none`. A boolean cannot say this, and the two are not interchangeable — the packet-level boundary holds against an agent actively evading it. Emitted `none`, never `null`, for an undeclared environment: a null reads as "unknown" and invites the consumer to guess. Derived from the same one call as `enforced`, so the pair cannot drift into `enforced: true, mechanism: none` |
| `egress.enforcement` | the effective mode (`advisory`/`strict`) |
| `agent.builtin_default_provider` | the disclosure, machine-readable |
| `agent.honours_proxy` | the adherence fact |

Satisfies FR-005 and FR-013: an agent operating the CLI determines the permitted set without
parsing prose, and without reading the underlying agent's documentation.

---

## C8 — What does **not** change

| Unchanged | Why it matters |
|---|---|
| Container name, port, all nine volume names | Constitution IV; changing one orphans every running environment |
| Rootlessness, capabilities, packages in the image | Constitution II, SC-005 |
| The credential channels | FR-009 — a provider declaration is not a second place a secret can live |
| Every environment without an `egress:` key | FR-012 — behaviour identical, disclosure aside |

---

# Phase B contracts (US4/US5)

Phase A's C1–C8 hold **until Phase B lands**. These supersede them at that point.

## C9 — Schema (supersedes C1)

```yaml
egress:
  allow:
    - provider: anthropic                  # tool supplies the hosts
    - provider: openai
      hosts: [llm.corp.internal]           # REPLACES the mapping (FR-001b, unchanged)
    - host: "*.githubusercontent.com"      # HTTPS, via the proxy
    - host: github.com
      port: 22                             # non-HTTP -> a netfilter rule
  enforcement: advisory
```

| Case | Behaviour |
|---|---|
| `egress` absent | unrestricted, **unchanged and never retroactive** (FR-004, SC-015's counterpart) |
| `allow: []` | default-deny — nothing reachable |
| entry with **no** port | proxy allowlist |
| entry with a port | explicit netfilter rule; **that host and that port only**, not the protocol generally |
| both `providers:` and `allow:` present *(Phase A form)* | migrated at B2; refused after |
| unknown provider name, short form | `die` naming it (unchanged) |

## C10 — Enforcement (supersedes C2's proxy-only model)

| Guarantee | Why |
|---|---|
| `NET_ADMIN` on the **egress** service only | Constitution II is per-container; the agent runs untrusted code and gains **nothing** (FR-019, SC-011) |
| agent joins via `network_mode: service:egress` | routing is done by the network stack, not by the agent's cooperation |
| **default-deny** on OUTPUT | FR-017 — allowing everything but 80/443 leaves the widest hole |
| 80/443 REDIRECT → squid | SNI-based allowlist |
| 53 REDIRECT → dnsmasq | FR-020a — the agent cannot pick its own resolver |
| declared `{host, port}` → explicit ACCEPT | FR-018/SC-010 |
| **no TLS termination** — `peek` + `splice`, never `bump` | R2/R12; bumping would expose every `Authorization` header |

**The published port moves to the egress service.** A shared namespace has one port owner. The port
*number* is unchanged — so the identity lock still passes, **which is why this needs handling
deliberately rather than being left to a test that cannot see it**.

## C11 — Resolution (FR-020)

Allowlist-only. Declared names resolve; everything else does not — *you can only resolve what you
are allowed to reach*.

**Why forwarding is not enough**: a resolver that faithfully asks Cloudflare still resolves
`<payload>.attacker.com`, and the payload has left. **The exfiltration is in the question.**

**Open (FR-020e)**: `local=/#/` yields **NXDOMAIN** — "no such host" — where **REFUSED** would
honestly say "policy". Settle in B1 before the error path is designed around the wrong signal.

## C12 — The honesty statement, rewritten (FR-022)

Phase A's statement says enforcement is proxy-level and does not stop a process that dials
directly. **Under Phase B that sentence becomes false** — and leaving it would understate the
control as badly as overclaiming overstates it.

It must state instead: enforcement is **packet-level and does not depend on the agent's
cooperation**; what remains outside are sidecars deliberately placed outside the boundary
(FR-023b), each **named**.

**The Phase A overclaim test must be rewritten, not deleted.** It asserts absence of "guarantee",
"blocks all", "prevents all" — some of which become defensible. Deciding *which* is B5's work, and
deleting the test instead would remove the guard at the exact moment the claims get stronger.
