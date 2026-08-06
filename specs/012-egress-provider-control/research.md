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

### R10b (CORRECTED) — `configs: file:` **is** a bind; only `content:` is API-delivered

The original text said injected material must travel by compose `configs` "never a bind", implying
the `configs` channel is not one. **That is wrong**, and the code was written to match it.

Measured, twice, on Docker 29.1.5 / Compose 5.3.1:

| Form | `inspect .Mounts` |
|---|---|
| `configs: {c1: {file: /path}}` | `[{"Type":"bind","Source":"/Users/…","RW":false}]` |
| `configs: {c1: {content: "…"}}` | `[]` — genuinely API-delivered |

So a `file:` config **is a read-only bind of the local path**, and fails at container create with
`bind source path does not exist` whenever the daemon cannot see it. It works today only because
`STATE_DIR` lives under `$HOME`, which Lima happens to share — the exact macOS+Lima caveat in
CLAUDE.md. **Against a remote host reached through an ssh-forwarded socket — the project's
canonical target — the allowlist would never arrive**, so the security control would fail to
deploy on the deployment mode it most exists for.

**Decision**: the allowlist rides `content:`, inline in the generated model. It is not a
credential (only hostnames the operator wrote down), so inlining costs nothing under Constitution
III, and it closes the live-edit window a bind leaves open — with a bind, a write to the source
path would alter the allowlist of the *running* proxy.

**Worth naming**: the false claim was in the code's docstring *and* here, so the two corroborated
each other. Two statements of the same untested belief are not evidence; only running it was.

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

---

# Phase 0 Research — Phase B (US4/US5, transparent enforcement)

## R12 (VERIFIED) — Alpine's squid can peek-and-splice, and R10 is superseded

R10 chose tinyproxy on measured criteria. **Those criteria changed**, so R10 is superseded rather
than contradicted: under transparent redirection a TLS connection arrives as a raw stream with no
`CONNECT` request, so tinyproxy has **no hostname to read at all**. It is not a worse choice for
US4; it is not a candidate.

Verified against `alpine:3.21`:

| Check | Result |
|---|---|
| squid version | **6.12** |
| built with TLS | `--with-openssl`, `--enable-ssl-crtd` |
| `ssl_bump peek step1` + `splice` accepted | **yes, 0 config errors** |
| `acl … ssl::server_name` accepted | **yes** |

**Decision**: squid with `ssl_bump peek` → `splice`. It reads the ClientHello's **SNI** and splices
the connection through **without terminating TLS**, so R2 holds unchanged — no CA certificate, no
`Authorization` header ever visible. `ssl_bump bump` would decrypt and is forbidden; the
Constitution III gate in the plan flips if anyone reaches for it.

**Cost, accepted**: 66 MB against tinyproxy's 4 MB. It wins on the one criterion it uniquely
satisfies.

### R12a — squid's allowlist syntax is NOT the tinyproxy syntax

Two mistakes caught by running the parser, both of which would have shipped a broken or
over-permissive allowlist:

1. **A quoted string is a FILE PATH.** `acl x ssl::server_name "*.githubusercontent.com"` makes
   squid try to *open a file* of that name: `ERROR: Can not open file *.githubusercontent.com for
   reading`. Quoting an allowlist entry — the natural thing to do when generating YAML-derived
   config — silently produces an acl with **no entries**.
2. **Subdomains use a LEADING DOT, not `*.`** — `.githubusercontent.com`. The `*.` form Phase A
   generates for tinyproxy regexes is not squid syntax.

So the generator cannot emit one string for both surfaces. `egress_filter_line` (tinyproxy, anchored
regex) and the squid acl form are **different renderings of the same entry**, and a shared
"hostname pattern" abstraction would be wrong. That belongs in B2's design, not discovered in B4.

---

## R13 — DNS: the exfiltration is in the question

A resolver that forwards faithfully to Cloudflare still resolves `<base64-payload>.attacker.com` —
it dutifully asks upstream, which asks the attacker's nameserver, and **the payload has left**. DNS
tunnelling survives a trusted upstream entirely.

**Decision**: `dnsmasq` in the egress sidecar, **allowlist-only** (`local=/#/` returning NXDOMAIN
for everything undeclared), with port 53 **redirected by netfilter** so an agent cannot pick its own
resolver. Composes exactly with default-deny: *you can only resolve what you are allowed to reach.*

**Open for B1** (FR-020e): `local=/#/` returns **NXDOMAIN**, which tells the client "no such host"
rather than "refused". `REFUSED` is the more honest signal and distinguishes policy from reality —
worth confirming dnsmasq can emit it before the error path is designed around NXDOMAIN.

---

## R14 — What Phase A leaves behind, and what breaks

| Phase A asset | Under Phase B |
|---|---|
| the anchored tinyproxy filter generator | **replaced** — squid acl syntax (R12a) |
| `egress_permits_host` | **kept** — still the pre-deploy check, must switch rendering |
| the `NO_PROXY` refusal (C6) | **kept, and cheaper to justify** — the vars are now diagnostics, so an operator unsetting them loses good errors but gains no reach |
| FR-003c's HTTPS push check | **kept, and needs an SSH arm** — default-deny kills `git push` over SSH unless port 22 is declared |
| `--json` `enforced` field | **kept**, but its meaning strengthens — B5's problem |
| the two-key schema | **migrated** at B2, per FR-018b and the plan's opening decision |

**The identity migration is the item with no Phase A analogue.** Under `network_mode:
service:egress` the published port moves to the egress service. The port *number* is unchanged, so
the identity lock passes — **which is exactly why it must be handled deliberately rather than left
to a test that cannot see it.**

---

## R15 (VERIFIED) — T102/T104: the Phase B mechanism works, and the agent cannot switch it off

Probed before writing any committed code, because if this failed the phase had no mechanism.

**Architecture**: egress container holds `CAP_NET_ADMIN` and installs the rules; the agent joins its
network namespace (`--network container:egress`) with **`CapAdd: []`** and **zero proxy environment
variables**.

### T104 — the agent gains nothing

| | |
|---|---|
| agent `CapAdd` | **`[]`** |
| egress `CapAdd` | `[CAP_NET_ADMIN]` |
| agent `NetworkMode` | `container:<egress>` |
| proxy env vars in the agent | **0** |

Constitution II is *better* served than by Phase A: the container running untrusted code holds no
privilege at all, and the privilege that exists sits where no untrusted code runs.

### T102 — it splices, it does not bump

Certificate seen by the agent for a **declared** host:

```text
subject=CN=api.anthropic.com
issuer=C=US, O=Google Trust Services, CN=WE1
```

**The real certificate.** Had this shown a squid-generated CN, that would be `bump` — TLS
terminated, every `Authorization` header visible, R2 and Constitution III broken. It is `splice`:
squid reads the ClientHello SNI and passes bytes through without terminating.

### The enforcement half — measured

| Attempt | Exit | Meaning |
|---|---|---|
| declared HTTPS | **0** | reachable |
| undeclared HTTPS | **35** | squid terminated on SNI |
| undeclared **after `unset` of every proxy variable** | **35** | *unchanged* — **this is the feature** |
| `http://example.com:8080` | **28** | dropped by default-deny |
| `http://example.com:1337` | **28** | dropped |
| ssh to an undeclared host:22 | **1** | dropped |

**Under Phase A the third row returns 0.** The agent unset everything available to it and reached
nothing. That difference is US4.

Ports 8080/1337 failing is US5's default-deny working — the hole the first design sketch left, and
the reason `-P OUTPUT DROP` is the policy rather than a REDIRECT of 80/443 alone.

### Rule shape that made it work

The proxy's own traffic must be exempted by **uid**, or the REDIRECT loops:

```sh
iptables -t nat -A OUTPUT -p tcp --dport 443 -m owner ! --uid-owner "$SQUID_UID" -j REDIRECT --to-port 3129
iptables -A OUTPUT -m owner --uid-owner "$SQUID_UID" -j ACCEPT
iptables -P OUTPUT DROP
```

`-m owner` is available in the Alpine `iptables` package and is the cleanest exemption — the
alternative (exempting by destination) would have to enumerate the allowlist twice, in two
syntaxes, and could drift.

**Consequence for T101**: the entrypoint must resolve the squid uid at runtime rather than
hard-coding it, and must install rules **before** exec'ing squid — a window where the rules are
absent but the proxy is up is a window where the agent is unconstrained.

---

## R16 (VERIFIED) — T103: allowlist-only DNS works, and FR-020e forces the resolver choice

Both candidates run; the difference is the **response code**, which is exactly what FR-020e is
about.

### dnsmasq — works, but can only lie

| Query | Result |
|---|---|
| declared `api.anthropic.com` | `NOERROR` → `160.79.104.10` |
| declared wildcard `raw.githubusercontent.com` | `NOERROR` → `185.199.109.133` |
| undeclared `api.openai.com` | **`NXDOMAIN`** |
| tunnelling-shaped `ZXhmaWx0cmF0ZWQ.attacker.example.com` | **`NXDOMAIN`** |

The allowlist itself is correct — including that a **tunnelling-shaped label does not resolve**,
which is the point: DNS exfiltration rides in the *question*, so a faithful upstream carries it out
regardless. Refusing to ask is the only thing that closes it.

But `local=/#/` returns **NXDOMAIN**, which tells the client *"this name does not exist"* when the
truth is *"policy forbids asking"*. `dnsmasq --help` has no rcode option; `--bogus-nxdomain` is
unrelated. **dnsmasq cannot satisfy FR-020e.**

### unbound — can say what it means

`unbound 1.22.0` with `local-zone: "." refuse` plus per-name `forward-zone` entries:

```text
undeclared api.openai.com  ->  status: REFUSED
```

**Decision: unbound, not dnsmasq.** FR-020e requires a refusal be distinguishable from a genuine
"no such host", and only one candidate can express it.

**Why it matters beyond honesty**: NXDOMAIN is a *cacheable negative answer*, and a client that
caches it will keep failing after the operator fixes the declaration — a policy error that presents
as a DNS bug and outlives its cause. `REFUSED` is not cached the same way.

**Cost, accepted**: unbound is heavier than dnsmasq's ~1 MB, and this replaces the R13 sketch.
Recorded as superseding it, not contradicting it — R13 argued *allowlist-only resolution*, which
stands; only the daemon changes, and it changes for a requirement R13 did not weigh.

**Consequence for the plan**: the Phase B image is `squid + unbound + iptables`. The DNS surface's
generator emits `forward-zone` blocks per declared name rather than dnsmasq `server=/…/` lines —
a third rendering of the same list (data-model §7), which is why the renderings were kept separate.

---

## R17 — T100/T101 built; forcing DNS by NAT is UNRESOLVED

The Phase B image exists and the boundary works. One sub-problem does not, and it is recorded here
rather than left for someone to rediscover.

### What the built image proves

| Property | Result |
|---|---|
| squid `peek` → `splice`, never `bump` | ✅ real server certificate reaches the agent |
| default-deny (`-P OUTPUT DROP`) | ✅ ports 8080/1337 dropped |
| evasion by `unset` of every proxy variable | ✅ still blocked |
| agent capability set | ✅ `[]`; `NET_ADMIN` only on the proxy |
| unbound allowlist-only | ✅ declared `NOERROR`, undeclared/tunnelling-shaped **`REFUSED`** |

**Two config defects were found by running it, both of which would have shipped:**

1. **Squid needs a non-intercept forward-proxy port.** With `http_port`/`https_port` both marked
   `intercept`, squid builds its internal URLs with port `0` and dies:
   `FATAL: mimeLoadIcon: cannot parse internal URL: http://…:0/…`. A loopback-only `http_port
   127.0.0.1:3127` satisfies it and is never advertised to the agent.

2. **`local-zone: "." refuse` shadows `forward-zone`.** Declared names were `REFUSED` along with
   everything else — an allowlist permitting **nothing**. Each declared name needs an explicit
   `local-zone: "<name>" transparent` to escape the catch-all.

   Worth naming: this is exactly the failure analysis finding **A1 / T136a** predicted — *"an
   allowlist-only resolver that resolves NOTHING passes every refusal test"*. Every refusal check
   passed while the resolver was completely broken. The positive-case task existed before the bug
   did, and still only caught it because it was run.

### UNRESOLVED — FR-020a, forcing port 53 to the sidecar resolver

unbound answers correctly **at the container's own address** (`dig @172.17.0.2` → `NOERROR`). What
does not work is making an agent that queries something else land there:

| Approach | Result |
|---|---|
| `REDIRECT --to-port 53` | rule fires (29 pkts counted) but no reply — needs `route_localnet`, and `/proc/sys` is **read-only** in the container |
| `--sysctl net.ipv4.conf.all.route_localnet=1` at run | no change |
| `DNAT --to-destination <container-ip>:53` | no reply; also broke direct `@127.0.0.1` queries |
| `DNAT` with `! -d <container-ip>` | still no reply |

**Note the earlier gates were not affected**: R15 simply `ACCEPT`ed port 53 rather than redirecting
it, which is why the mechanism verified cleanly there. The redirect is new here and is the only
part that fails.

**Most promising next step**, untested: give the agent service `dns: [<egress-ip>]` so the normal
path needs no NAT at all, and keep NAT solely to catch a hardcoded external resolver. Requires
confirming compose permits `dns:` alongside `network_mode: service:` — if it does not, the resolver
address has to reach the agent another way.

**Until this is settled, FR-020a is not met and T128 is not startable.** The DNS allowlist would be
advisory: an agent that picks its own resolver walks around it, and DNS is the channel whose
payload rides in the *question*.

---

## R18 (VERIFIED) — FR-020a is met by DROPPING port 53, not by redirecting it

R17 left this unresolved after four NAT approaches failed. The answer is that **the NAT was the
wrong idea**, and the default-deny policy US5 already requires does the job on its own.

### The route that looked most promising is closed

```console
$ docker compose up -d          # agent: network_mode: service:egress, dns: [127.0.0.1]
Error response from daemon: conflicting options: dns and the network mode
```

**`dns:` cannot be combined with `network_mode: service:`.** The daemon refuses at create time, so
the resolver address cannot be delivered that way at all.

### What actually works — measured

With **no DNS NAT of any kind**, only `-P OUTPUT DROP` plus an ACCEPT for unbound's own uid:

| From the agent | Result |
|---|---|
| reach `8.8.8.8:53` | **blocked (exit 1)** |
| query our resolver for a declared name | `NOERROR` |
| `/etc/resolv.conf` writable | **yes** |
| after rewriting it to our resolver | declared names resolve |
| reach `8.8.8.8:53`, after the rewrite | **still blocked** |

**Decision: drop port 53 rather than redirect it, and have the agent's entrypoint point
`/etc/resolv.conf` at the sidecar resolver.**

### Why this is stronger than the redirect, not a workaround

A REDIRECT *answers* an agent that queries `8.8.8.8` — it silently substitutes our resolver. A DROP
means **the agent cannot reach any resolver but ours**, because reaching one requires a connection
default-deny does not permit. The property FR-020a wants — "all port-53 traffic is forced to the
sidecar resolver" — is delivered by making every other resolver *unreachable*.

It also removes a moving part: no `route_localnet`, no NAT rule whose reply path has to be
un-mangled by conntrack, and nothing that breaks a direct `@127.0.0.1` query (which the DNAT
attempt did).

**The resolv.conf rewrite is not the enforcement**, and must not be described as such. It is the
*usability* half — without it the agent's normal lookups fail. An agent that rewrites the file back
loses working DNS and gains nothing, because every resolver except ours is unreachable either way.
That asymmetry is what makes a writable `resolv.conf` acceptable here.

**Consequence for T128 and FR-020a**: the netfilter rule set gains no DNS entry at all. The work
moves to `image/entrypoint.sh` — one line, in the container the agent already controls, whose
failure mode is a broken lookup rather than a silent bypass.

---

## R19 (VERIFIED) — Docker's embedded DNS bypasses the boundary over loopback

Found by the US4 acceptance tests failing against real containers. **The mechanism
is sound; the integration has a hole**, and it only appears on the network compose
actually creates.

| Network | agent's nameserver | undeclared name |
|---|---|---|
| default bridge | `10.0.2.3` (external) | **refused** — dropped by policy |
| **user-defined** (what compose makes) | **`127.0.0.11`** | **RESOLVES** |

Docker runs an embedded resolver at `127.0.0.11` inside every container on a
user-defined network. The agent reaches it **over loopback**, which
`-A OUTPUT -o lo -j ACCEPT` permits, and the resolver then forwards the query
**outside the network namespace** — where no rule of ours applies. The DNS
allowlist is therefore inert in exactly the deployment shape that matters.

The default-bridge probes that verified the mechanism (R15, R18) were not wrong,
but they tested the easier case. **Compose always creates a user-defined network**,
so every real deployment has this.

### Two fixes, both required

1. **Point the agent's `/etc/resolv.conf` at our resolver** (T128, already planned)
   — otherwise ordinary lookups go to `127.0.0.11` by default.
2. **Narrow the loopback ACCEPT so it does not cover `127.0.0.11:53`.** Without
   this, a hostile agent simply queries the embedded resolver directly and the
   rewrite in (1) is advisory — which is precisely the distinction US4 exists to
   make. The loopback rule cannot stay a blanket ACCEPT.

Until both land, `test_agent_cannot_switch_enforcement_off` and
`test_declared_provider_still_resolves` are **expected failures**, marked as such
with this finding named rather than deleted or weakened.

### Also observed, unresolved

In the same acceptance run the DECLARED provider was unreachable (`curl` exit 7)
while squid was listening on 3128/3129 and the direct-bridge probe reached it
fine. Likely the same root cause — squid resolving upstream through a path the
rules treat differently — but **not confirmed**, and recorded as open rather than
assumed.

### R19a — closing the resolver hole, and what it uncovered (measured, T128)

**The hole is closed by rewriting the packet, not the configuration.** The task
originally read "point the agent's `/etc/resolv.conf` at the sidecar resolver".
That is **not implementable and would not have been sufficient**:

- The agent image ends `USER dev`, and `/etc/resolv.conf` is a daemon-owned bind
  mount. Nothing in the agent container may write it.
- Even with write access, a rewrite is **advisory** — a hostile agent ignores
  `resolv.conf` and queries `127.0.0.11` itself. US4 exists to remove exactly
  that choice.

So the rule set DNATs `127.0.0.11:53` to unbound instead. Two measurements
governed the shape:

| Attempt | Result |
|---|---|
| `-t nat -A OUTPUT` (append) | **dead rule.** The daemon has already installed its own DNAT for `127.0.0.11:53` → `127.0.0.11:<ephemeral>`, and iptables takes the first match. Undeclared names resolved. |
| `-t nat -I OUTPUT 1` (insert) | undeclared → **REFUSED**, declared → resolves |

**The rcode is the tell.** unbound answers REFUSED; the daemon's resolver answers
NXDOMAIN. An NXDOMAIN for an undeclared name therefore means *the rules are in
the wrong position*, not that the policy is off — the two failures look identical
from the agent and are distinguishable only here.

**The ephemeral port behind it is a second, separate hole.** The DNAT matches
dport 53 only, while the daemon's resolver also answers on the high port its own
rule targets. Asking that port directly walked straight past the rewrite
(measured: it answered). A filter `-d 127.0.0.11 -j DROP` closes it and *cannot*
catch the rewritten traffic, because by the filter table the destination is
already `127.0.0.1`.

Docker-specific: podman puts aardvark-dns on the gateway address, not loopback,
where the default-deny policy already covers it.

### R19b — the `curl` exit 7 from R19, resolved: two defects, not one

R19 recorded an unconfirmed exit 7 on the DECLARED provider. It was **two**
independent defects, both now measured.

1. **`EGRESS_PORT` was still 8888** — Phase A's tinyproxy port. Phase B's squid
   forward-proxy port is `3127`. The diagnostic layer pointed at nothing, and the
   symptom was an unreachable *declared* destination, which reads as the
   allowlist being wrong rather than as a stale constant.
2. **The target named the service (`http://egress:8888`)**, so the proxy's own
   address needed a DNS lookup that the allowlist refuses — measured as `curl`
   exit 5, "couldn't resolve proxy", once R19a landed. The agent shares the
   sidecar's netns, so the proxy *is* `127.0.0.1`. A security control whose own
   address requires permission from that control is a loop.

Both fixed. With the correct allowlist file the forward-proxy path is now clean:
declared → exit 0, undeclared → refused with a status.

### R19c — OPEN: the intercept path terminates TLS for a DECLARED host

Found while verifying R19b, and **not fixed**. On the transparent path (no proxy
variables at all — the path US4 exists for):

| Request | Expected | Measured |
|---|---|---|
| undeclared host | cannot resolve | `curl` exit 6 ✅ the DNS allowlist holds |
| **declared host** | exit 0, real server certificate | **exit 60 — certificate problem** ❌ |

squid's own access log names the cause:

```
TCP_DENIED/000 0 CONNECT 160.79.104.10:443 - HIER_NONE/-
```

**The destination is logged as an IP, not a hostname.** `ssl::server_name` never
matched, so `ssl_bump splice allowed_sni` did not fire and `ssl_bump terminate
all` did — after presenting the intercept certificate, which is what `curl` exit
60 reports.

This matters beyond availability. The Dockerfile states the client must see the
**real server certificate** and that a locally-issued CN means the configuration
"has silently become `bump` and the boundary has inverted". A declared host is
currently getting the intercept certificate on the transparent path, so the
Constitution III gate in the plan is **not** presently satisfied there. The
forward-proxy path is unaffected (`TCP_TUNNEL/200`, spliced, verified above).

Do not close US4 on the strength of the DNS result alone: refusing everything
undeclared while also breaking everything declared is the broken-closed failure
T136a exists to catch.


### R19c resolved — `http_access` was denying the intercepted connection before
### `ssl_bump` could splice it (measured, T129b)

The cause was **not** SNI parsing, and not `ssl_bump`. squid reads the SNI
correctly — `parseSniExtension: host_name=api.anthropic.com` appears in the debug
log. The connection never got that far in the decision:

An intercepted TLS connection reaches `http_access` as a **synthesised CONNECT to
the destination IP**. There is no Host header and the ClientHello has not been
peeked, so `acl allowed_http dstdomain` cannot match, `http_access deny all`
fires, and the connection is closed before `ssl_bump` runs. **The allowlist was
being enforced by the one component that cannot see the hostname.**

Fixed by deferring the decision on that port to `ssl_bump`, which runs after the
peek and does hold the SNI:

```
acl tls_intercept myportname tlsintercept
http_access allow tls_intercept
```

**`myportname`, not `localport`.** First attempt used `localport 3129` and failed
identically: on a NAT-intercepted connection squid reports the **original**
destination port (443), so the ACL never matches and the scoping silently becomes
a no-op — indistinguishable from a working rule from outside the container. The
`https_port` is now named and the ACL matches the name.

**This defers, it does not permit**, and that was proven rather than argued — by
isolating the check from DNS. With a host that unbound *will* resolve but that is
absent from squid's ACL, the connection is still terminated:

| Path | Measured |
|---|---|
| declared, transparent | exit 0, `TCP_TUNNEL/200 CONNECT api.anthropic.com:443` — **spliced** |
| resolvable but not in the ACL | **exit 35, no tunnel** — `ssl_bump` terminated it |
| undeclared (unresolvable) | exit 6 — the DNS allowlist refuses first |

Constitution III holds: `curl` returns **0** for the declared host, meaning it
verified the chain against public CAs. The self-signed intercept certificate
cannot satisfy that — presenting it is exactly the `curl` exit 60 seen before the
fix. So the client is seeing the real server certificate and the proxy is not
bumping.

**A methodology note that cost real time:** `squid -k reconfigure` silently does
not apply under `squid -N`. An `http_access allow all` experiment run that way
appeared to *refute* the http_access hypothesis, which was correct all along.
Both that and `debug_options` only took effect after a container restart with the
directive baked into the mounted config. Any squid experiment here must restart
the container, not reconfigure.

### R20 — the last failure was a READINESS RACE, not a defect in the boundary

`test_undeclared_provider_is_refused_not_dropped` kept reporting `curl` exit 7
for the DECLARED provider while isolated probes of the identical path passed.
Reproduced and measured:

| When | Result |
|---|---|
| immediately after `up` returns | **exit 7** |
| ~3 s later | **exit 0** |
| and thereafter | exit 0 |

`up` returns when compose reports the containers STARTED, which is true long
before squid and unbound are serving. The entrypoint installs netfilter FIRST —
deliberately — so during that window the agent's traffic is redirected at ports
nothing is listening on yet.

**It fails CLOSED, which is the right direction and by design.** This is not a
hole. But it is a real problem for the DIAGNOSTIC layer that FR-021/FR-022 exist
to provide: a bare connection refusal for a *declared* destination is
indistinguishable from the refusal a destination gets for not being declared. An
agent starting work immediately after deploy sees the allowlist appear wrong.

Fixed with a healthcheck on the egress service and
`depends_on: {egress: {condition: service_healthy}}` on the agent — the list form
waits only for STARTED. **Both daemons are probed, not just squid**: a resolver
that is not yet answering fails every name lookup, and that failure also reads as
a policy refusal from inside the container. The same condition is applied to
operator sidecars placed inside the boundary, which would otherwise hit the
identical window.

Two process notes, both of which cost time here:

- **`uv run --project … agent-container` runs the INSTALLED console script**, not
  the working tree. A first reproduction attempt deployed a stale build and
  showed `https_proxy=http://egress:8888` — a value already fixed in source.
  Probe through `bin/agent-container` directly. (The acceptance harness is fine:
  it uses `uv run --no-project --script`.)
- The wrong config schema proves nothing. `environments.yaml` takes a **list**
  under `environments:`; written as a mapping the declaration is simply not the
  shape the tool reads, and the deployment comes up with no boundary at all.
