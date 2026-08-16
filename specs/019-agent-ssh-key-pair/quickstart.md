# Quickstart: Validating the Agent SSH Key Pair (Feature 019)

Runnable scenarios. Each names the contract (`C#`) and criterion (`SC-###`) it validates. Requirements
and field detail live in [spec.md](./spec.md), [data-model.md](./data-model.md) and
[contracts/](./contracts/agent-ssh-key-contract.md).

**Prerequisites**: a working runtime, and a git forge account where you can add a **deploy key** to a
test repository. S3 and S12 need real network access to that forge.

**Read S1 first.** It is the whole feature, and it is an absence — the hardest kind to notice missing.

---

## S1 — No agent SSH private key on the operator's disk (C1, SC-001)

```sh
agent-container up pk-demo
grep -rl 'PRIVATE KEY' "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/" \
                       "${XDG_CONFIG_HOME:-$HOME/.config}/agent-container/" 2>/dev/null
```

**Expect**: **no output**. Combined with Feature 018's equivalent check, the tool now writes **no**
private key to your disk at all.

## S2 — The container made one, and it is public-half-visible (C1)

```sh
agent-container exec pk-demo -- ls -l ~/.ssh/id_ed25519 ~/.ssh/id_ed25519.pub ~/.ssh/config
```

**Expect**: private `0600`, public `0644`, and a `config` containing the tool's block **explicitly**:

```
Host *
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    UserKnownHostsFile ~/.ssh/known_hosts
    StrictHostKeyChecking accept-new
```

The private half exists **only** here.

The **conventional path** is the point: nothing had to be wired for git to use it, and `ssh`, `scp`
and `rsync` use it too. Confirm no wiring survives:

```sh
agent-container exec pk-demo -- git config --global --get core.sshCommand; echo "exit=$?"
```

**Expect**: empty, non-zero — `core.sshCommand` is gone, not rewired.

## S3 — Register the public key and push for real (C3, SC-002)

```sh
agent-container ssh-key show pk-demo
# or from the row, for an agent:
agent-container list --json | jq -r '.data.containers[] | select(.name|endswith("pk-demo")) | .agent_ssh_public_key'
```

Paste that into the repository's **Deploy keys** (write access), then inside the container:

```sh
agent-container exec pk-demo -- git -C /workspace push
```

**Expect**: the line pastes **verbatim** with no reformatting (SC-004), and the push succeeds. This is
the scenario that proves the feature does the job — everything else proves it does it safely.

## S4 — The key survives recreation (C4, SC-003)

```sh
agent-container exec pk-demo -- cat ~/.ssh/agent_ssh_ed25519_key.pub > /tmp/before
agent-container down pk-demo && agent-container up pk-demo
agent-container exec pk-demo -- cat ~/.ssh/agent_ssh_ed25519_key.pub > /tmp/after
diff /tmp/before /tmp/after && echo "unchanged — no re-registration needed"
```

**Expect**: identical. **Zero** re-registrations. If this fails, generation is not idempotent and every
restart silently invalidates the operator's registration — a failure that would surface days later as a
push that stopped working.

## S5 — `--purge` rotates it, and says so (C5)

```sh
agent-container down pk-demo --purge
agent-container up pk-demo
```

**Expect**: a warning that the agent SSH key was regenerated and the previous registration is now dead, and
a new public key. Nothing else in the system would tell you.

## S6 — Every removed channel explains itself (C6, SC-007)

```sh
agent-container up gone --push-key ~/.ssh/id_ed25519;      echo "exit=$?"
agent-container redeploy gone --push-key ~/.ssh/id_ed25519; echo "exit=$?"
agent-container up gone2 -e <(echo 'SSH_PUSH_KEY_B64=abc')
```

**Expect**: each fails non-zero with a message saying the agent SSH key is generated in the container and
its public half registered. A bare "unrecognized argument" is a **fail** — an operator who used this
flag had a reason, and it is now served without a private key on their disk.

## S7 — A declared `push_key` is refused, not ignored (C6)

Put `target: push_key` in `.agent-container/environments.yaml`, then `agent-container plan`.

**Expect**: refused with the same explanation. Silently dropping it would leave you believing your key
is in use.

## S8 — A stale staged key is deleted, loudly (C7)

```sh
printf 'x\n' > "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/local/pk-demo.push_key"
agent-container redeploy pk-demo
ls "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/local/pk-demo.push_key"   # must not exist
```

**Expect**: gone, and the deploy **said** it removed a private key. Silent deletion fails this: copies
may exist elsewhere and you should know to treat them as exposed.

## S9 — The deploy tells you what to register (C8, SC-005)

Deploy a fresh environment whose repository is an SSH remote.

**Expect**: the output includes the public key and states plainly that pushes fail until it is
registered. Discovering that from a failed push mid-run trades a security win for a worse experience.

## S10 — The probe fails SOFT (C9)

Deploy with egress enforced and the forge **not** declared (Feature 012), or simply offline.

**Expect**: the deploy **succeeds**, and the report says registration could not be confirmed —
`unknown`, never "not registered". A probe that blocked a deploy because a third party was unreachable
would be a worse failure than the one it prevents.

## S11 — SSH clone-on-start is two-phase (C10)

```sh
agent-container up two-phase --repo git@github.com:you/test.git
```

**Expect**: the container **starts**, does **not** clone, says so, prints the key with the exact next
command, and **exits non-zero** with the distinct *pending registration* code.

**Check the wording, not just the code**: it must say that tearing the environment down destroys the
key, and that the fix is register-then-`redeploy`. An agent that reads only the exit status will
otherwise `down` and retry — regenerating the very key it was about to register, forever.

Register it, then:

```sh
agent-container redeploy two-phase
agent-container exec two-phase -- ls /workspace
```

**Expect**: now cloned. The first step deliberately relaxes the empty-workspace refusal for this case
only — the container is *pending and says so*, not silently useless.

## S13 — `~/.ssh/config` is written once, not clobbered (C13, FR-014a)

```sh
agent-container exec pk-demo -- sh -c 'echo "Host myjump" >> ~/.ssh/config'
agent-container down pk-demo && agent-container up pk-demo
agent-container exec pk-demo -- grep myjump ~/.ssh/config
```

**Expect**: the agent's own edit **survives** the recreate, *and* the tool's block is still present.

Then the harder half — a config that existed **before** any deploy:

```sh
agent-container down cfg-demo --purge
agent-container up cfg-demo   # fresh volume
agent-container exec cfg-demo -- sh -c 'printf "Host early\n" > ~/.ssh/config'
agent-container down cfg-demo && agent-container up cfg-demo
agent-container exec cfg-demo -- grep -c "IdentitiesOnly" ~/.ssh/config
```

**Expect**: `1`. Write-once applies to the **block**, not the file — a config the agent created first
must still gain the tool's settings, or `StrictHostKeyChecking` is never set and every SSH the agent
attempts hangs on an interactive prompt it cannot answer. A tool that rewrote this file each boot
would discard it silently, and the agent would have no way to discover why its jump host stopped
working.

## S14 — Rotation is explicit and proportionate (C13, FR-014b)

```sh
agent-container exec pk-demo -- cat ~/.ssh/id_ed25519.pub > /tmp/old
agent-container ssh-key rotate pk-demo
agent-container exec pk-demo -- cat ~/.ssh/id_ed25519.pub > /tmp/new
diff /tmp/old /tmp/new; agent-container exec pk-demo -- ls /workspace
```

**Expect**: a **different** key, an explicit statement that the previous registration is now dead, and
the **workspace intact**. `--purge` also rotates the key — by destroying everything, which is the
wrong tool when the workspace is worth keeping.

## S12 — The key authorises only what you registered (C12, SC-008)

With the key registered on repository A only, from inside the container:

```sh
agent-container exec pk-demo -- git ls-remote git@github.com:you/repo-B.git
```

**Expect**: **denied**. This is the least-privilege gain — `--push-key` typically handed the container
your personal key, which reaches everything that key reaches.

---

## What "done" looks like

**S1 and S12 are the point.** S1 is an absence, and S12 is a permission that is *narrower* than before
— neither is visible in a passing test that only checks the push works. S4 is the one that will break
quietly if generation is not idempotent, and its symptom would arrive days later.


## S15 — Exit codes are documented and match reality (C14, SC-012)

```sh
agent-container --help | grep -A6 -i "exit code"
agent-container up two-phase --repo git@github.com:you/test.git > /dev/null 2>&1; echo "exit=$?"
```

**Expect**: `--help` lists `0` success, `1` failure, `2` refused, `3` pending registration — and the
deferred clone really exits **3**. The documented values and the enforced ones must be the same, which
is why a test binds them rather than trusting the prose.

Both caveats must appear: `2` is shared with the CLI framework's usage-error code, and a headless
`--foreground` run propagates the **agent's** exit code rather than the tool's.

## S16 — Key generation failure is loud (C15, SC-010)

Make generation fail (a read-only `~/.ssh`, or a full volume), then deploy.

**Expect**: the failure is **stated**. A container that starts, cannot authenticate anywhere, and says
nothing is the outcome this scenario exists to make impossible — the agent would discover it as an
inexplicable permission denied, hours later.

## S17 — The HTTPS path still works (C16, SC-011)

```sh
agent-container up https-demo --repo https://github.com/you/test.git
agent-container exec https-demo -- git -C /workspace push
```

**Expect**: clone and push both succeed on `GH_TOKEN` alone, with no SSH key involved. Three deletions
in this feature sit beside that credential helper, and nothing else would catch collateral damage.
