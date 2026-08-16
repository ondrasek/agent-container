# Implementation Plan: The Agent SSH Key Pair Is Generated In the Container

**Branch**: `019-agent-ssh-key-pair` | **Date**: 2026-08-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/019-agent-ssh-key-pair/`

## Summary

The container generates its own outbound SSH keypair; the operator obtains the **public** half through
the CLI and registers it wherever the push must land. The private half is created in the container and
never leaves.

This finishes what Feature 018 started. 018 removed the private **host** key — inbound identity, which
only ever needed a public key to verify. This removes the private **push** key — outbound
authentication, which genuinely needs a private key and therefore had to be **relocated** rather than
eliminated. Afterwards the tool writes **no private key anywhere** on the operator's disk.

It is also a real least-privilege win rather than only a tidier one: `--push-key` is usually handed
the operator's *personal* key, so the container receives everything that key authorises. A
per-container key registered as a repository deploy key authorises one repository.

## The decisions this plan settles first

### 1. Clone-on-start over SSH becomes TWO-PHASE — the collision this plan exists to surface

**Found by reading the tree, and the spec does not address it.** `clone_credential_precheck` refuses to
start when `--repo` is an SSH URL and no push key was supplied:

```python
die(f"--repo {spec.repo} is an SSH URL but no push key is injected — pass --push-key …
     Refusing to start an empty-workspace agent (FR-014).")
```

That premise inverts here. The key is generated **inside** the container, so at first boot nothing is
registered yet and an SSH clone **cannot** succeed — the entrypoint's `git clone … || die` would fail
the boot. The capability does not survive unchanged, whatever we do.

**Settled: boot, register, redeploy.**

1. `up --repo <ssh-url>` starts the container, generates the key, and **does not clone** — saying so,
   and printing the public key with the exact command to run next.
2. The operator registers it.
3. `redeploy` clones.

**This deliberately relaxes FR-014**, which today refuses to start an empty-workspace agent. That
refusal exists so an operator never gets a silently useless container; here the container is
*deliberately* pending and says so, which serves the same intent by a different route. The relaxation
is narrow: **only** for an SSH `--repo` on a first boot with no registered key. Every other
empty-workspace refusal stands.

The alternative — refusing SSH clone-on-start entirely and pointing at `https://` + `GH_TOKEN` —
was rejected: it deletes a working capability, and for a non-github.com host `GH_TOKEN` does not
apply, so those operators would have no path at all.

### 2. The registration probe runs INSIDE the container, because that is where the key is

The operator's machine cannot test whether the key is registered: it does not have the private half —
which is the entire point of the feature. So the probe is `<runtime> exec … ssh -T <forge>`, run where
the key lives.

That placement has a property worth stating rather than discovering: **the probe inherits the same
egress the push will**. If Feature 012 has denied the container access to the forge, the probe fails
exactly as the push would, so a failed probe is genuinely predictive rather than a false alarm about
network conditions the agent will not face.

**It must fail soft.** A probe that cannot reach the forge — denied egress, offline, forge down — must
report "could not confirm" and **never** block or fail the deploy. FR-008 already forbids leaving the
operator believing the environment can push; it does not license refusing to deploy because a third
party is unreachable.

### 3. The generated key lives on the persisted `ssh` volume — amending Feature 003, deliberately

Stated in the spec (FR-003) and repeated here because it contradicts a CLAUDE.md invariant:
*tool-injected secrets land under `/run/…`, **never** on a volume*.

A key under `/run` dies with the container, so every recreate would need re-registration on the forge —
which makes the feature unusable. The original rule protects **operator-supplied** secrets from
persisting somewhere beyond the operator's control. A key the container generated and never exports
has no such origin; the volume **is** its home, exactly as for the host key since 018.

**The amendment is scoped to self-generated material.** Injected secrets stay ephemeral, and the
invariant is rewritten to say so rather than quietly weakened.

### 4. Removal surface: FOUR channels, and one is a precheck

Grepped, not recalled — the lesson 018 paid for:

| Channel | Site |
|---|---|
| `up --push-key` | CLI option → `do_up` |
| `redeploy --push-key` | CLI option → `do_redeploy` |
| `SSH_PUSH_KEY_B64` | env-file, consumed in `image/entrypoint.sh` |
| `target: push_key` | `CRED_SSH_TARGETS`, declarative `.agent-container/` |

Plus `stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH`, `clone_credential_precheck`, and the
stale `<state>/<host>/<name>.push_key` an upgrade must delete. **`--known-hosts` / `PUSH_KNOWN_HOSTS`
stay**: they verify the *forge*, which is the opposite direction and public data.

### 5. Reuse 018's capture, do not write a second one

`capture_host_pubkey` already reads a public key out of a container through the runtime, with the
bounded poll that exists because 016 measured `Up` preceding the entrypoint. Pointing it at a second
path is a parameter, not a new mechanism — and a second implementation would be a second thing to
drift.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI, POSIX shell entrypoint.

**New dependencies**: **none** (Constitution VI). `ssh-keygen` and the runtime are already used.

**Storage**: no new store. The generated key lives on the existing per-container `ssh` volume; the
captured public key is exposed through the existing machine-readable interface.

**Testing**: hermetic pytest for the removal census, the refusals, the two-phase clone decision and
the soft-failing probe; acceptance for what only real containers show — a generated key that persists
across recreate, a real `git push` with the registered key, and no private key anywhere on disk.

**Constraints**:

- **No private push key written anywhere** on the operator's machine (FR-001/FR-010).
- **The probe never blocks a deploy** (decision 2).
- **Key persists across recreate**, or registration is worthless (FR-003, SC-003).
- **`--purge` rotates it**, and that must be said (FR-007).

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, with a wrinkle worth naming.** The key is deliberately *not* ephemeral — it must survive recreate. It is not "work", so nothing of value is trapped, and `--purge` regenerating it is correct rather than lossy |
| **II. Least Privilege, Immutable Runtime** | **PASS, and strengthened.** A per-container deploy key authorises one repository where the operator's personal key authorised everything it could reach |
| **III. Least Exposure** | **PASS, and this is the point.** The last private key the tool writes to the operator's disk stops being written |
| **IV. Deterministic Identity** | **PASS** — no name, port or volume change |
| **V. Durable Spec** | **PASS** — clarified across two sessions; decisions 1 and 2 were settled before this plan was written |
| **VI. Least Dependencies** | **PASS** — nothing new |
| **VII. Continuous Deployment** | **`feat!` — BREAKING.** Four channels removed, and SSH clone-on-start changes shape |

## Project Structure

```text
bin/agent-container       generation trigger, capture of the agent SSH public key (reusing 018's),
                          the registration probe, the two-phase clone decision, removal of
                          --push-key from up/redeploy, stage_push_injection's push arm,
                          INJECT_PUSH_KEY_PATH, CRED_SSH_TARGETS' push_key, stale-file cleanup,
                          the list --json field
image/entrypoint.sh       generate the agent SSH key on the ssh volume if absent; derive its .pub;
                          delete the SSH_PUSH_KEY_B64 branch; make clone-on-start over SSH
                          PENDING rather than fatal when no key is registered
completions/*.bash|zsh    drop --push-key
docs/credentials.md       the outbound key is captured, not supplied; the /run rule amended for
                          self-generated material
docs/execution.md         clone-on-start over SSH is two-phase
docs/agent-interface.md   the new list --json field
docs/threat-model.md      reconcile — the last private-key write site removed; a signing key now
                          lives on a volume that outlives its container
CLAUDE.md                 the /run invariant is no longer absolute — say what it excludes
bin/tests/                census, refusals, two-phase, soft probe; acceptance for persistence,
                          a real push, and no private key on disk
```

## Design decisions carried into tasks

1. **Generate in the entrypoint**, on the `ssh` volume, only when absent (idempotent across boots).
2. **Capture through the runtime**, reusing 018's primitive (decision 5).
3. **Two-phase SSH clone-on-start** (decision 1), with the relaxation of FR-014 scoped to that case.
4. **The probe runs in the container and fails soft** (decision 2).
5. **Remove all four channels plus the precheck** (decision 4), each with an explaining refusal.
6. **`--purge` warns that the key rotates** and the registration dies with it (FR-007).

## Phasing

**P1 — the key exists and never leaves.** US1/US2. Generate, capture, expose, and remove the four
channels. **Prove no private key is on disk before building anything on top** — that is the feature.

**P2 — the operator knows what to do.** US3. What to register, when, and the probe.

**P3 — the honest edges.** The two-phase clone, `--purge` rotation, the stale file, and the threat
model.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A private key on a persisted volume | under `/run` it dies with the container, so every recreate needs re-registration on the forge — unusable | keeping it ephemeral; the feature does not work |
| Relaxing FR-014 for one case | the key cannot exist before the container does, so an SSH clone-on-start cannot succeed on a first boot | refusing SSH clone-on-start entirely — deletes a working capability, and `GH_TOKEN` does not apply to non-github.com hosts |
| A network probe in a deploy path | FR-011 asks the tool to stop nagging once pushing works, and only the forge knows | remembering a successful push — needs push-result reporting that does not exist; announcing once — cheap but silently wrong when registration was never done |
