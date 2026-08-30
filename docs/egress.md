# Egress control — declaring where an environment may go (Feature 012)

An agent container can reach a model provider **you never chose**. That is not a hypothesis:
Feature 010's probe ran `opencode` with no operator credential at all and it answered normally,
over the network, via a built-in default provider. Nothing declared it, nothing recorded it, and
nothing would have told you.

This feature makes the reachable set **declared, enforced and visible**.

## Declaring

In the declarative spec, beside the credentials that authorise the providers:

```yaml
environments:
  - name: acme
    host: local
    container: { agent: claude }
    egress:
      allow:
        - provider: anthropic               # the tool supplies the hosts
        - provider: openai                  # an indirect endpoint…
          hosts: [llm.corp.internal]        # …whose hosts REPLACE the tool's
        - host: "*.githubusercontent.com"   # domain + subdomains, over HTTPS
        - host: github.com
          port: 22                          # a non-HTTP destination
      enforcement: advisory                 # advisory (default) | strict
      sidecars_outside: []                  # see "Sidecars", below
```

**One list, four entry shapes** — `{provider}`, `{provider, hosts}`, `{host}`, `{host, port}`.
The earlier two-key form (`providers:` beside `allow:`) was **removed, not deprecated**: a spec
still carrying `providers:` is refused with the rewrite named, because silently ignoring it would
deploy an environment permitting far less than its author wrote.

**The presence of a port selects the enforcement surface.** No port means HTTP/HTTPS filtered on
the hostname; a port means an explicit packet-filter rule for that host on that port. You declare
*destinations*; the tool decides which surface each one needs. The consequence is worth stating
directly: `{host: github.com, port: 22}` does **not** make `github.com` reachable over HTTPS, and
`{host: github.com}` does **not** open port 22.

One combination is **refused** for the same reason: `{host: "*.example.com", port: 22}`. A port
selects the packet filter, and netfilter has no wildcard destination — the rule would render as
`-d '*.example.com'`, which cannot resolve. A subtree can only be matched from the name in the TLS
handshake, which is the proxy's surface and therefore ports 80 and 443 only. So name the exact host
for that port, or drop the `port:`. It is refused at validation rather than at deploy because it
otherwise validated, was **reported as permitted**, and then did not exist.

## The three states are different, and one of them is not what you'd guess

| Declaration | Meaning |
|---|---|
| **no `egress:` key** | **unrestricted** — exactly today's behaviour, plus a one-time disclosure |
| `allow: []` | **air-gapped** — nothing outbound succeeds |
| `allow: [{provider: anthropic}]` | only those hosts reachable |

Absent and empty are **opposites**, and the tool never conflates them. If it did, upgrading would
silently air-gap every environment that has no declaration. An `egress:` block with no `allow:` key
at all is neither state, so it is refused rather than guessed.

## It governs ALL egress, not just model providers

Not by policy but by construction: the default is **deny**, so anything the declaration does not
name fails — any host, any port, any protocol, including the ones nobody thought of. An
environment that declares anything must declare everything it needs.

**This includes your git remote**, from both directions:

- **over HTTPS**, the hostname must be in the allowlist or the push is refused;
- **over SSH**, `{host: <remote>, port: 22}` must be declared or the connection never opens —
  default-deny closes port 22 like every other undeclared port.

The tool refuses to let either surprise you: if the environment pushes to a remote the declaration
does not permit, it says so **at deploy time**, naming the entry to add. Under `strict` it refuses
to deploy. Both arms escalate identically, so the severity cannot come to depend on whether the
remote's URL happens to start with `https://` or `git@`.

There is **no hidden always-permitted baseline**. If a host is reachable, you declared it.

## What enforcement actually is

**A packet-level boundary.** Routing is programmed into the network stack, so enforcement does not
depend on the agent's cooperation: a process that ignores proxy settings and opens a direct
connection is denied.

How it is built:

- the **egress sidecar** holds `NET_ADMIN` — the only privilege in the deployment — and runs no
  untrusted code;
- the **agent container joins that sidecar's network namespace** and gains nothing: its capability
  set is identical to an undeclared environment's, which is asserted rather than assumed;
- inside the shared namespace the sidecar installs `-P OUTPUT DROP`, redirects ports 80 and 443 to
  a local squid, and appends one explicit `ACCEPT` per declared `{host, port}`;
- squid **peeks the ClientHello and splices**. It reads the SNI and hands the connection through
  **without terminating TLS** — never `bump`. The client sees the real server certificate; a
  locally-issued CN would mean the configuration had silently become `bump` and the boundary had
  inverted.

The rules are installed **before** either daemon starts, and the sidecar dies if it cannot install
them. A boundary that comes up without its rules is worse than one that does not come up at all,
because the declaration still reads as enforced.

There is **no automatic downgrade** to a weaker mechanism. Everything that could rule out the
packet-level boundary (no image sources, an operator-redefined `egress` service) rules out the
cooperative proxy just as completely, so there is nothing to fall back *to*: enforcement is either
this boundary or nothing, and "nothing" is always said out loud.

### And what it is not

Every limit below is measured, and the tool states all of them in its own output. They are not
caveats buried in docs.

- **It is not content inspection.** TLS is never terminated, so what travels to a **declared**
  destination is neither seen nor limited. Anything reachable *through* a permitted host remains
  reachable.
- **A declared name does not constrain the address.** Filtering of TLS uses the name the client
  asks for, and the connection is spliced to the address the **client** chose — the original
  destination is what squid connects to and logs. A process that opens a connection to an
  arbitrary address while presenting a declared name is not stopped by the name check.
- **Sidecars in `egress.sidecars_outside` are outside the boundary entirely**, and anything they
  can reach is reachable through them.

## The proxy is still there — as the diagnostic layer, not the enforcement

The agent's `HTTPS_PROXY`/`https_proxy` still point at squid (on loopback, because the agent shares
the sidecar's namespace — naming the service instead would make the control depend on a DNS lookup
the control itself refuses).

That is deliberate and it is **not** what enforces anything. A client that honours the variables is
**refused with a status it can report** — a `403` from squid — rather than left to time out; a
client that ignores them is transparently redirected to the same squid, matched against the same
allowlist, and has its connection terminated instead. The variables buy a better error message, not
a stronger boundary, which is why unsetting every one of them changes nothing about what is
reachable.

## What you cannot do

**Set `NO_PROXY` yourself.** Under an enforced declaration, any operator-supplied `NO_PROXY` or
`*_PROXY` is refused — from an env file, from a credential *named* `NO_PROXY`, or from a sidecar
override. Three routes, all closed.

The refusal is **kept under packet-level enforcement even though it is no longer the bypass it was
under a cooperative proxy**: an operator value would still break the diagnostic layer above, and a
declaration whose error messages silently stop working is its own kind of failure.

No value is judged safe, including `NO_PROXY=localhost`. Deciding whether one `NO_PROXY` is "wider"
than another means comparing `*`, `.suffix`, IP, CIDR and port forms across clients that disagree
about all of them — and a comparison erring *permissively* reproduces the exact bypass the rule
prevents, while passing its own tests.

## Name resolution is part of the boundary

The sidecar runs its own resolver, and it is **allowlist-only**: declared names resolve, everything
else is `REFUSED`.

Forwarding faithfully to a trusted upstream is **not** a substitute. A resolver that forwards still
resolves `<payload>.attacker.com` — it asks the upstream, which asks the attacker's nameserver, and
the data has left. **The exfiltration is in the question, not the answer**, so only refusing to ask
closes it.

Two details that are load-bearing rather than incidental:

- **`REFUSED`, not `NXDOMAIN`.** A policy refusal must be distinguishable from a genuine "no such
  host", or an operator debugs their network instead of their declaration. `NXDOMAIN` is also a
  cacheable negative answer, so a client that caches it keeps failing after the declaration is
  fixed — a policy error presenting as a DNS bug and outliving its cause.
- **The agent cannot pick another resolver, and this is now enforced by a rule.** **All** port-53
  traffic, UDP and TCP, is REDIRECTed to the sidecar resolver — exactly as 443 and 80 are
  REDIRECTed to squid, and for the same reason (FR-020a). The daemons are exempted **by UID**
  (`! --uid-owner`), never by destination: unbound forwards declared names upstream over port 53
  itself, so without the exemption its own queries would be rewritten back into it and loop. An
  allowlist written twice, in two syntaxes, can drift; a UID cannot, because it does not encode
  the allowlist at all.

  > **This paragraph used to say the opposite** — that no DNS rule was needed because default-deny
  > already made every other resolver unreachable, with Docker's embedded `127.0.0.11` as the lone
  > rewritten exception. That reasoning was runtime-specific and it was wrong as a general claim:
  > it held only where the runtime's resolver sat at a known loopback address, and **under rootless
  > podman it did not hold at all**. The spec never accepted it — FR-020a always required *all*
  > port-53 traffic to be forced to the resolver — so what changed is that the implementation came
  > into compliance with the requirement, not that the requirement moved. Recorded rather than
  > quietly rewritten, because "no rule is needed here" is precisely the shape of a control that
  > looks deliberate while enforcing nothing.

- **Two rules that look like plumbing and are not.** A REDIRECT rewrites the *destination* and
  leaves the source alone, so a redirected query arrives at unbound carrying the namespace's
  bridge address — and unbound answers `127.0.0.0/8` only, so it **REFUSES** it. That refusal is
  `rcode 5`, which reads exactly like a policy denial and is not one; the tell is that declared
  names are denied too. A POSTROUTING SNAT to `127.0.0.1` is what makes the query arrive looking
  local. Separately, the resolver's **ephemeral high port** is dropped, because the redirect
  matches port 53 only and asking that port directly walks straight past the rewrite — measured,
  and it answered.

The upstream for declared names is chosen by the tool, not inherited from the host: the host's
resolver would otherwise learn the environment's entire declared destination set.

## Sidecars are inside the boundary by default

**Any sidecar the agent can reach that has unrestricted egress *is* a bypass.** The agent need not
escape the namespace; it need only ask something that already has the access — `redis REPLICAOF`,
`postgres COPY … FROM PROGRAM`, any service that fetches a URL on request. So every service in
`.agent-container/<name>.services.yaml` joins the boundary automatically.

`egress.sidecars_outside` is the deliberate exception, for a service that legitimately syncs from an
upstream on its own schedule. It lives in the **spec**, not the override file: the override is
operator-owned and shape-validated, and every other security decision lives in the spec an agent
cannot rewrite.

Two guards around it:

- an entry naming a service the override does not declare is **refused**, not ignored — a rename
  would otherwise leave the new service silently inside the boundary while the declaration says it
  is outside, or leave an exception describing nothing;
- every out-of-boundary sidecar is **named at deploy time**, always. `enforced: true` must never
  quietly mean "except for these containers"; an undisclosed exemption is the same overclaim as an
  undisclosed baseline.

### Adopting a declaration changes how you address them

**Service-name DNS between the services stops working**, and this is the one migration cost that
bites immediately. Inside the boundary the agent and every sidecar share **one** network namespace,
so there is no per-service name to resolve any more — `postgres://db:5432` fails, and it fails as a
name-resolution error with nothing pointing back at the declaration you added.

They are all on **loopback** instead:

| Before a declaration | Inside the boundary |
|---|---|
| `redis://redis:6379` | `redis://127.0.0.1:6379` |
| `postgres://db:5432` | `postgres://127.0.0.1:5432` |

Two consequences follow. One namespace means **one port space**, so two sidecars can no longer both
listen on the same port. And **declaring the service name in `egress.allow` does not fix it** — that
is the natural guess and it is refused, naming the fix: loopback traffic inside the boundary needs no
permission, and the resolver has no such name to answer with (with a port it would render an
`-d redis` rule the boundary cannot install; without one, a proxy entry it can never resolve).

The tool says all of this at deploy time, on the same line that lists which sidecars joined the
boundary.

The override is also checked for **egress posture**, not merely shape. A sidecar *inside* the
boundary that asks for `privileged`, for `NET_ADMIN`/`NET_RAW`/`SYS_ADMIN`/`ALL`, or for
`network_mode: host` is refused: the first two could flush the rules of the namespace they share,
the third leaves that namespace altogether. The agent needs no capability of its own to exploit
that — only something to ask. A sidecar already declared outside is exempt, since it is not in the
namespace to dismantle and is named as unconstrained anyway.

## Seeing what is enforced

```console
$ agent-container status --json | jq '.data.environments[] | select(.name=="acme") | .egress'
```

`declared` and `enforced` are **separate fields**: a declaration can exist without being in force,
in which case `not_enforced_reason` names the specific obstacle — the egress image sources are not
reachable (a non-checkout install), or a sidecar override redefines the `egress` service so the
running boundary is not the one this tool configured. Never "unsupported": an operator must be able
to tell *which* obstacle they hit.

`destinations` is the **effective** allowlist — an operator `hosts:` override is reported rather
than the tool's default, since reporting the default while enforcing an override would state a
permission set nothing enforces. Each entry carries `source` (`tool` or `declaration`) and `port`,
and **`port` is the field that says which surface enforces it**: `null` for the hostname allowlist,
an integer for an explicit packet-filter rule. A caller reading only `host` cannot tell those apart,
and they have very different reach.

`unrestricted` disambiguates an empty list, since undeclared and air-gapped both have one.

`mechanism` names **which** enforcement you got — `transparent` for the packet-level boundary,
`none` when nothing is enforced. It is not a restatement of `enforced`: the two mechanisms this
feature can deliver are not interchangeable (one holds against an agent actively evading it, the
other only against accident), and a boolean cannot say which. The prose statement distinguishes
them, so a machine consumer must be able to as well. `enforced` keeps its meaning and is still
emitted; the two are computed from one call so they cannot come to disagree.

### Seeing what was refused

```console
$ agent-container logs acme --egress
```

The boundary's log is **the only place a refusal is recorded**, and it carries both halves:

| line | means |
|---|---|
| `api.openai.com. A IN REFUSED` | the name is **not declared**. `NXDOMAIN` instead would mean it genuinely does not exist |
| `NONE_NONE/000 … sni=github.com bump=terminate` | a TLS connection **terminated** because the name it asked for is not on the allowlist. Read the `sni=`, not the URL — the URL is the address the client chose, and on a CDN it fronts thousands of sites |
| `TCP_DENIED/403 GET http://github.com/` | refused on the plain-HTTP path, **with a status** the client can report rather than a silent drop |
| `NONE_NONE/000 … sni=api.anthropic.com bump=splice` | **permitted.** This is the first of the two lines a permitted request logs, and everything but `bump=` is identical to the terminated line above |
| `TCP_TUNNEL/200 CONNECT api.anthropic.com:443 ORIGINAL_DST/…` | the second line of that same permitted request — spliced, so the tunnel was opened and not inspected |

**`bump=` is the field that tells a refusal from a permission, not the status tag.** Measured on a
live boundary: a permitted HTTPS request to a declared host logs a first line whose status tag,
status code, byte count, method, hierarchy and `%err_code` are *identical* to a terminated one.
`%ssl::bump_mode` is squid's own record of what `ssl_bump` decided, so both the operator reading the
log and the tool building the durable record ask the enforcer rather than inferring. Grepping
`NONE_NONE` alone will show you permitted traffic.

The agent's own log shows only the resulting failure with no cause, which is why this flag exists.
Two things to know before reading it: the container healthcheck contributes a
`NONE_NONE/000 … error:transaction-end-before-headers` line every few seconds, so filter those out;
and asking for an environment with no boundary reports that as a **policy** fact ("no egress
boundary to read"), not as a missing container.

### The durable record — what was refused *after the container is gone*

```console
$ agent-container egress acme
$ agent-container egress --json | jq '.data.events[]'
```

The log above is **live**: it dies with the container, and containers are ephemeral by design
(Constitution I). So the tool distils that same stream into a durable record on your machine —
`$XDG_DATA_HOME/agent-container/egress/<host>/<environment>/`, a sibling of the run records and
**not** a volume. Every command that talks to a host collects it, and **teardown collects before it
removes the boundary**.

**One producer, one truth.** The events come from the boundary's own log and nothing else writes
them. A second mechanism could disagree with what `logs --egress` shows, and "the tool says nothing
was refused" beside a log that says otherwise is worse than having no record.

**What is kept, and what is deliberately not:**

| event | kept |
|---|---|
| a refused resolution (`REFUSED`) | **yes** — the common shape; an undeclared name never reaches a connection |
| a terminated TLS connection (`bump=terminate`) | **yes** |
| a plain-HTTP denial (`TCP_DENIED`) | **yes**, on the status tag alone |
| a destination **permitted while undeclared** | **yes**, and it is the loudest event here — the running boundary is not enforcing the allowlist this tool generated |
| ordinary permitted traffic to a declared host | **no.** This is a record, not a traffic log: one line per request would bury the events above and set retention to work evicting refusals to make room |
| `NXDOMAIN` | **no.** That name genuinely does not exist — a fact about the internet, not a policy event (and the distinction is why the resolver answers `REFUSED` at all) |
| an upstream's **own** status code to a declared host — `503`, and equally `403` | **no.** Policy permitted it; the far end said no. A WAF, a bot block, a stale API key and a CDN all answer `403`, and recording those as refusals would be fabricated findings at the rate the agent makes requests. A genuine denial by this configuration always carries `TCP_DENIED` |
| a divergent-resolution failure (`NONE_NONE/409`, measured) to a declared host | **no**, and **neither verdict is invented for it.** squid's host verification rejected the connection because its own address for the name and the agent's had diverged — so `refused` would fabricate a policy finding and `permitted` would claim a connection that never happened |

Each event carries the destination, a verdict, whether the declaration named it, which daemon saw
it (`dns` or `connect`), and the provider where the tool's mapping knows one. **Nothing else** —
no headers, no bodies, no tokens, no model names, no prompt content. The boundary never terminates
TLS, so it cannot see them; and a plain-HTTP URL's query string and `user:pass@` are dropped at the
one place they could have entered.

**It answers *what* and *when*, never *how many*.** Two events identical in every recorded field
collapse into one record — that is what makes re-reading an unclearable log safe. The retry count
lives in `logs --egress` while the boundary is alive.

**Silence means nothing was refused.** That only holds while something is watching, so an
environment with no boundary is told so instead of answered with a blank screen:

| you asked about | you are told |
|---|---|
| an environment whose last deployment declared a boundary | nothing collected from that boundary's log **was refused** |
| an environment with **no** boundary | nothing observes its egress: it is **unrestricted and unrecorded** |
| an environment the tool has no deployment for | none were **ever ingested** — which is not evidence none happened |

The first row says "collected" rather than "happened", and the difference is real: the tool reads
that log on every contact and before it removes the boundary, but a sidecar removed **out of band**
takes whatever had not been collected with it. That is the one gap this store cannot close, since a
log that no longer exists cannot be read late.

`--json` carries the same distinction as a `boundary` field (`watched` / `unwatched` / `unknown`)
per environment, so a consumer never has to read prose to tell the three apart. A listing also
names the environments it does *not* cover, because an incomplete answer presented as a complete
one is worse than no answer.

**Two limits, stated rather than discovered.** Events are pruned at ingestion, per environment, at
**90 days** or **500 events** — whichever prunes first, and the count is spent on **distinct
destinations first**, so one endpoint an agent retries all night cannot evict the record of every
other host it reached for. And the pending window is the *runtime's* log retention, not a volume
this tool owns: each contact reads the last **20000** lines of the boundary's log, so lines the log
driver has already rotated away were never ingested. Talk to the host — any command does — and the
window resets.

Beside the events, each store keeps one `watermark` file: how far that boundary's log has already
been read. It is what makes the bound above converge — without it a pruned event whose line is still
in the window comes back on the next command, is pruned again, and both are announced every time.
It is a cursor, not a record: nothing lists it as an event, and deleting it only causes a re-read.

## Modes

| | enforceable | not enforceable |
|---|---|---|
| `advisory` *(default)* | deploys with the boundary | **deploys**, stating plainly that nothing is enforced |
| `strict` | deploys with the boundary | **refuses**, naming why |

Advisory deploys because the defect this feature fixes is **silence**, not permissiveness.

Note what is *not* on this axis any more: **the agent**. Transparent enforcement needs nothing from
the agent, so an agent nobody has ever probed for proxy adherence still gets the full boundary.
Under the cooperative proxy an unknown agent was an obstacle; here it is not one.

## The published port moves with the boundary

A shared network namespace has exactly one port owner, and it is the container that owns the
namespace. So under an enforced declaration the `2200 + hash` SSH binding is published by the
**egress** service instead of the agent. The port **number** is unchanged — `attach` and every
other consumer still agree — but which service publishes it is part of the deployed shape.

That makes adopting or dropping a declaration a **migration, not an edit**: compose cannot hand a
published port to a different service while the current owner still holds it. The tool detects the
stale owner in **both** directions and recreates the deployment, announcing it rather than doing it
silently. Volumes are preserved.

## Teardown

The egress sidecar shares the environment's compose project, so `down` and `wipe` remove it with no
extra step. It adds **no volume** — the nine-volume identity contract is untouched.
