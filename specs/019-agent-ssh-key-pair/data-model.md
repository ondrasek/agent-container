# Data Model: Agent SSH Key Pair (Feature 019)

## §1 No new store, and one file that stops existing

| Artefact | Where | Lifetime |
|---|---|---|
| agent SSH **private** key | **`~/.ssh/id_ed25519`** — the conventional path, which IS the persisted `ssh` volume | survives `down`/`up`; **dies with `--purge`**, or an explicit rotate |
| agent SSH **public** key | `~/.ssh/id_ed25519.pub`, world-readable | same |
| `~/.ssh/config` | same volume; **written once, never rewritten** | survives everything except `--purge` |
| captured public key | the tool's local state, for FR-004 | re-capturable; safe to delete |
| ~~`<state>/<host>/<name>.push_key`~~ | ~~operator's disk, 0644~~ | **deleted, and no longer written** |

The last row is the feature. After 018 removed the host key's staged copy, this was the **only**
private key the tool still wrote to the operator's disk — and `--purge` never removed it either.

**The conventional path is load-bearing.** Git shells out to `ssh`, which reads `~/.ssh/id_ed25519`
automatically — so `core.sshCommand` and its `PUSH_RUNTIME` scaffolding (11 references) are **deleted**
rather than rewired, and every outbound SSH the agent makes uses one registered identity instead of
git alone holding a credential nothing else can reach.

## §2 The key's lifecycle

```text
first boot        -> generate on the ssh volume if absent; derive the .pub
every boot after  -> keep it (idempotent) — a regenerated key would silently
                     invalidate the operator's registration
deploy            -> capture the .pub through the runtime; expose it
down / up         -> unchanged: the volume persists, so the registration keeps working
--purge           -> the volume goes, so the key is REGENERATED and the old
                     registration is dead. WARN, because nothing else would say so
explicit rotate   -> the proportionate hammer: a new key WITHOUT destroying the
                     workspace, stating that the old registration is dead (FR-014b).
                     A suspected compromise is when rotation must be cheap
```

**Idempotence is load-bearing.** Regenerating on every boot would break the operator's registration
on each restart while every other symptom looked healthy — the failure would surface as a push
failing days later.

## §3 Registration state — computed, never stored

| Result | Meaning |
|---|---|
| `registered` | the forge accepted the key |
| `not-registered` | the forge answered, and rejected it |
| `unknown` | the forge could not be reached — **denied egress, offline, or down** |

**Never stored.** Registration lives on the forge, not here; a cached "registered" would go stale the
moment an operator revokes the key, and the tool would then assure them of something false.

`unknown` must **never** be reported as either of the others, and must **never** fail a deploy
(research R3). The probe runs **inside the container**, so it inherits the same egress the push will —
which is what makes a `not-registered` answer predictive rather than a guess.

## §3a `~/.ssh/config` — written once, then the agent's

Content is **static** (`IdentitiesOnly`, a fixed `IdentityFile`, a fixed `UserKnownHostsFile`), so
there is nothing a per-boot rewrite could update. It is written **if absent** and never rewritten
(FR-014a): rewriting would discard edits the agent legitimately makes — a jump host, a per-host user —
while gaining nothing. Only the *contents* of the referenced `known_hosts` vary, through their own
injection path.

## §4 Clone-on-start becomes a three-way decision

```text
--repo https://…            -> clone (GH_TOKEN; unchanged)
--repo ssh://…, key registered   -> clone
--repo ssh://…, NOT registered   -> START, DO NOT CLONE, say so, print the key
                                    and the exact next command, and EXIT NON-ZERO
                                    with a DISTINCT "pending registration" code
```

**The non-zero exit carries a hazard the wording must defuse.** An automated caller seeing failure will
reasonably `down` and retry — destroying the key awaiting registration, so the retry generates a
different one and the loop never terminates. The output must therefore state that tearing down destroys
the key and that the recovery is **register, then `redeploy`**.

The third row **relaxes FR-014**, which today refuses to start an empty-workspace agent. That refusal
exists so nobody receives a silently useless container; here the container is *deliberately* pending
and announces it, which serves the same intent. **The relaxation is scoped to this row alone** —
every other empty-workspace refusal stands.

## §5 What is removed

| Channel | Fate |
|---|---|
| `up --push-key`, `redeploy --push-key` | **removed**; using one fails with an explanation |
| `SSH_PUSH_KEY_B64` | **removed** from the entrypoint |
| `target: push_key` | **refused**, not ignored — silently dropping it leaves an operator believing their key is in use |
| `stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH`, `clone_credential_precheck` | deleted |
| `--known-hosts` / `PUSH_KNOWN_HOSTS` | **kept** — they verify the *forge*, opposite direction, public data |
