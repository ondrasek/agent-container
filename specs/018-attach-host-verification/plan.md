# Implementation Plan: Verified Attach, Without a Private Host Key on Disk

**Branch**: `018-attach-host-verification` | **Date**: 2026-08-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/018-attach-host-verification/`

## Summary

`attach` becomes verified, and the tool stops holding a private SSH host key.

Both halves are small because the pieces already exist: the container **already** generates its host
key as `dev` on the persisted `ssh` volume, and the entrypoint **already** writes the matching
`.pub` beside it at 0644. What is missing is that nothing reads that public key, and nothing pins it.

So: read it through the runtime, write a tool-owned `known_hosts`, point `attach` at it with
`StrictHostKeyChecking=yes`, and delete `--host-key` along with the 0644 private key it staged.

**This feature removes an exposure rather than adding a store.** That is unusual enough to be worth
saying twice, because it changes what "done" looks like: the strongest evidence of success is a file
that no longer exists.

## The decisions this plan settles first

### 1. The pinned file is DERIVED HOST STATE, not durable user data

`$XDG_STATE_HOME/agent-container/<host>/known_hosts` — beside `.port`, in the location Feature 011
documents as *"computed; safe to delete"*.

That is exactly right here and it is worth stating because the neighbouring feature pulls the other
way. Feature 014's inventory must be **durable** — it answers *what did we ever create* and has to
outlive its host. A pinned host key answers *is this the container I created*, is meaningless once
the container is gone, and is **re-capturable at any time from the running container**. Safe to
delete is a true statement about it, so it belongs where that is the documented property.

**Consequence: 018 needs no new location and no `docs/layout.md` row.** It is a new *file* in an
existing category. (This is also why 018 and 014 stay separate features: their data has opposite
lifetimes.)

### 2. Per host, one entry per environment, keyed `[address]:port` — measured

One `known_hosts` per host, holding one line per environment:

```
[127.0.0.1]:2206 ssh-ed25519 AAAAC3Nz...
```

**Measured**, because FR-005 depends on it: `ssh-keygen -F` finds `[127.0.0.1]:2222`, and does **not**
match `[127.0.0.1]:2223` or the bare `127.0.0.1`. So two containers on one host cannot verify each
other's connections, which is the failure FR-005 names — and it falls out of the standard format
rather than needing tool logic.

### 3. FR-007 needs no change-attribution logic — capture at every deploy makes it fall out

FR-007 asks the tool to re-pin silently when *it* caused the identity to change, and refuse when it
did not. Written as attribution ("did we do this?") that is stateful and fragile.

Inverted, it disappears: **capture on every deploy.** The pinned entry is then, by construction,
whatever the tool last saw. A mismatch at attach time therefore means the key changed *without a
deploy* — i.e. not by us — and refusing is correct with no attribution needed. `--purge` + recreate
re-pins because the recreate is a deploy.

This is the whole reason the design is small, and it is the part most likely to be re-complicated by
someone later.

### 4. Capture must wait for the key, and Feature 016 already paid for that lesson

The `.pub` file does not exist the instant the container is `Up`. 016 measured that the runtime
publishes `Up` **before the entrypoint executes a line**, and that the entrypoint's own first write
lands 0.27–0.57 s later. Host-key generation happens later still.

So capture polls for the file with a bound, and on timeout **warns and says attach is unverified**
(FR-008) rather than pinning an empty value or failing the deploy. A test must assert the empty case
is refused, because "pinned nothing" and "pinned correctly" are indistinguishable from the exit code.

### 4a. An ABSENT pin asks; a MISMATCH never does — and the reason is not symmetry

Correcting an error in the first draft of this plan, which had `attach` simply refuse when nothing is
pinned. Two separate things were wrong with that.

**First, capture-at-attach is not a verification, so it must not be silent.** A pin is a witness, and its
value comes from being **older than what it checks**. At deploy the tool knows the container is the one
it just created; at attach the runtime can only say *"the container currently called X"*. An attacker who
replaced the container would have their own key captured and then checked against themselves. So
FR-003's "the runtime is a trusted channel" licenses preferring the runtime over `ssh-keyscan` **at
deploy time** — it does not license capturing at attach time. Research R8 has the table.

**Second, refusing outright is disproportionate.** The only re-pin path would be `redeploy`, which runs
`--force-recreate` — it destroys the container and kills the operator's running agent. A deleted cache
file would cost a working session, against Constitution I.

So: **warn, show the fingerprint, say what accepting cannot detect, and ask** (FR-013/FR-016). A trust
decision the operator makes knowingly, never one the tool makes quietly. No terminal → refuse (FR-015);
an assumed yes is a silent capture with extra steps.

**And a mismatch is unconditional** (FR-014). Absent has no prior claim to contradict; a mismatch
contradicts one the tool made itself. Making both prompt would let the second be clicked through, which
deletes the feature.

**US3 is the preferred escape**, not the prompt: an entry copied from the deploying machine has real
provenance.

### 5. `ssh-keyscan` is forbidden, and that is a requirement not a preference

FR-003 names the channel. The runtime is an independent, already-trusted path — the operator controls
that daemon. `ssh-keyscan` asks the endpoint being authenticated to state its own identity, which is
trust-on-first-use with extra steps. Someone will suggest it because it is one line; the plan says no
here so the answer is on record.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell entrypoint.

**New dependencies**: **none** (Constitution VI). `ssh`, `ssh-keygen` and the runtime are already used.

**Storage**: `$XDG_STATE_HOME/agent-container/<host>/known_hosts`. **Nothing is added under
`$XDG_DATA_HOME`**, and one file stops being written: `<state>/<host>/<name>.host_key`.

**Testing**: hermetic pytest for entry formatting, the `[addr]:port` keying, the empty-capture
refusal, and the argv `attach` builds; acceptance for what only a real container shows — verified
attach, refusal on a substituted key, silent re-pin after recreate, and capture over a **remote**
context.

**Constraints**:

- **No private key material written anywhere** on the operator's machine (FR-001/FR-012).
- **Capture through the runtime only** (FR-003) — never from the SSH endpoint.
- **Never touch the operator's `~/.ssh/known_hosts`** (FR-006, SC-007 asserts byte-identical).
- **A capture failure must not fail the deploy** but must not leave attach silently unverified
  (FR-008).

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS** — the pinned file is disposable and re-derivable from the running container; nothing of value is trapped |
| **II. Least Privilege, Immutable Runtime** | **PASS** — no new capability. The entrypoint *loses* a branch (injected-key install) |
| **III. Least Exposure** | **PASS, and this is the point.** A plaintext private key at 0644 that survived `--purge` stops being written. The tool holds only public keys |
| **IV. Deterministic Identity** | **PASS, and slightly strengthened** — identity becomes *verified* rather than assumed. No name, port or volume changes |
| **V. Durable Spec** | **PASS** — clarified in one session; the four questions were settled before writing |
| **VI. Least Dependencies** | **PASS** — nothing new |
| **VII. Continuous Deployment** | **`feat!` — BREAKING.** `--host-key` is removed. The commit must say so or semantic-release under-bumps |

## Project Structure

```text
bin/agent-container       capture, the tool-owned known_hosts, attach's verification argv,
                          removal of --host-key and its staging, stale-file cleanup
image/entrypoint.sh       delete the injected-host-key branch and INJECT_HOST_KEY_PATH
docs/shell-integration.md attach is now verified; what a refusal means
docs/credentials.md       remove --host-key; state that host identity is captured, not supplied
docs/threat-model.md      reconcile — an exposure removed, a new trusted file introduced
bin/tests/                hermetic formatting/keying/argv; acceptance for verify, refuse, re-pin, remote
```

## Design decisions carried into tasks

1. **Capture through the runtime**, reading `~/.ssh/hostkeys/ssh_host_ed25519_key.pub` — which the
   entrypoint already writes at 0644, so nothing in the image changes to enable this.
2. **Capture at every deploy**, which is what makes FR-007 free (decision 3).
3. **`[address]:port` keying**, measured to distinguish environments on one host (decision 2).
4. **`StrictHostKeyChecking=yes`, not `accept-new`.** `accept-new` would silently trust an unpinned
   host, which is the behaviour being replaced.
5. **A tool-owned file, never the operator's.** SC-007 asserts `~/.ssh/known_hosts` is byte-identical
   before and after any operation.
6. **Removal is part of the feature, not cleanup afterwards** — the flag, the staging, the entrypoint
   branch and any stale `<name>.host_key` all go, and FR-011 requires the deletion be stated.

## Phasing

**P1 — capture and pin.** US1. Read the key, write the file, make `attach` verify. **Prove a
substituted key is refused before anything else** — a pin that never refuses is decoration.

**P2 — remove the private key.** US2. Delete `--host-key`, its staging, the entrypoint branch, and
stale files. The evidence of success is a file that no longer exists.

**P3 — expose the captured key.** US3. A `known_hosts` line the operator can put elsewhere.

**P4 — the honest edges.** Capture timeout, remote context, two-on-one-host, the operator's own file
untouched, and the threat-model reconciliation.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A tool-owned `known_hosts` | FR-006 forbids touching the operator's | writing into `~/.ssh/known_hosts` — silently editing a file the operator owns |
| A prompt on an absent pin, but never on a mismatch | the two are different situations (decision 4a); refusing on absent costs a running agent, prompting on mismatch lets the warning be clicked through | silent capture-if-absent — cannot detect a replaced container yet *looks* like verification, which is worse than an obvious absence |
| Polling for the `.pub` at capture | it does not exist when the container reports `Up` (016, measured) | capturing immediately — pins nothing, and "pinned nothing" is indistinguishable from success |
| Removing a documented flag | it delivers no verified benefit and costs a 0644 private key that survives `--purge` | keeping it — the whole exposure this feature exists to remove |
