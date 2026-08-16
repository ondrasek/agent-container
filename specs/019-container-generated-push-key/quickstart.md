# Quickstart: Validating the Container-Generated Push Key (Feature 019)

Runnable scenarios. Each names the contract (`C#`) and criterion (`SC-###`) it validates. Requirements
and field detail live in [spec.md](./spec.md), [data-model.md](./data-model.md) and
[contracts/](./contracts/push-key-contract.md).

**Prerequisites**: a working runtime, and a git forge account where you can add a **deploy key** to a
test repository. S3 and S12 need real network access to that forge.

**Read S1 first.** It is the whole feature, and it is an absence — the hardest kind to notice missing.

---

## S1 — No private push key anywhere (C1, SC-001)

```sh
agent-container up pk-demo
grep -rl 'PRIVATE KEY' "${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/" \
                       "${XDG_CONFIG_HOME:-$HOME/.config}/agent-container/" 2>/dev/null
```

**Expect**: **no output**. Combined with Feature 018's equivalent check, the tool now writes **no**
private key to your disk at all.

## S2 — The container made one, and it is public-half-visible (C1)

```sh
agent-container exec pk-demo -- ls -l ~/.ssh/push_ed25519_key ~/.ssh/push_ed25519_key.pub
```

**Expect**: private `0600`, public `0644`. The private half exists **only** here.

## S3 — Register the public key and push for real (C3, SC-002)

```sh
agent-container list --json | jq -r '.data.containers[] | select(.name|endswith("pk-demo")) | .push_public_key'
```

Paste that into the repository's **Deploy keys** (write access), then inside the container:

```sh
agent-container exec pk-demo -- git -C /workspace push
```

**Expect**: the line pastes **verbatim** with no reformatting (SC-004), and the push succeeds. This is
the scenario that proves the feature does the job — everything else proves it does it safely.

## S4 — The key survives recreation (C4, SC-003)

```sh
agent-container exec pk-demo -- cat ~/.ssh/push_ed25519_key.pub > /tmp/before
agent-container down pk-demo && agent-container up pk-demo
agent-container exec pk-demo -- cat ~/.ssh/push_ed25519_key.pub > /tmp/after
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

**Expect**: a warning that the push key was regenerated and the previous registration is now dead, and
a new public key. Nothing else in the system would tell you.

## S6 — Every removed channel explains itself (C6, SC-007)

```sh
agent-container up gone --push-key ~/.ssh/id_ed25519;      echo "exit=$?"
agent-container redeploy gone --push-key ~/.ssh/id_ed25519; echo "exit=$?"
agent-container up gone2 -e <(echo 'SSH_PUSH_KEY_B64=abc')
```

**Expect**: each fails non-zero with a message saying the push key is generated in the container and
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

**Expect**: the container **starts**, does **not** clone, says so, and prints the key with the exact
next command. Register it, then:

```sh
agent-container redeploy two-phase
agent-container exec two-phase -- ls /workspace
```

**Expect**: now cloned. The first step deliberately relaxes the empty-workspace refusal for this case
only — the container is *pending and says so*, not silently useless.

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
