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
      providers:
        - anthropic                         # the tool supplies the hosts
        - name: openai                      # an indirect endpoint…
          hosts: [llm.corp.internal]        # …whose hosts REPLACE the tool's
      allow:
        - github.com                        # non-provider hosts you also need
        - "*.githubusercontent.com"         # domain + subdomains
      enforcement: advisory                 # advisory (default) | strict
```

> **Being re-specced.** Clarification of US4/US5 (2026-08-05) merges `providers:` and `allow:` into
> one typed `egress.allow` list, where **the presence of a port selects the enforcement surface**.
> See `specs/012-egress-provider-control/spec.md` FR-018a/FR-018b. The two-key form above is what
> ships today.

## The three states are different, and one of them is not what you'd guess

| Declaration | Meaning |
|---|---|
| **no `egress:` key** | **unrestricted** — exactly today's behaviour, plus a one-time disclosure |
| `providers: []` | **air-gapped** — every outbound model call refused |
| `providers: [anthropic]` | only those hosts reachable |

Absent and empty are **opposites**, and the tool never conflates them. If it did, upgrading would
silently air-gap every environment that has no declaration.

## It governs ALL egress, not just model providers

The mechanism is a forward proxy on `HTTPS_PROXY`, which intercepts **every** HTTPS request — it
cannot be narrowed to model vendors. So an environment that declares anything must declare
everything it needs.

**This includes your git remote.** With `providers: [anthropic]` and nothing else, `git push` over
HTTPS gets `403`:

```console
$ git ls-remote https://github.com/you/acme
fatal: unable to access '…': CONNECT tunnel failed, response 403
```

The tool refuses to let that surprise you: if the environment pushes over HTTPS and the remote's
host is not in the allowlist, it says so **at deploy time**, naming the host to add. Under `strict`
it refuses to deploy.

There is **no hidden always-permitted baseline**. If a host is reachable, you declared it.

## What enforcement actually is

**Proxy-level, not packet-level — by scope, not by necessity.**

The agent is *pointed at* the proxy through `HTTPS_PROXY`/`https_proxy`, not *confined to* it:

- a client that honours proxy settings is bound, and **all four supported agents do** — verified by
  running each against a black-holed proxy, not read from documentation;
- a process that ignores them and opens a direct connection is **not stopped**;
- a shell can override the variables via `~/.agent-env/env`, which every interactive shell sources
  from a volume that survives teardown. The tool can neither see nor prevent that.

The tool states all of this in its own output. It is not a caveat buried in docs.

> **Packet filtering is achievable here** — `NET_ADMIN` on the *proxy* container plus a shared
> network namespace, with the agent container gaining nothing. It is not yet implemented (US4).
> Earlier drafts claimed Constitution II forbade it; that was wrong, and the correction matters
> because a false impossibility argues against ever building the stronger version.

## What you cannot do

**Set `NO_PROXY` yourself.** Under an enforced declaration, any operator-supplied `NO_PROXY` or
`*_PROXY` is refused — from an env file, from a credential *named* `NO_PROXY`, or from a sidecar
override. Three routes, all closed.

No value is judged safe, including `NO_PROXY=localhost`. Deciding whether one `NO_PROXY` is "wider"
than another means comparing `*`, `.suffix`, IP, CIDR and port forms across clients that disagree
about all of them — and a comparison erring *permissively* reproduces the exact bypass the rule
prevents, while passing its own tests.

## Seeing what is enforced

```console
$ agent-container status --json | jq '.data.environments[] | select(.name=="acme") | .egress'
```

`declared` and `enforced` are **separate fields**: a declaration can exist without being in force
(advisory mode, an agent not known to honour the proxy, or an operator override redefining the
proxy service), in which case `not_enforced_reason` says which. `unrestricted` disambiguates an
empty `hosts` list, since undeclared and air-gapped both have one.

## Modes

| | enforceable | not enforceable |
|---|---|---|
| `advisory` *(default)* | deploys with the proxy | **deploys**, stating plainly that nothing is enforced |
| `strict` | deploys with the proxy | **refuses**, naming why |

Advisory deploys because the defect this feature fixes is **silence**, not permissiveness.
An agent absent from the known-to-honour list reads as *not* honouring, so `strict` refuses it
until someone probes it.

## Teardown

The proxy shares the environment's compose project, so `down` and `wipe` remove it with no extra
step. It adds **no volume** — the nine-volume identity contract is untouched.
