# Implementation Plan: The Agent SSH Key Pair Is Generated In the Container

**Branch**: `019-agent-ssh-key-pair` | **Date**: 2026-08-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-agent-ssh-key-pair/`

**Supersedes** the first draft of this plan, which predated four clarifications. Two of them changed
the shape of the work rather than its details, and both made it **smaller**.

## Summary

The container generates its own SSH key pair at `~/.ssh/id_ed25519`; the **private half never leaves
it**, and the **public half** is what the operator obtains and registers. Afterwards the tool writes
**no private key anywhere** on the operator's disk.

This completes what Feature 018 began. 018 removed the private *host* key — inbound identity, which
only ever needed a public key to verify. This removes the private *agent* key — outbound
authentication, which genuinely needs a private key and therefore had to be **relocated** rather than
eliminated.

It is also a real least-privilege gain: `--push-key` is usually handed the operator's *personal* key,
so the container receives everything that key authorises. A per-container key registered as a
repository deploy key authorises one repository.

## The decisions this plan settles first

### 1. The conventional path makes this a DELETION, not a rewiring

The clarification that changed the most. The key is the **agent's** SSH identity, so it goes where an
SSH identity goes: `~/.ssh/id_ed25519`.

Everything follows from that, and all of it is removal:

- **`core.sshCommand` disappears.** Git shells out to `ssh`, which reads the conventional identity
  automatically. That config line existed only because the key used to arrive at an arbitrary injected
  path under `/run` and git had to be told where to look.
- **`PUSH_RUNTIME` disappears** — 11 references in `image/entrypoint.sh`, all of it scaffolding for
  copying an injected 0644 key to a private 0600 location. A container that generates its own key at
  0600 has nothing to copy.
- **Persistence needs no new path.** `SSH_DIR="${AGENT_CONTAINER_HOME}/.ssh"` is already the per-
  container `ssh` volume's mount point, so the conventional location is *already* persisted.
- **Every outbound SSH uses it** — git, `ssh`, `scp`, `rsync` — rather than git alone holding a
  credential nothing else can reach.

The container's own `~/.ssh/config` is **greenfield**: nothing writes it today (verified).

### 2. `~/.ssh/config` is written ONCE, and rotation is an explicit command

The block's content is entirely static — `IdentitiesOnly`, a fixed `IdentityFile`, a fixed
`UserKnownHostsFile`. Verified against what `core.sshCommand` carries today, which is exactly those
flags and fixed paths. **Nothing in it varies per boot**, so a per-boot rewrite gains nothing while
costing an ownership conflict on a file the agent may legitimately need (a jump host, a per-host user).
Only the *contents* of the referenced `known_hosts` vary, and that is a different file with its own
injection path.

The stale-after-upgrade case is handled by an **explicit** command, not silent clobbering — the same
reason `--purge` exists rather than the tool quietly resetting volumes.

That surfaced a capability the spec was missing: **deliberate key rotation** (FR-014b). `--purge`
already rotates the key by destroying the volume, which is disproportionate when the workspace is
worth keeping — and a suspected compromise is exactly when rotation should be cheap.

### 3. A deferred clone exits NON-ZERO, so the output must prevent the obvious wrong reaction

FR-013's two-phase flow starts the container without cloning, and that invocation exits **non-zero**
with a **distinct code** meaning *pending registration*.

I argued for exit 0 and was overruled, so the objection becomes a design constraint rather than
disappearing: an automated caller seeing non-zero will reasonably `down` and retry, which **destroys
the key awaiting registration**; the retry generates a different key, so the loop never terminates and
each iteration invalidates the registration just made. This tool is driven by agents, so that caller
is the expected one.

Hence the two requirements that make the choice safe: a distinct exit code so a caller can tell
"pending" from "broken" without parsing prose, and output stating that tearing down destroys the key
and the recovery is **register, then `redeploy`** — never recreate.

### 4. The probe targets the `--repo` host, or nothing

It runs **inside the container**, because the operator's machine holds no private key and so cannot
answer the question. That placement has a property worth stating rather than discovering: **the probe
inherits the same egress the push will**, so a `not-registered` answer is predictive rather than a
guess about network conditions the agent will never face.

It targets **only** the host of `--repo`. With no `--repo` there is no probe and the key is reported
*unverified* — never assumed good or bad. Defaulting to `github.com` would invent a fact and send
traffic to a third party the operator never named.

**It must fail soft.** Denied egress (Feature 012), offline, or a forge outage yields *unknown* and
never blocks a deploy.

### 5. Four removal channels, grepped rather than recalled

`up --push-key`, `redeploy --push-key`, `SSH_PUSH_KEY_B64`, declarative `target: push_key` — plus
`stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH` and `clone_credential_precheck`.

**`--known-hosts` / `PUSH_KNOWN_HOSTS` stay**: they verify the *forge*, which is the opposite direction
and public data.

### 6. Reuse 018's capture

`capture_host_pubkey` already reads a public key out of a container through the runtime, with the
bounded poll that exists because Feature 016 measured `Up` preceding the entrypoint. Pointing it at a
second path is a parameter, not a new mechanism.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell entrypoint.

**New dependencies**: **none** (Constitution VI).

**Storage**: no new store and **no new path** — the key lives on the existing `ssh` volume at the
conventional identity location.

**Testing**: hermetic pytest for the removal census, the refusals, write-once config, the pending-clone
exit code and the soft probe; acceptance for what only real containers show — a key that persists
across recreate, a real `git push`, rotation, and no private key anywhere.

**Constraints**:

- **No private key written anywhere** on the operator's machine (FR-001/FR-010).
- **Generation is idempotent** — regenerating on every boot would silently invalidate the operator's
  registration while every symptom looked healthy (FR-003, SC-003).
- **`~/.ssh/config` is never rewritten** after creation (FR-014a).
- **The probe never blocks a deploy** (FR-011).

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, with a wrinkle named.** The key deliberately survives recreate — it is not *work*, so nothing of value is trapped, and `--purge` rotating it is correct rather than lossy |
| **II. Least Privilege, Immutable Runtime** | **PASS, and strengthened.** A per-container key authorises one repository where the operator's personal key authorised everything it could reach |
| **III. Least Exposure** | **PASS, and this is the point.** The last private key the tool writes to the operator's disk stops being written |
| **IV. Deterministic Identity** | **PASS** — no name, port or volume change |
| **V. Durable Spec** | **PASS** — clarified across three sessions; every decision above is recorded in the spec, not only here |
| **VI. Least Dependencies** | **PASS** — nothing new, and 11 references of existing scaffolding removed |
| **VII. Continuous Deployment** | **`feat!` — BREAKING.** Four channels removed, and SSH clone-on-start changes shape and exit status |

## Project Structure

```text
bin/agent-container       capture (reusing 018's), the agent_ssh_public_key field, the probe, the
                          pending-clone exit code, the rotate command, removal of --push-key from
                          up/redeploy, stage_push_injection's push arm, INJECT_PUSH_KEY_PATH,
                          CRED_SSH_TARGETS' push_key, clone_credential_precheck, stale-file cleanup
image/entrypoint.sh       generate at ~/.ssh/id_ed25519 if absent; write ~/.ssh/config ONCE;
                          DELETE core.sshCommand and all 11 PUSH_RUNTIME references and the
                          SSH_PUSH_KEY_B64 branch; make an SSH clone PENDING rather than fatal
docs/credentials.md       the agent's key is captured, not supplied; the /run rule amended for
                          self-generated material
docs/execution.md         SSH clone-on-start is two-phase, and what its exit code means
docs/agent-as-code.md     target: push_key is refused, not ignored
docs/agent-interface.md   the agent_ssh_public_key field
docs/threat-model.md      reconcile — last private-key write site removed; a signing key now on a
                          volume that outlives its container
CLAUDE.md                 the /run invariant is no longer absolute — say what it excludes
bin/tests/                census, refusals, write-once, exit code, soft probe; acceptance for
                          persistence, a real push, rotation, and no private key on disk
```

## Design decisions carried into tasks

1. **Generate at `~/.ssh/id_ed25519`**, idempotently, in the entrypoint.
2. **Delete rather than rewire** — `core.sshCommand`, `PUSH_RUNTIME`, the injected-key branches.
3. **`~/.ssh/config` written once**; rotation is an explicit command that states the old registration
   is dead.
4. **Pending clone: non-zero, distinct code, and output that forbids the destructive reaction.**
5. **Probe in-container, `--repo` host only, fail soft.**
6. **Remove all four channels plus the precheck**, each with an explaining refusal.
7. **Capture via 018's primitive.**

## Phasing

**P1 — the key exists and never leaves.** US1/US2. Generate, capture, expose, remove the four
channels. **Prove no private key is on disk before anything is built on top** — that is the feature,
and it is an absence.

**P2 — the operator knows what to do.** US3. What to register, the probe, and rotation.

**P3 — the honest edges.** Two-phase clone with its exit code, `--purge` rotation warning, the stale
file, and the threat model.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A private key on a persisted volume | under `/run` it dies with the container, so every recreate needs re-registration on the forge — unusable | keeping it ephemeral; the feature does not work |
| Relaxing FR-014 for one case | the key cannot exist before the container does, so an SSH clone-on-start cannot succeed on a first boot | refusing SSH clone-on-start entirely — deletes a capability, and `GH_TOKEN` is github.com-scoped so other forges would have no path |
| A non-zero exit that leaves a working container | operator's decision: the environment is not usable yet, so the invocation did not do what was asked | exit 0 — argued for and overruled; the risk it carried is now mitigated by FR-013's distinct code and wording |
| A network probe in a deploy path | FR-011 asks the tool to stop nagging once pushing works, and only the forge knows | announcing once — silently wrong for the operator who never registered, which is the case the requirement exists to catch |
