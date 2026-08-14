# Research: Verified Attach, Without a Private Host Key on Disk (Feature 018)

Phase 0. Each entry records a **decision**, its **rationale**, and what was **rejected** — and where
a fact is claimed, how it was established.

---

## R1 — The public key is already there; nothing in the image changes to enable capture

**Decision**: capture `~/.ssh/hostkeys/ssh_host_ed25519_key.pub` from inside the container.

**Rationale**: read from `image/entrypoint.sh`, not assumed. The host key lives at
`${SSH_DIR}/hostkeys/ssh_host_ed25519_key` on the per-container `ssh` volume, and after installing or
generating it the entrypoint derives the public half and relaxes its mode:

```sh
ssh-keygen -y -f "${HOSTKEY}" > "${HOSTKEY}.pub"
chmod 0644 "${HOSTKEY}.pub"
```

So the artefact this feature needs already exists, is already world-readable inside the container, and
is regenerated whenever the key is. **Capture requires no image change at all** — which is most of
why this feature is small.

**Rejected**: having the entrypoint publish the key somewhere new (a second mechanism that could
disagree with the first); deriving it on the operator's machine (requires the private key, i.e. the
thing being removed).

---

## R2 — The pinned file is DERIVED HOST STATE

**Decision**: `$XDG_STATE_HOME/agent-container/<host>/known_hosts`, beside `.port`.

**Rationale**: Feature 011 documents that location as *"computed; safe to delete"*, and for this file
that is literally true — delete it and the tool re-captures from the running container. It is also
correctly **per host**: when a host goes, its containers go, so its pins are meaningless.

The contrast with Feature 014 is the useful part. 014's inventory must be **durable** and must
outlive its host, because it answers *what did we ever create*. This answers *is this the container I
created* — present tense, worthless once the container is gone. Same shaped question, opposite
lifetime, so opposite location.

**Consequence: no `docs/layout.md` row and no new location.** A new file in an existing category.

**Rejected**: `$XDG_DATA_HOME/agent-container/…` beside the run records and inventory (it is not
durable data — treating it as such invites someone to preserve a pin whose container is long gone);
the operator's `~/.ssh/known_hosts` (FR-006 forbids it, and SC-007 asserts that file is untouched).

---

## R3 — `[address]:port` keying, and it is measured because FR-005 rests on it

**Decision**: one line per environment, `[<address>]:<port> ssh-ed25519 AAAA…`.

**Rationale**: FR-005 requires that two environments sharing an address and differing only by port do
not verify each other's connections. That is a property of the `known_hosts` format, so it was
measured rather than assumed:

| Lookup against a file containing `[127.0.0.1]:2222 …` | Result |
|---|---|
| `ssh-keygen -F '[127.0.0.1]:2222'` | **found** |
| `ssh-keygen -F '[127.0.0.1]:2223'` | **not matched** |
| `ssh-keygen -F '127.0.0.1'` | **not matched** |

So the standard bracket-port form gives FR-005 for free, and the bare-host form would have silently
broken it — one container's key verifying another's connection, on a tool whose whole premise is
running several containers on one host.

**Rejected**: one file per environment (more files, no benefit — the format already namespaces by
port); a bare-host entry (measured to cross-match, which is the defect FR-005 names).

---

## R4 — Capture at EVERY deploy, which makes FR-007 disappear

**Decision**: capture and re-pin on every deploy path. `attach` never re-pins.

**Rationale**: FR-007 asks for a silent re-pin when the tool caused the identity to change, and a
refusal when it did not. Written as attribution — *did we do this?* — it needs state, and state about
"whose fault was that" is exactly the kind that goes wrong quietly.

Inverting it removes the question. If every deploy re-captures, the pinned entry is **by construction
whatever the tool last saw**. A mismatch at attach therefore means the key changed *without a deploy*,
which is precisely "not by us", and refusing is correct with nothing to attribute. `--purge` +
recreate re-pins because the recreate *is* a deploy.

**This is the load-bearing simplification of the feature**, and the most likely thing for a later
change to re-complicate. SC-003 and SC-004 measure the two directions separately so that
re-complication shows up as a failing test rather than as a subtle regression.

**Rejected**: recording "the tool recreated this" and consulting it at attach (state that can be
stale or lost, answering a question that does not need asking); prompting the operator (a prompt is
what this feature exists to remove, and an unattended agent cannot answer one).

---

## R5 — Capture must wait, and the empty case must be refused

**Decision**: poll for the `.pub` with a bound; on timeout, warn that attach is unverified and leave
the deploy successful.

**Rationale**: the file does not exist when the container reports `Up`. Feature 016 measured that the
runtime publishes `Up` **before the entrypoint executes a line**, with its first write landing
0.27–0.57 s later; host-key generation is later still. A capture that reads immediately gets nothing.

**And "pinned nothing" is indistinguishable from "pinned correctly" by exit code**, which is this
project's recurring defect shape. So an empty or unparseable capture must be an explicit refusal to
write, with a warning — never a written empty entry, and never a silent skip.

FR-008 forbids failing the deploy for this: a container that is running fine should not be torn down
because the tool could not read a file from it. But it also forbids silence, so an unverified attach
must say it is unverified.

**Rejected**: a fixed sleep (the 016 lesson — a sleep is a bet that loses under load, and widening it
widens a race rather than closing one); failing the deploy (disproportionate); pinning whatever was
read without validating it is a public key (the empty-value trap above).

---

## R6 — `StrictHostKeyChecking=yes`, and `accept-new` is the bug being fixed

**Decision**: `attach` runs with `UserKnownHostsFile=<tool file>` and
`StrictHostKeyChecking=yes`.

**Rationale**: `accept-new` silently trusts a host that is not yet pinned — which is today's
behaviour and the thing being replaced. `yes` refuses both an unpinned host and a changed one; since
capture happens at deploy, an unpinned host at attach time is itself a signal worth refusing on.

Note the existing `seed_known_hosts` / `accept-new` code path is for the **provisioned VPS**, a
different endpoint, and is out of scope. Reusing it here would conflate two verifications with
different trust sources.

**Rejected**: `accept-new` (the current defect); `no` (turns off the feature); relying on the
operator's agent/config (unverifiable from here, and FR-006 says the tool owns its own file).

---

## R8 — A pin must PREDATE what it checks, so an absent pin is a question, not a capture

**Decision**: nothing pinned → **warn, state what accepting cannot detect, ask** (FR-013). A
**mismatch** never prompts (FR-014). No terminal → refuse (FR-015).

**Rationale — and this is the argument the whole design rests on.** The obvious move when the pin is
missing is "just fetch the key through the runtime and connect; FR-003 already says the runtime is a
trusted channel." That reasoning is **wrong**, and it is wrong in a way that reads as correct, which is
why it is written down here.

A pin is a **witness**. Its entire value comes from being **older than the event it testifies about**. A
witness created at the moment of the event witnesses nothing. Consider an attacker who destroys the
container and starts their own under the same name:

| | Captured at deploy | Captured at attach |
|---|---|---|
| The pin holds | **our** container's public key, from when we created it | **their** container's public key, fetched just now |
| `ssh` compares it against | their endpoint's key | their endpoint's key |
| Outcome | **mismatch → refused** | **match → connected** |

At deploy time the tool knows the container is the one it just created — the provenance comes from the
*act of deploying*, not from the channel. At attach time the runtime can only answer *"the container
currently called X"*, never *"the container you created"*. So the guarantee evaporates, and
capture-at-use is trust-on-first-use through a different door — with the attacker who replaced the
container owning what is behind that door too.

**So FR-003's "the runtime is a trusted channel" does NOT license capture-at-attach.** It licenses
preferring the runtime over `ssh-keyscan` *at deploy time*, which is a different claim. Conflating the
two is the mistake this entry exists to prevent.

**Which leaves a real usability problem, and it is not solved by weakening verification.** Refusing
outright makes `redeploy` the only re-pin path, and `redeploy` runs `--force-recreate` — it destroys the
container and kills the operator's running agent. A deleted cache file would cost a working session,
against Constitution I's whole point.

The resolution is to stop dressing a trust decision as a verification: **ask**, and say plainly what
accepting does not detect. The operator takes a known risk knowingly; the tool does not pretend. Hence
FR-016's fingerprint — a prompt with nothing to compare against is theatre — and FR-015's refusal where
no answer can be obtained, because an assumed yes is a silent capture with extra steps.

**Rejected**: silent capture-if-absent (the analysis above — it cannot detect a replaced container, and
it *looks* like verification, which is worse than being obviously absent); refuse-always (destroys a
running session over a deletable cache file); prompting on a **mismatch** too (a mismatch contradicts a
claim the tool made itself, and a prompt would let a warning be clicked through — this is the one place
the feature must be unconditional); defaulting to yes when there is no terminal (an unattended
invocation cannot consent).

---

## R7 — Removal is part of the feature, and the stale file must be deleted

**Decision**: remove the `--host-key` flag, its staging, the entrypoint's injected-key branch, and
`INJECT_HOST_KEY_PATH`; delete any `<state>/<host>/<name>.host_key` left by an earlier version and say
so.

**Rationale**: FR-002 and FR-011. The staged file is a plaintext private key at mode 0644 that
`--purge` does not remove, so an upgrade that merely stops *writing* it leaves the exposure in place
on every machine that ever used the flag. Silent deletion is also wrong: an operator should learn that
a private key was removed from their disk.

The mode was defensible where it stood — compose exposes the source file's mode into the container,
and `dev`'s uid need not match the host uid that ran `up`, so 0600 was measured to break — and a
separate measurement here confirmed there is no way out via `mode:` on the config reference: with a
0600 source and `mode: 0400` declared, the file arrived in-container as `-rw------- root root`, i.e.
the source's mode, ignoring the declaration. **So the mode could not have been fixed in place.**
Removing the file is the only clean answer, which is a second reason this feature is the right shape.

**Rejected**: keeping the flag and chmod'ing the staged file (measured impossible — see above);
switching to `configs: {content:}` so the compose file could be 0600 (inlines a secret into the
compose model, against CLAUDE.md's *"inline non-secret injected material"*, and still leaves a secret
on disk); leaving stale files (the exposure persists exactly where it already exists).
