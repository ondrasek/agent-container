# Contract: Agent SSH Key Pair (Feature 019)

Numbered so tasks and tests can cite them.

## C1 — The container generates its own key, and it never leaves

The agent SSH key pair is created **inside** the container at **`~/.ssh/id_ed25519`** — the
conventional identity path, which is already the persisted `ssh` volume's mount point. Being
conventional is load-bearing: git, `ssh`, `scp` and `rsync` all use it with no wiring, so
`core.sshCommand` and `PUSH_RUNTIME` are deleted rather than rewired. No private half
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
machine has nothing to authenticate with. It targets **only the host of `--repo`**; with no `--repo`
there is no probe and the key is reported *unverified*, never assumed good or bad. A forge that cannot be reached yields `unknown`, never
`not-registered`, and **never blocks or fails the deploy** (FR-011, research R3).

## C10 — SSH clone-on-start is two-phase

With an SSH `--repo` and no registered key, the container **starts without cloning**, says so, prints
the key and the next command, and **exits 3 (*pending registration*)**
(data-model §4). The output MUST state that tearing the environment down destroys the key and that the
recovery is **register, then `redeploy`** — a caller that reads only the exit status will otherwise
recreate, regenerating the key it was about to register. This relaxes FR-014 for **this case only**; every
other empty-workspace refusal stands.

## C11 — The HTTPS path is untouched

`--repo https://…` with `GH_TOKEN` clones and pushes exactly as before (FR-012). `--known-hosts` and
`PUSH_KNOWN_HOSTS` are unaffected — they verify the forge, not the container.

## C13 — `~/.ssh/config` is written once, and rotation is explicit

The tool **appends its block** to the agent's `~/.ssh/config` if absent and never rewrites it
(FR-014) — write-once applies to the **block**, not the file, so a config the agent created earlier
still gains the tool's settings while keeping its own entries. The block states `IdentityFile`,
`IdentitiesOnly`, `UserKnownHostsFile` and `StrictHostKeyChecking` **explicitly** rather than relying
on ssh's defaults.

`agent-container ssh-key show <name>` and `ssh-key rotate <name>` are the surface (FR-004a) — not part
of `keys`, which injects *authorized* keys. The key can be **regenerated deliberately** without
destroying the environment (FR-015), and doing so
states that the previous registration is dead. `--purge` also rotates it, as a side effect of
destroying the volume — that is the large hammer, not the intended one.

## C12 — A per-container key authorises only what was registered

The key grants access to what the operator registered it for and nothing else — verified by confirming
a second repository is **not** reachable with it (SC-008). This is the least-privilege gain over
injecting the operator's own key.


## C14 — Exit codes are documented, in `--help` and in `docs/`

`0` success · `1` failure · `2` refused (usage error **or** a destructive action declined without `-y`
on a non-TTY) · `3` pending registration (FR-014a, SC-012).

Two caveats are stated rather than left to be discovered: `2` is **shared** with the CLI framework's
usage-error code, and a headless `--foreground` run **propagates the agent's** exit code so the status
is not the tool's. A test binds the documented values to the enforced ones.

## C15 — Generation failure is loud, and never silent

A failure to generate the key MUST be surfaced and MUST NOT yield a container that starts, cannot
authenticate, and says nothing (FR-008, SC-010).

## C16 — The HTTPS path still works

Clone and push over HTTPS + `GH_TOKEN` are verified after every removal in this feature (FR-012,
SC-011) — three deletions sit beside that credential helper, and nothing else would catch collateral
damage to it.
