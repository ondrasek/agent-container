# Phase 0 Research: Egress and Provider Control

**Feature**: 012-egress-provider-control | **Date**: 2026-07-30

---

## R1 (VERIFIED) — All four agents honour proxy environment variables

The clarification identified this as the per-agent question that decides whether enforcement is
real, and said it must be established **by running each agent** rather than read from
documentation. Done, against the real image:

| Agent | Behaviour with `HTTPS_PROXY` pointed at a black hole | Honours proxy? |
|---|---|---|
| `pi` | `Connection error.` — immediate, clean, exit 1 | **Yes** |
| `codex` | retries 5×, then `stream disconnected … error sending request for url (https://api.openai.com/v1/responses)`, exit 1 | **Yes** |
| `claude` | no response; killed at 30s | **Yes** |
| `opencode` | no response; killed at 40s | **Yes** |

The control group is Feature 010's probe: with **no** proxy set, `opencode` answers within
seconds using a built-in default provider. With the proxy set it does not answer at all — so the
request went to the proxy rather than around it.

**Consequence**: FR-008's honest-strength statement is *"enforced for all four supported agents"*,
not *"enforced for some"*. That is a materially stronger feature than the spec dared assume.

### R1a — The probe's limitation, stated

The probe pointed at an **unreachable** proxy. A real allowlisting proxy **refuses** a
disallowed request with an HTTP error rather than dropping it, which should produce fast, clear
failures rather than the hangs seen for `claude` and `opencode`.

So those hangs are the **worst case, not the predicted case**. But they are a genuine risk if the
sidecar is unhealthy or starting, and FR-003 ("must not succeed silently") is satisfied either way
— a hang is not a silent success. The sidecar must **refuse, never drop**, and that is now a
design requirement rather than an implementation preference.

---

## R2 — The proxy must not decrypt, and does not need to

A forward proxy sees the target host of an HTTPS request from the `CONNECT` target — **before**
the TLS session is established, and without terminating it. Allowlisting by hostname therefore
needs **no TLS interception**.

**Decision**: the egress proxy MUST NOT terminate or inspect TLS. It allowlists on the `CONNECT`
target and passes bytes through.

**Rationale — this is a Constitution III requirement, not an optimisation.** A proxy that
terminated TLS would see every request header, including `Authorization`. That would create a new
place where a credential exists in plaintext, inside a component whose entire purpose is to be
between the agent and the network. The feature would then weaken least-exposure while claiming to
strengthen it.

It also avoids injecting a CA certificate into the agent container, which would be a durable
trust change to an image that is meant to be immutable.

**Cost, accepted**: the proxy can enforce *which host*, never *which model* or *what was sent*.
That is exactly the scope the spec claims — it governs **where**, not **what**.

---

## R3 — `NO_PROXY` is the bypass, and must be controlled

Every HTTP client that honours `HTTPS_PROXY` also honours `NO_PROXY`, which lists hosts to reach
**directly**. An operator env-file or an agent's own configuration setting `NO_PROXY=*` would
silently disable the entire feature while leaving the declaration in place — the exact failure
FR-008 exists to prevent.

**Decision**: the tool sets `NO_PROXY` itself, to the minimum needed for in-container traffic, and
MUST detect and refuse an operator-supplied `NO_PROXY` that would widen it. Precedence must be
the tool's, not the env-file's.

**This is the feature's most likely silent-failure mode** and deserves a test of its own, not a
line in the docs.

---

## R4 (REVISED after reading the code) — The proxy belongs in the *generated* compose model, not the operator override

The spec's clarification says the proxy rides "the existing sidecar channel". Reading
`bin/agent-container` shows that channel is the wrong home for it.

`resolve_sidecar_override` picks the first existing `<name>.services.yaml` and
`driver_compose_argv` rides it as a **second `-f`**. But `validate_sidecar_override` requires the
file be **services-only** and **must not redefine `agent`** — it is deliberately *operator-owned*.
Writing a tool-generated proxy into that path would either clobber an operator's file or force a
**third `-f`** and a merge-order rule nobody asked for.

**Decision**: the proxy is a second service in the model `build_compose_model` already generates,
beside `agent`. The generated file is wholly the tool's; a service added there inherits the compose
project, the lifecycle, `down`, `redeploy` and teardown **for free**, and the operator override
still layers *on top* — so an operator who wants to override the proxy can, which is a feature.

**Alternative rejected**: a third `-f`. It buys nothing the generated file does not already give
and adds a precedence rule between two tool-authored files.

**Consequence — headless foreground.** `driver_up_argv` passes `--abort-on-container-exit
--exit-code-from agent` for a foreground headless run. That stops **every** service when **any**
one exits, so a proxy that crashes aborts the agent run. That is fail-closed and correct, but it
is a behaviour change for headless users and must be stated rather than discovered.

---

## R9 — Egress records would be a **tenth volume**, and that is a migration

FR-010 needs the proxy's decisions to outlive the container, which means a volume. The on-disk
identity contract (Constitution IV, CLAUDE.md) pins **nine** per-container volumes by name, and
`--purge`, `wipe` and both shell completions all read that list. A tenth is a **migration, not an
edit** — the identity lock test (`IDENTITY_BASELINE`, `VOLUME_SUFFIXES`) will fail on it by
design, which is the guard working.

**Decision**: do not add a volume in this feature. Two routes, to be settled in tasks:

- Feature 016 already needs the same durable per-container store and will pay the identity cost
  once. 012's egress events reuse **that storage and its ingestion machinery** — but keep **their
  own schema**. They are not rows in a run record: a different producer (the proxy, not the agent)
  and a different lifetime (continuous, not at-run-end). 016's own FR-011a sets the precedent that
  a distinct concern gets a distinct schema.
- If 012 must ship FR-010 first, the tenth volume is an explicit, announced identity migration
  with the baseline updated deliberately — never a silent edit to make a test pass.

The first is strongly preferred, and it is the second reason (with R5) that FR-010 should follow
016 rather than lead it.

---

## R5 — Egress records reuse Feature 016's pattern

FR-010 requires egress events to outlive the container. Feature 016 solved the identical problem
for run records: **the container writes locally, the tool ingests on next contact**, with teardown
ingesting before removing storage.

**Decision**: reuse that pattern rather than invent a second one. The proxy writes its decisions
to a volume; the tool ingests them.

**Dependency created**: this makes 016's ingestion machinery a prerequisite for 012's FR-010, even
though the features are otherwise independent. Either 012 ships FR-010 after 016, or it builds a
narrower ingestion path it will later throw away. **Flagged for the plan's phasing** — the spec
does not mention this and it changes the delivery order.

---

## R6 — What "provider" means to the proxy

The operator declares a **provider name**; the proxy needs **hostnames**. The mapping is the
tool's, and it will drift as vendors change endpoints.

**Decision**: a table in the tool, versioned with it, with the mapping visible via the
machine-readable interface (FR-005) so an operator can see exactly what a name permits — rather
than discovering it when a request is refused.

**Alternative rejected — as the *only* form**: letting operators declare raw hostnames everywhere.
It moves the vendor-drift problem onto the operator and makes the declaration unreadable —
`anthropic` says what is meant; a list of hostnames does not.

### R6a (AMENDED, analysis finding F3) — raw hosts survive as an escape hatch

Rejecting raw hostnames outright collided with the spec's own edge case: a provider reached
**indirectly** — a corporate gateway, a self-hosted endpoint, a vendor-compatible deployment.
Under names-only, such an operator can only leave the declaration empty and get **no enforcement
at all**. The deployments most likely to want egress control would have received the least.

**Decision**: a provider entry takes either a bare name or a name plus an explicit `hosts:` list.
Names stay the default and keep R6's readability for the common case; raw hosts appear exactly
where they are needed and are self-documenting there.

**The load-bearing sub-decision**: an explicit `hosts:` **REPLACES** the tool's mapping for that
entry, never extends it. An operator who routes through a gateway is usually doing so to *close*
the direct vendor path; additive semantics would silently leave it open while the declaration read
as constrained — the exact silent over-permission this feature exists to prevent. It needs a test,
because additive-vs-replacing is invisible in a passing deployment.

---

## R7 — Enforcement mode, and what `advisory` actually means

`advisory` was chosen as the default (clarification, 2026-07-29). With R1's result, the mode's
meaning is narrower than it looked at spec time: since **all four agents honour the proxy**, a
declaration is enforceable for all of them today.

**Decision**: `advisory` means *deploy without the proxy sidecar, recording the declaration as
unenforced*; `strict` means *refuse to deploy if the proxy cannot be started or the agent is not
known to honour it*. The known-to-honour list is R1's table, and it is a **test fixture**, not a
comment — a new agent added without probing it must fail that test rather than silently inherit
"honours".

---

## R8 — Constitution check

| Principle | Effect |
|---|---|
| **II. Rootless, immutable runtime** | The proxy is a *sidecar container*, so the agent container gains no privileges, no packages and no CA certificate. |
| **III. Least exposure** | **Improves**, provided R2 holds: no TLS termination means the proxy never sees a credential. Terminating TLS would have inverted this. |
| **VI. Least dependencies** | Adds a proxy image to the deployment. Justified: it is the only way to enforce egress without privileges, and it is optional — absent a declaration, no sidecar is deployed. |

No violations. R2 is the requirement that keeps Principle III on the right side of the ledger.
