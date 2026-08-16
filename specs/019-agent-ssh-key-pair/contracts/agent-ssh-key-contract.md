# Contract: Agent SSH Key Pair (Feature 019)

Numbered so tasks and tests can cite them.

## C1 — The container generates its own key, and it never leaves

The agent SSH key pair is created **inside** the container on its persisted `ssh` volume. No private half
exists anywhere on the operator's machine after any deployment path (FR-001, FR-010, SC-001 at 100%).

## C2 — Generation is idempotent

An existing key is kept on every subsequent boot. Regenerating would silently invalidate the
operator's registration while every other symptom looked healthy (data-model §2).

## C3 — The public key is obtainable, without reaching the container

Through the existing machine-readable interface, in a form that pastes directly into a deploy-key
field (FR-004, SC-004). The answer comes from what was captured, so a **stopped environment or an
unreachable host still answers** (FR-005, SC-006) — that is when an operator most needs it.

## C4 — The key survives recreation

`down` then `up` keeps it, so a registered key keeps working with **zero** re-registrations
(FR-003, SC-003).

## C5 — `--purge` rotates it, loudly

`--purge` destroys the volume, so the key is regenerated and the old registration is dead. The tool
**says so** (FR-007); nothing else would.

## C6 — Every supplying channel is removed, and each explains itself

`up --push-key`, `redeploy --push-key`, `SSH_PUSH_KEY_B64` and `target: push_key` all fail with a
message explaining that the agent SSH key is generated in the container and its public half registered
(FR-002, SC-007). A declared `push_key` is **refused**, never ignored.

## C7 — A stale staged key is deleted, and stated

Any `<state>/<host>/<name>.push_key` from an earlier version is removed on the next deploy and the
removal reported (FR-009). Silent deletion is wrong: an operator should learn a private key left their
disk, because copies may exist elsewhere.

## C8 — The deploy says what to register, before the agent needs it

A deploy of an environment that will push over SSH states the public key and that pushes fail until it
is registered (FR-006, SC-005) — unless the probe says it already works.

## C9 — The probe runs in the container and FAILS SOFT

Registration is checked by `ssh -T <forge>` **inside** the container, where the key is — the operator's
machine has nothing to authenticate with. A forge that cannot be reached yields `unknown`, never
`not-registered`, and **never blocks or fails the deploy** (FR-011, research R3).

## C10 — SSH clone-on-start is two-phase

With an SSH `--repo` and no registered key, the container **starts without cloning**, says so, and
prints the key and the next command (data-model §4). This relaxes FR-014 for **this case only**; every
other empty-workspace refusal stands.

## C11 — The HTTPS path is untouched

`--repo https://…` with `GH_TOKEN` clones and pushes exactly as before (FR-012). `--known-hosts` and
`PUSH_KNOWN_HOSTS` are unaffected — they verify the forge, not the container.

## C12 — A per-container key authorises only what was registered

The key grants access to what the operator registered it for and nothing else — verified by confirming
a second repository is **not** reachable with it (SC-008). This is the least-privilege gain over
injecting the operator's own key.
