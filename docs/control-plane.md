# The control plane — manage containers from a device with nothing installed (Feature 017)

Everything this tool does used to require the machine it was installed on. Away from that machine,
an operator could reach a container over SSH but could not *manage* one: no `list`, no `stop`, no
`redeploy`.

A **control plane** is an SSH-reachable container holding a **configured** `agent-container` CLI. You
attach to it from a phone and manage the fleet.

```sh
agent-container up hub --role control-plane
agent-container attach hub
```

## Read this before you deploy one

**This is the highest-risk thing in the tool, and the risk is specific rather than vague.** The
container holds a keypair whose public half you authorise on your hosts. A session in it reaches a
sandbox shell **and** machine-level daemon access — the same key that inspects is the key that stops
and destroys. Whoever holds the volume *and* the passphrase holds both.

`up --role control-plane` states three things before it creates anything:

1. **A session holds whatever the container holds.** The key is not scoped to "inspect".
2. **The declared scope**, host by host.
3. **The passphrase has no recovery.**

Printed, not prompted — `up` is a path an agent may drive, and a prompt would be auto-answered,
which reads as consent.

## The passphrase

Generated **in the container**, printed **once**, stored **nowhere** by this tool.

```
=== hub: CONTROL-PLANE KEY PASSPHRASE — copy it now, it is shown ONCE ===
<value>
=== stored NOWHERE by this tool. No recovery. Put it in your password manager ===
```

It is not in a file, a log, a run record, a `--json` payload, or any variable that outlives the
print. It is the **one place this tool touches a secret it did not receive from you**, and that is
recorded as a stated narrow exception to Constitution III rather than glossed
([threat model](threat-model.md), T18).

**If you lose it there is no recovery.** Redeploy to mint a fresh keypair, then `revoke` the old
public half. A recovery path would by definition be a way to obtain the key without the passphrase.

## What bounds it

| Thing | What it actually is |
|---|---|
| `control_plane_hosts` in `settings.yaml` | **a declaration of intent** — visible before you deploy, comparable afterwards |
| where you authorised the public key | **the boundary** |
| `agent-container revoke <name>` | the only concrete narrowing |

Reach is where the key is authorised, which lives outside the container on purpose. Treating the
declared scope as the boundary would be a control that does not control — so the tool refuses an
out-of-scope action to make a *mistake* fail at the first host rather than half-way through a fleet,
and says plainly that this is not a security boundary.

**Deploying grants nothing.** Authorising the public key is always an explicit, separate act.

### Revocation

```sh
agent-container revoke hub
```

One command across every registered host — not the declared scope, because the key may have been
authorised somewhere you forgot, and that is the authorisation revocation exists for.

**The honest limit:** this tool holds an SSH identity only for hosts it *provisioned*. For a host you
registered by handing over a docker context, it can start containers and cannot log in, so it reports
`unsupported`, names the manual step, and **fails the run**. "Mostly revoked" is worthless — an
operator who believes a key is gone stops looking.

`--purge` is the other revocation boundary: it destroys the volume the key lives on.

## The key is locked whenever nobody is attached

No `ssh-agent` is started at boot and the key is never added to one. You supply the passphrase on
connect. After a host reboot it comes back **locked**, which is harmless: a control plane has no
unattended work.

## It cannot destroy itself

`panic --destroy` from inside a control plane **excludes its own container** and says so as a
first-class outcome:

```
EXCLUDED from destroy: hub — this control plane is the container you are issuing this
command from. Stopping it would kill this process mid-operation and the report would
never be delivered.
  to stop it, from your own machine: agent-container destroy hub --host vps1
```

Not to protect the container — to protect the **report**. `panic`'s whole value is telling the truth
about what it could not reach, and there is no report at all if the reporter is the first casualty.

## What it can see

It enumerates hosts **live** on connect. It holds no durable inventory of its own, so:

- an environment on an **unreachable host is not shown as absent — it is named as unreachable**;
- `list --json` carries `unreachable_hosts` and `complete`, because a short list that looks complete
  is worse than an error.

The host registry is injected as a **snapshot** at deploy. A host you register afterwards is
invisible there until you redeploy — stated in the boot log so you meet the fact before it confuses
you.

## Nesting

A control plane may deploy another. This is **supported, not refused**, and **not gated**: scope is
where the key is authorised, so a parent cannot constrain a child even in principle. A gate would be
a control that cannot control.

What you get instead is **visibility**. Every inventory entry carries `role` and `provenance`
(`operator` or `control-plane:<name>`), persisted — so a *stopped* control plane is still
identifiable, which inspecting the container could not tell you.

## Version skew

A control plane manages environments that may be newer or older than itself. Compared by **semver
precedence**, not equality:

| Situation | Result |
|---|---|
| patch difference (and post-1.0 minor) | **silent** — ignored, not warned about |
| control plane **newer** | advisory (the normal state after an upgrade) |
| environment **newer** | **REFUSED**, naming `redeploy` as the remedy |
| either version unreadable | `unknown` — never assumed compatible |

`major_on_zero = false` in this project, so **pre-1.0 a breaking change lands as MINOR**: 0.31 → 0.32
*is* the breaking channel.

## The image

A **second image** (`image-control-plane/`), not a build arg. It holds the CLI, ssh, tmux, git and
curl — and **no agent CLI or runtime**. FR-015a wants "no agents here" to be a readable property of
the artifact rather than something you reconstruct from a build invocation, and the agent census is
parameterised over every Dockerfile in the tree and **fails on one it has no expectation for**.

`agent-container build` builds both. It **refuses** to build the control-plane image when it cannot
resolve a version, because that image *pins the CLI it installs* and a default would install a
version nobody chose.

## Not provided, deliberately

- **No passphrase store, cache or escrow.** Any of them is a way to get the key without the
  passphrase.
- **No control-plane-local inventory.** It enumerates live; a second durable source would drift.
- **No subset-scope inheritance for nested control planes.** Not expressible — see above.
