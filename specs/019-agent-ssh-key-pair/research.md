# Research: The Agent SSH Key Pair Is Generated In the Container (Feature 019)

Phase 0. Each entry records a **decision**, its **rationale**, and what was **rejected** — and where a
fact is claimed, how it was established.

---

## R1 — The 018 argument does NOT transfer, and the difference is the whole design

**Decision**: relocate the private key into the container; do not attempt to eliminate it.

**Rationale**: for **inbound** identity the container proves itself *to us*, so `known_hosts` needs
only a public key and the private half can stay put — that is Feature 018. For **outbound**
authentication the container proves *our* identity *to a forge*, and signing requires possessing a
private key. There is no public-key-only `git push`.

So the same headline ("the private key never leaves the container") is reached by a different move:
018 **removed** a key that bought nothing; 019 **relocates** one that is genuinely needed. Anyone
reading the two features together will assume the same trick twice, which is why this is R1.

**Rejected**: eliminating the key (impossible — outbound auth needs one); leaving `--push-key` in
place (the exposure the feature exists to remove).

---

## R2 — Clone-on-start over SSH cannot work on a first boot

**Decision**: **two-phase** — boot, register, redeploy. FR-014's empty-workspace refusal is relaxed
**only** for this case.

**Rationale**: read from the tree. `clone_credential_precheck` today refuses to start when `--repo` is
an SSH URL and no key was supplied, and the entrypoint's clone is `git clone … || die`. Both
assume the key predates the container. Under 019 the key is generated **inside** it, so on a first
boot nothing is registered and an SSH clone cannot succeed — the capability does not survive
unchanged whatever we choose.

Two-phase keeps it working: `up` starts the container, generates the key, **does not clone**, and
prints the public key with the exact next command. The operator registers. `redeploy` clones.

**The relaxation is narrow and serves FR-014's intent rather than defeating it.** That refusal exists
so an operator never receives a silently useless container. Here the container is *deliberately*
pending and says so — the opposite of silent. Every other empty-workspace refusal stands.

**Rejected**: refusing SSH clone-on-start and pointing at `https://` + `GH_TOKEN` — it deletes a
working capability, and the entrypoint's own comment records that `GH_TOKEN` is **github.com-scoped**,
so operators on any other forge would be left with no path at all. Also rejected: keeping
`--push-key` solely to seed the first clone — it preserves the 0644 file on disk and SC-001 could not
hold.

---

## R3 — The probe belongs INSIDE the container, and that is not a convenience

**Decision**: `<runtime> exec … ssh -T <forge>`, run in the container. Fails **soft**.

**Rationale**: the operator's machine **cannot** answer the question. It does not hold the private
key — which is the entire point of the feature — so it has nothing to authenticate with. The probe
must run where the key is.

That placement has a property worth stating rather than stumbling into: **the probe inherits the same
egress the push will**. If Feature 012 has denied the container access to the forge, the probe fails
exactly as the eventual push would, so a negative result is genuinely predictive rather than a false
alarm about network conditions the agent will never face.

**Failing soft is a requirement, not politeness.** Denied egress, an offline operator, or a forge
outage must produce "could not confirm" and never block the deploy. FR-008 forbids leaving an operator
believing the environment can push; it does not license refusing to deploy because a third party is
unreachable.

**Rejected**: probing from the operator's machine (no key to authenticate with); remembering a
successful push (requires push-result reporting from container to tool, which does not exist —
Feature 016 records run outcomes, not per-push results); announcing once per generated key (cheap and
stateless, but silently wrong for the operator who never registered, which is exactly the case the
requirement exists to catch).

---

## R4 — The generated key lives on the `ssh` volume, amending Feature 003

**Decision**: persist it on the existing per-container `ssh` volume; scope the amendment to
**self-generated** material.

**Rationale**: CLAUDE.md records the 003 invariant — *tool-injected secrets land under
`/run/agent-container/…`, **never** on a volume*. A key under `/run` dies with the container, so every
recreate would need re-registration on the forge, which makes the feature unusable.

The rule exists to stop **operator-supplied** secrets persisting somewhere beyond the operator's
control: they arrived from outside, and the tool should not extend their life. A key the container
generated and never exports has no such origin — the volume is its home, exactly as for the host key
since 018.

**Stating the amendment is the point.** An invariant quietly broken is worse than one deliberately
changed, and the next reader of CLAUDE.md must find the exception rather than infer a contradiction.

**Rejected**: `/run` (feature does not work); a new volume (the `ssh` volume already exists and already
holds exactly this kind of material).

---

## R5 — Four removal channels, and a precheck

**Decision**: remove `up --push-key`, `redeploy --push-key`, `SSH_PUSH_KEY_B64`, `target: push_key`,
plus `stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH` and `clone_credential_precheck`. Delete
any stale `<state>/<host>/<name>.push_key` and say so.

**Rationale**: grepped rather than recalled — the lesson Feature 018 paid for, where recall found one
channel and grep found five. Each removal must **explain itself**: an operator who used `--push-key`
had a reason, and it is now served without a private key on their disk.

**`--known-hosts` and `PUSH_KNOWN_HOSTS` stay.** They let the container verify the *forge* — the
opposite direction, public data, and unaffected.

**Rejected**: leaving any channel "for compatibility" (SC-001 is 100% and one survivor makes a 95%
removal indistinguishable from a complete one by every other test).

---

## R6 — Reuse 018's capture

**Decision**: point `capture_host_pubkey`'s mechanism at the agent SSH key's `.pub`; do not write a second
capture.

**Rationale**: it already reads a public key out of a container through the runtime, with the bounded
poll that exists because Feature 016 **measured** the runtime publishing `Up` before the entrypoint
executes a line. A second implementation would be a second thing to drift, and the subtlety it
encodes (poll, validate, refuse empty) is exactly what a fresh copy would omit.

**Rejected**: a parallel `capture_push_pubkey` (duplicate); reading the key from a volume mount (fails
over a remote context, the 001/003 lesson).
