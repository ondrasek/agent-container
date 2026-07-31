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
| The operator override still rides as the second `-f`, on top | an operator can override the proxy; that is a feature |
| No new volume | a tenth per-container volume is an identity migration (research R9) |
| `down` / `redeploy` / `wipe` tear the proxy down | it is in the same project; nothing new to remember |
| Absent a declaration, the model is **byte-identical to today** | FR-004/FR-012 — existing environments keep working |

**Behaviour change to state, not discover**: a foreground headless run passes
`--abort-on-container-exit --exit-code-from agent`, which stops every service when any one exits.
A crashing proxy therefore aborts the agent run. Fail-closed and correct; still a change.

---

## C3 — The proxy's own contract

| Requirement | Rationale |
|---|---|
| **MUST NOT terminate or inspect TLS** | it would see every `Authorization` header, creating a new plaintext credential location inside the component meant to improve least-exposure (research R2, Constitution III) |
| Allowlists on the **`CONNECT` target** | the hostname is visible before TLS is established; decryption is unnecessary |
| **MUST refuse, never drop** | a refusal gives a clean, fast client error; dropping gives the 30–40s hangs the probe saw for `claude` and `opencode` (research R1a) |
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
- it does **not** stop a process that ignores proxy settings and dials directly, because packet
  filtering needs privileges Constitution II forbids;
- **which agents are known to honour the proxy** — from the adherence fixture, currently all four.

**Prohibited**: any phrasing implying a stronger guarantee than that. This is the requirement most
easily satisfied in appearance and violated in substance.

---

## C6 — `NO_PROXY` precedence

The tool sets `NO_PROXY` itself, to the minimum needed for in-container traffic.

| Case | Behaviour |
|---|---|
| operator env-file sets `NO_PROXY` wider | **refused**, naming the file — it would silently disable enforcement while the declaration still reads as enforced |
| operator sets `NO_PROXY` narrower or equal | permitted |
| no declaration | the tool sets nothing; today's behaviour |

**This is the feature's most likely silent-failure mode** (research R3) and has a test of its own,
not a line in the docs.

---

## C7 — Machine-readable exposure

The existing `--json` envelope (Feature 009) gains, per environment:

| Field | Meaning |
|---|---|
| `egress.providers` | the declared names |
| `egress.hosts` | the **effective** allowlist — so an operator sees the mapping **before** a refusal, not after. Must reflect an operator `hosts:` override rather than the tool's default (FR-001b), or the JSON would state a permission set the proxy does not enforce |
| `egress.host_source` | per entry: `tool` or `declaration` — which side supplied the hosts |
| `egress.enforcement` | the effective mode |
| `egress.enforced` | whether the declaration is actually being enforced for this agent |
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
