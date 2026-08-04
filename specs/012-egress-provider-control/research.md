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
MUST refuse **any** operator-supplied `NO_PROXY` while a declaration is enforced. Precedence must
be the tool's, not the env-file's.

**No subset comparison (amended, analysis finding F4).** The first draft said "refuse a value that
would *widen* it", which quietly required deciding whether one `NO_PROXY` is wider than another —
across `*`, `.suffix` forms, bare hostnames, IP literals, CIDR blocks and port suffixes, in forms
that are not consistent between HTTP clients. **A comparison erring in the permissive direction
reproduces the exact bypass this rule exists to prevent, and passes every test one would naturally
write.** Refusing outright is unambiguous, fails closed, and is testable as present-or-absent. A
genuine need for `NO_PROXY` should be expressed deliberately, not by defeating the check.

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

## R10 (VERIFIED by running each) — Proxy image evaluation

Four candidates, tested against C3's criteria on a real daemon. **Documentation would have chosen
wrong**: the smallest, most obvious candidate crashes on the exact code path this feature depends
on.

| Candidate | Size | Rootless | Disallowed host | Survives refusal? |
|---|---|---|---|---|
| `vimagick/tinyproxy` | 3 MB | yes | — | **NO — SIGSEGV (exit 139)** |
| `kalaksi/tinyproxy` | 7 MB | yes | `403 Filtered` | yes |
| `ubuntu/squid` | 66 MB | only with `pid_filename none` | `403 Forbidden` | yes |
| **Alpine + `tinyproxy` 1.11.2 (built here)** | **4 MB** | **yes, uid 65534** | **`403 Filtered`** | **yes** |

### The finding that justifies T003 existing at all

`vimagick/tinyproxy` **segfaults the instant it refuses a filtered domain** — reproducibly, twice
out of two. It logs `Proxying refused on filtered domain`, then dies with exit 139. Every piece of
documentation says tinyproxy supports domain filtering, and it does; that build just cannot survive
using it. A proxy that dies on its first refusal is not a weakened control, it is **no control from
the second request onward**.

Note that `kalaksi/tinyproxy` runs the *same software* and does **not** crash. The defect is in the
build, not in tinyproxy — which is precisely why the criterion had to be tested per-image rather
than per-project.

### Decision: build it here, from Alpine

`image/egress/` — a Dockerfile installing `tinyproxy` from Alpine's package repository, run as
uid 65534.

**Rationale, in priority order:**

1. **Supply chain.** This container *is* the egress control. Sourcing it from an unaudited personal
   Docker Hub account would put the security component itself outside the trust boundary. Alpine's
   package repo is the same class of dependency as the agent image's Debian base — already trusted
   by construction.
2. **It costs no publishing.** The tool **already builds its own image** on the target host
   (`build: {context: image/}`), so a second build context is machinery that exists. Nothing new is
   distributed; the context is one Dockerfile, negligible even over a remote context.
3. **Smallest of the four** — 4 MB, and the version is pinned by us rather than by someone else's
   rebuild cadence.

**Rejected**: `vimagick` (crashes); `kalaksi` (works well, but a personal image in the supply chain
of a security control); `ubuntu/squid` (excellent provenance and the most battle-tested forward
proxy there is — but 16× the size, needs a config workaround to run rootless, and buys nothing the
Alpine build lacks). Squid remains the fallback if Alpine's tinyproxy is ever unavailable.

**Cost accepted**: `up` now builds two images instead of one.

### R10a — `%{http_code}` cannot express a refused CONNECT (corrects the F9 amendment)

Measured, and it invalidates an assertion added while resolving analysis finding F9:

| Outcome | `curl -w '%{http_code}'` | curl exit | Visible with `-v` |
|---|---|---|---|
| allowed | `405` (the real API answered) | 0 | — |
| **refused** | **`000`** | **56** | `< HTTP/1.1 403 Filtered` |
| dropped | `000` | 28 (timeout) | nothing |

`%{http_code}` reports the **tunnelled** response, which for a refused `CONNECT` never happens — so
it reads `000` for refusals *and* drops alike. **Asserting on it would pass for a dropped
connection**, which is the exact failure C3 forbids.

**The correct assertion is the curl exit code: 56 = refused, 28 = dropped** — binary, non-timing,
and it distinguishes the two cases that matter. Quickstart S3 and T039 are corrected accordingly.

### R10c (VERIFIED) — `FilterType ere`, and the empty filter really does deny everything

Two things the design pass got wrong, both caught by building the image and running it.

**`FilterType re` is a syntax error.** A design agent read upstream `conf.c` and concluded
`FilterExtended` is deprecated in favour of `FilterType` — true — but the accepted values in the
shipped 1.11.2 are `bre|ere|fnmatch`. `re` fails config parse outright: *"Syntax error on line 10.
Unable to parse config file. Not starting."*

**`ere` is load-bearing, not a preference.** The generated wildcard pattern
`^([A-Za-z0-9_-]+\.)*githubusercontent\.com$` depends on ERE grouping and `+`. Under `bre` those
are **literal characters**, so the pattern matches nothing and the host is silently denied —
fail-closed, but broken in a way that reads as a policy decision rather than a bug.

**The catastrophic case, measured.** `providers: []` generates an **empty** filter body. With
`FilterDefaultDeny Yes` that must deny everything; had it meant allow-all, the air-gapped state
would have been wide open, silently and totally. Probed against filters generated by the real
`build_egress_filter`:

| Declaration | `api.anthropic.com` | `objects.githubusercontent.com` | `api.openai.com` / `github.com` |
|---|---|---|---|
| `providers: [anthropic]`, `allow: ["*.githubusercontent.com"]` | exit 0 | exit 0 (wildcard) | **exit 56** |
| `providers: []` | **exit 56** | — | **exit 56** |

Empty denies everything. Image is **3.9 MB**, rootless, config parses with no deprecation warning.

---

### R10b — the allowlist must ride the compose `configs` channel

Discovered while probing: a host bind of the filter file **fails over the Lima/remote daemon**
(`error while creating mount source path … permission denied`). Same lesson as Features 001/003 —
injected material must travel by compose `configs`, never a bind. The generated allowlist is
injected material, so this is a constraint on the implementation, not a probe artifact.

---

## R11 (VERIFIED by probe) — Transparent, default-deny enforcement is achievable with no agent privileges

The env-var mechanism (US1–US3) binds only clients that **choose** to honour it. An agent prompted
into `unset HTTPS_PROXY`, or into writing that line to `~/.agent-env/env`, defeats it completely —
and a prompt-injected agent is exactly what this container exists to contain. US4/US5 close that.

**Architecture** — the Istio/Linkerd sidecar pattern:

```yaml
egress:
  cap_add: [NET_ADMIN]              # the ONLY privileged piece; runs no untrusted code
agent:
  network_mode: "service:egress"    # joins that netns; cap_add: NOTHING
```

Rules installed inside the shared namespace by the **proxy**:

```text
nat OUTPUT     REDIRECT tcp 80,443 -> transparent proxy port, exempting the proxy's own uid
filter OUTPUT  POLICY DROP                     <- everything undeclared fails
               ACCEPT -o lo                    <- redirected traffic lands here
               ACCEPT ESTABLISHED,RELATED
               ACCEPT udp/tcp 53               <- DNS; nothing reachable works without it
               ACCEPT --uid-owner <proxy>      <- the proxy may egress
               (declared non-HTTP destinations appended here, host+port)
```

**Measured**, agent running as uid 1000 with **no proxy environment variables at all**:

| Attempt | Result |
|---|---|
| `8080` undeclared — *the non-standard-port bypass* | **blocked** |
| `1337` arbitrary | **blocked** |
| `22` SSH undeclared | **blocked** |
| `21` FTP undeclared | **blocked** |
| `80` / `443` | **redirected to the proxy** — 8 packets on the REDIRECT rule |
| `53` DNS | reached |
| Agent container `CapAdd` | `[]` |

`iptables` reported `policy DROP 18 packets` and `24 packets` accepted on `lo`, so both halves are
confirmed: undeclared traffic is dropped, HTTP/HTTPS is intercepted rather than passed.

### R11a — the default is the whole design

A first sketch used `-P OUTPUT ACCEPT` with REDIRECT on 80/443 only. **Port 8080 sails straight
through that**, which is worse than no control: the declaration reads as constraining while an
agent reaches anything it likes on an unusual port. Default-deny is not a hardening step to add
later; it is what makes the mechanism a boundary rather than a speed bump.

### R11b — tinyproxy cannot serve this, and the image choice changes

A transparently-redirected HTTPS connection arrives as a **raw TLS stream**, not a `CONNECT`
request — tinyproxy has nothing to read a hostname from. Filtering by hostname without decrypting
requires **SNI peeking**: squid's `ssl_bump peek` + `splice` reads the ClientHello SNI and splices
the connection through **without terminating TLS**, so R2 and Constitution III still hold (no CA,
no `Authorization` header ever visible). `ubuntu/squid` was evaluated and rejected in R10 on size;
under US4 it becomes the leading candidate, since the criterion it lost on is now outweighed by one
it uniquely satisfies.

### R11c — consequences that are not implementation details

- **The published port moves.** With a shared namespace the agent service cannot publish ports; the
  `2200 + hash` binding moves to the egress service. The port **number** is unchanged so Constitution
  IV's value holds, but the service owning the binding changes — a **migration** for every running
  container, not an edit.
- **Constitution II is better served, not violated.** The principle is per-container: the container
  running untrusted code gains nothing. `NET_ADMIN` lands on the one running a proxy and nothing
  else. FR-008's current claim that packet filtering "needs privileges this container deliberately
  does not have" conflates *the agent container* with *any container* — FR-022 exists to fix that
  wording rather than let it argue against its own successor.
- **Non-HTTP egress becomes explicit** — which is the point (FR-018), and resolves the git-push
  collision more precisely than the HTTP-only allowlist could: SSH to a declared host and port is
  permitted exactly, rather than the protocol being allowed wholesale.

---

## R8 — Constitution check

| Principle | Effect |
|---|---|
| **II. Rootless, immutable runtime** | The proxy is a *sidecar container*, so the agent container gains no privileges, no packages and no CA certificate. |
| **III. Least exposure** | **Improves**, provided R2 holds: no TLS termination means the proxy never sees a credential. Terminating TLS would have inverted this. |
| **VI. Least dependencies** | Adds a proxy image to the deployment. Justified: it is the only way to enforce egress without privileges, and it is optional — absent a declaration, no sidecar is deployed. |

No violations. R2 is the requirement that keeps Principle III on the right side of the ledger.
