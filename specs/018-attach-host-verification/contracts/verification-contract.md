# Contract: Verified Attach (Feature 018)

Numbered so tasks and tests can cite them. Each is testable.

## C1 — Capture happens on every deploy, through the runtime

Every deploy path captures the container's host public key by reading
`~/.ssh/hostkeys/ssh_host_ed25519_key.pub` **through the container runtime** (FR-003). The SSH
endpoint is never the source: reading an identity from the party being authenticated is not
verification.

## C2 — `attach` verifies, and refuses rather than prompting

`attach` runs with `UserKnownHostsFile=<tool file>` and `StrictHostKeyChecking=yes` (FR-004).
`accept-new` is forbidden — it silently trusts an unpinned host, which is the behaviour being
replaced.

## C3 — A substituted host key is refused

With the container's host key replaced out of band, `attach` **fails** and the message names the
mismatch (SC-003). Zero silent acceptances.

## C4 — A tool-caused recreation re-pins silently

After `down --purge` and recreate, `attach` succeeds with no mismatch warning (SC-004) — because the
recreate captured. Zero false alarms.

## C5 — Two environments on one host never cross-verify

Entries are keyed `[address]:port` (FR-005). One environment's key must not verify another's
connection (SC-005).

## C6 — The operator's own `known_hosts` is untouched

`~/.ssh/known_hosts` is byte-identical before and after any tool operation (FR-006, SC-007).

## C7 — A capture failure is loud and non-fatal

Capture failure leaves the deploy's exit status untouched (FR-008), warns, and **states that attach is
unverified**. No line is written from an empty or unparseable read — "pinned nothing" must not be
indistinguishable from "pinned correctly".

## C8 — Capture works over a REMOTE context

Capture succeeds where the operator's machine shares no filesystem with the daemon (FR-009, SC-006),
**verified against a remote context rather than inferred from a local run**.

## C9 — No private host key is written anywhere

No file on the operator's machine contains private host key material after any deployment path
(FR-001, FR-012, SC-001 at 100%).

## C10 — `--host-key` is gone, and says why

Passing `--host-key` fails with a message stating that host identity is captured rather than supplied
(FR-002).

## C11 — An upgrade deletes the stale private key and says so

Any `<state>/<host>/<name>.host_key` from an earlier version is removed on the next deploy, and the
removal is reported (FR-011). Silent deletion is wrong: an operator should learn a private key left
their disk.

## C12 — The captured key is obtainable

The operator can obtain a `known_hosts`-format line for a running environment through the existing
machine-readable interface (FR-010, US3), or a clear statement that none was captured — never a silent
empty result.

**This is also the non-TOFU answer for a second machine** — an entry copied from the machine that
deployed predates what it checks, where a fresh capture there would not (research R8). Preferred over
C13 whenever it is available.

## C13 — An unpinned attach asks, and says what accepting does not detect

With no entry for the environment, `attach` warns, shows the key's **fingerprint**, states that
accepting **cannot detect a container that was replaced**, and asks (FR-013, FR-016). Yes → capture,
pin, connect. No → refuse. **Never a silent capture, and never described as verification** (SC-009).

## C14 — A mismatch never prompts, and no answer means no

A mismatch is refused unconditionally, with or without a terminal (FR-014, SC-010). Where no answer can
be obtained, an unpinned attach refuses rather than assuming yes (FR-015, SC-011). `--print` and
`--ssh-config` never prompt; with nothing pinned they say so, and say the emitted command will refuse
(FR-017).
