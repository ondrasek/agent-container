# Quickstart: Validating Verified Attach (Feature 018)

Runnable scenarios that prove the feature works. Each names the contract (`C#`) and criterion (`SC-###`)
it validates. Requirements and field detail live in [spec.md](./spec.md),
[data-model.md](./data-model.md) and [contracts/](./contracts/verification-contract.md) — not repeated
here.

**Prerequisites**: a working runtime (Podman or Docker), the CLI on `PATH`, and a registered host. On
macOS + Lima, any working directory used for a bind must be Lima-shared.

Throughout: `KH="${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/<host>/known_hosts"`.

---

## S1 — Attach is verified, with no prompt (C2, SC-002)

```sh
agent-container up --name verify-demo
ssh-keygen -F "[127.0.0.1]:$(cat "$(dirname "$KH")"/verify-demo.port)" -f "$KH"
agent-container attach --name verify-demo --print
```

**Expect**: the lookup finds an `ssh-ed25519` line, and the printed argv contains
`UserKnownHostsFile=<that file>` and `StrictHostKeyChecking=yes`. Attaching produces **no**
trust-on-first-use prompt.

`--print` matters here: it shows the argv without needing an interactive terminal, so the
verification options can be asserted directly rather than inferred from a successful connection.

## S2 — A substituted host key is REFUSED (C3, SC-003)

The most important scenario. Replace the container's host key **without the tool's involvement**:

```sh
agent-container exec --name verify-demo -- \
  sh -c 'rm -f ~/.ssh/hostkeys/ssh_host_ed25519_key* &&
         ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/hostkeys/ssh_host_ed25519_key &&
         pkill sshd'
# restart sshd however the environment does, then:
agent-container attach --name verify-demo
```

**Expect**: **failure**, with a message naming the host-key mismatch. A success here means the pin is
decoration — the feature does not work regardless of what else passes.

## S3 — A tool-caused recreation re-pins silently (C4, SC-004)

```sh
agent-container down --name verify-demo --purge
agent-container up   --name verify-demo
agent-container attach --name verify-demo --print
```

**Expect**: the pinned line **changed** (the volume was purged, so the key is new) and attach carries
no mismatch warning. The recreate *is* a deploy, so it captured — this is decision R4 working, and
S2/S3 together are the two halves that must not collapse into each other.

## S4 — Two environments on one host never cross-verify (C5, SC-005)

```sh
agent-container up --name env-a
agent-container up --name env-b
grep -c . "$KH"     # two lines
```

**Expect**: two entries, keyed `[127.0.0.1]:<port-a>` and `[127.0.0.1]:<port-b>`, with **different**
keys. Confirm the keying is what refuses a cross-match:

```sh
ssh-keygen -F "[127.0.0.1]:<port-b>" -f "$KH"   # env-b's key, never env-a's
```

## S5 — No private host key anywhere (C9, SC-001)

```sh
grep -rl 'PRIVATE KEY' "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/" \
                       "${XDG_CONFIG_HOME:-$HOME/.config}/agent-container/" 2>/dev/null
```

**Expect**: **no output**. Run it after every deployment path you can construct — this is the
100%-or-fail criterion, and the whole point of the feature.

## S6 — `--host-key` is gone and explains itself (C10)

```sh
agent-container up --name gone --host-key /some/key; echo "exit=$?"
```

**Expect**: non-zero, with a message saying host identity is **captured, not supplied**. A bare
"unrecognized argument" is a fail: an operator who used the flag deserves to learn where it went.

## S7 — A stale staged private key is deleted, loudly (C11)

Simulate what an older version left behind:

```sh
printf 'x\n' > "$(dirname "$KH")/verify-demo.host_key"
agent-container up --name verify-demo
ls "$(dirname "$KH")/verify-demo.host_key"     # must not exist
```

**Expect**: the file is gone and the deploy **said** it removed a private host key. Silent deletion
fails this scenario — an operator should learn a private key left their disk.

## S8 — The operator's own `known_hosts` is untouched (C6, SC-007)

```sh
shasum ~/.ssh/known_hosts > /tmp/kh.before
agent-container up --name untouched && agent-container attach --name untouched --print
shasum -c /tmp/kh.before
```

**Expect**: `OK`. Byte-identical, before and after.

## S9 — Capture failure is loud, and the deploy still succeeds (C7, SC-008)

Force the read to fail (e.g. point the tool at a container whose `ssh` volume has no host key yet, or
interrupt the daemon mid-capture).

**Expect**: exit status **unchanged** (the deploy succeeded), a warning that the host key could not be
captured, and an explicit statement that **attach will be unverified**. Then check the file:

```sh
grep -c "$(cat "$(dirname "$KH")"/failing.port)" "$KH"    # zero — nothing written
```

**Expect**: no entry at all. A blank or malformed line here is the defect this scenario exists to
catch: "pinned nothing" must not look like "pinned correctly".

## S10 — Capture works over a REMOTE context (C8, SC-006)

```sh
agent-container host add remote-box --ssh user@remote-box
agent-container up --name remote-verify --host remote-box
grep . "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/remote-box/known_hosts"
```

**Expect**: an entry keyed by the remote address and port. **Must be run against a real remote
context**, not inferred from a local run — SC-006 says so because the operator's machine shares no
filesystem with that daemon.

## S11 — The captured key is obtainable (C12, US3)

```sh
agent-container ... --json | ...   # the machine-readable interface (FR-010)
```

**Expect**: a `known_hosts`-format line for a running environment, usable verbatim on another client;
and for an environment with no capture, an explicit statement of that — never a silent empty result.

---

## What "done" looks like

The unusual part of this feature: **the strongest evidence is an absence.** S5 finding nothing and S2
refusing are worth more than every other scenario passing, because a pin that never refuses and a
private key that is merely unused both look exactly like success.
