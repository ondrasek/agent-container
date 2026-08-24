# Phase 0 Research: Public-key collection, auto-injected

Six decisions. The first is the feature — the rest follow from precedent this
project has already set and paid for.

---

## R1 — The union is the feature's central obstacle, and a MANAGED REGION resolves it

**Finding**: the entrypoint assembles `authorized_keys` as a union and **writes the
union back to the persisted file**:

```sh
[[ -f "${AUTHKEYS}" ]] && cat "${AUTHKEYS}" >> "${_akt}"          # persisted
[[ -f "${INJECT_DIR}/authorized_keys" ]] && cat ... >> "${_akt}"  # injected
[[ -n "${SSH_AUTHORIZED_KEYS:-}" ]] && printf ... >> "${_akt}"    # env
awk 'NF && !seen[$0]++' "${_akt}" > "${AUTHKEYS}"
```

So **every key ever injected is retained on the `ssh` volume**. A collection built
on this mechanism could add access and never remove it. US3 — "I lost the iPad" —
would fail while every other scenario passed, and the operator would believe the
removal had worked. FR-006 exists because of this line, not because of a
hypothetical.

**Rejected — replace the file wholesale.** It would revoke correctly and destroy
anything else there: a key an operator added by hand inside the container, or one a
future feature writes. Silent data loss to fix a revocation bug is a bad trade.

**Rejected — leave the union and document that removal needs `--purge`.** `--purge`
destroys the volume, which takes the container's own SSH identity (019) with it.
"To un-authorise a phone, destroy the environment's identity" is not a revocation
story.

**Decision**: a **sentinel-delimited managed region** inside `authorized_keys`:

```
# BEGIN agent-container managed keys — replaced on every boot; edit outside this region
<resolved admit set>
# END agent-container managed keys
```

Everything outside the region is preserved byte-for-byte; the region is **replaced**,
not merged. Adding and removing both work, and a hand-added key survives.

**This is not a new idiom** — the entrypoint already manages `~/.ssh/config` with
`# BEGIN agent-container` sentinels. The difference is deliberate and must be
stated: that block is **write-once** (an agent's own settings must survive),
whereas this one is **rewritten every boot**, because a region that is never
rewritten cannot revoke. Two blocks with the same sentinel style and opposite
update rules is exactly the kind of thing a later reader gets wrong, so both sites
must say which they are.

---

## R2 — The collection is a plain `authorized_keys` file at both config levels

**Decision**: `authorized_keys` in the user config dir and in the project config
dir — Feature 011's contract, same filename at both levels, project winning.

Chosen over a new format (YAML list, JSON) because FR-011 wants it
operator-editable without a tool command, and `authorized_keys` is the format every
operator already knows and every tool already emits. `cat ~/.ssh/id_ed25519.pub >>
~/.config/agent-container/authorized_keys` is the whole registration flow; no
`agent-container keys add` needs to exist for the feature to work.

It also means **no parser**: sshd's own format, read as lines. The project's rule
against regexing structured formats does not bite, because this format *is* lines.

---

## R3 — Project REPLACES user; it does not merge

**Decision**: the winning file wins entirely.

Merging would let a project *widen* the admit set and never *narrow* it, and
narrowing is the point of US2 — a client repository must not inherit an operator's
personal phone. Feature 017's `settings.yaml` resolves per-KEY because its keys are
independent settings; a key collection is **one** value, so the file-level rule
applies. Recorded because the two look similar and the difference is not obvious.

---

## R4 — The injection channel carries a CONTRADICTION that this feature must settle

**Decision**: injected as compose `configs:` — **non-secret**, and with the
**`content:`** form.

Public keys are not secrets. Treating them as secrets would imply protections that
misrepresent what they are, and would put them on the `/run` ephemeral path for no
benefit. The existing code already gets this part right.

**The contradiction.** The `ssh_authorized_keys` config is the exact channel 020's
admit set must travel through, and the codebase makes two incompatible claims about
it:

- `build_compose_model` (Feature 017): a `file:` config "is a read-only BIND of a
  local path, so it cannot reach a daemon that does not share the filesystem — the
  001/003 lesson, **measured**."
- `stage_ssh_injection`: the staged file is "returned for the compose model to
  reference as a config (**transfers over a remote context**; a bind resolves empty
  on a remote host)."

Both describe `configs: {source: ssh_authorized_keys}`. One says `file:` crosses a
remote context; the other says it cannot. They cannot both be true, and the
docstring asserting it works is attached to the code that uses `file:`.

This is the shape of defect this project keeps finding: **a claim that passes while
the thing it names may be broken.** It is not a style question — if `file:` does not
cross, then `--authorized-key` silently admits nobody on a remote host, and the
collection built on the same channel would inherit that exact failure on the host
where a lockout is hardest to recover from.

**Measurement attempts, 2026-08-23 — still UNSETTLED, and now with two ruled-out routes.**

1. *Remote host over `dbg-ctx`* — blocked. The host's SSH key has **changed**, so the context
   refuses to connect. Not worked around: 018's own rule is that a host-key mismatch **refuses,
   never prompts**, and that the tool leaves the operator's `~/.ssh/known_hosts` untouched.
   Clearing that entry to obtain a measurement would perform the failure this project refuses.
2. *Podman over the local Lima VM* — **cannot answer the question**, proven rather than assumed.
   A probe file written to the staging directory was read successfully from inside a container,
   so the VM **shares `$HOME`**. A `file:` config pointing under `$HOME` therefore resolves here
   whether or not it would resolve against a daemon that shares nothing.

That second result is worth more than a failed attempt: **it explains how the contradiction
survived.** On macOS with Lima — the setup this project is developed on — `file:` works. Anyone
testing locally would have seen `--authorized-key` succeed and written a docstring saying so. The
claim is not careless; it is true of the environment it was formed in and untested outside it.

**SETTLED, 2026-08-23 — `file:` does NOT cross.** Measured with the existing Lima VM by staging
the config file OUTSIDE the one shared mount. `~/.lima/docker/lima.yaml` mounts `~` and nothing
else, so `/tmp/...` is invisible to the daemon — a genuinely unshared path without needing a remote
host at all. A compose project with `configs: {ak: {file: /tmp/.../ak.txt}}` against that daemon:

```
Error response from daemon: invalid mount config for type "bind":
bind source path does not exist: /tmp/claude/t001/ak.txt
```

So a `file:` config **is** a bind, resolved **daemon-side**. `build_compose_model`'s docstring was
right; `stage_ssh_injection`'s was wrong and is corrected (T002).

**Two corrections to this document's own earlier reasoning.** (a) It predicted the failure would be
a silent empty arrival — "`--authorized-key` silently admits nobody on a remote host". Wrong: the
daemon **refuses the deploy** with the error above. Loud, not silent, which makes the pre-existing
defect far less dangerous than claimed, though still a defect. (b) The earlier note that Lima "cannot
answer the question" was too pessimistic — it cannot answer it via a path under `$HOME`, but the VM
answers it perfectly well via a path outside the mount. The mount was never the obstacle; assuming
the staging location was fixed was.

**Wider than 020, and left alone deliberately**: Feature 003's `injected_configs` still use `file:`
(`model_configs[cfg_name] = {"file": str(local_file)}`), so any deploy carrying 003-injected
material to a non-sharing daemon fails the same way. Out of scope here, loud rather than silent, and
deserving its own fix rather than a silent fold-in.

**What would actually settle it**: a daemon that does not share the host filesystem — a real remote
Docker/Podman context, or a Lima VM configured without the `$HOME` mount. Until then C20 stays open
and T002's docstring correction stays unmade, because correcting it either way would be asserting
something still unmeasured.

**Consequence for scope**: settling this is **inside** 020, not adjacent to it.
020's admit set flows through this config entry; choosing its form is unavoidable.
So the plan does two things, in order:

1. **Measure it** — deploy with an existing `--authorized-key` over a genuinely
   remote context and observe whether the file arrives non-empty in the container.
   The answer, not either docstring, decides.
2. **Move the entry to `content:`** — the form 017 measured as working. The keys
   are text, non-secret, and small; inlining them is the 001/003 lesson applied.

If the measurement shows `file:` was broken, that is a **pre-existing bug in
`--authorized-key`** that 020 fixes as a consequence, and it must be reported as
such rather than folded silently into a new feature. Whichever way it goes, **one
docstring is wrong and gets corrected** — leaving both in the tree guarantees the
next reader trusts the wrong one.

## R5 — Validation happens on the operator's machine, before any runtime call

**Decision**: every entry is validated with `ssh-keygen -l -f` before deploy;
a malformed entry **refuses the deploy** naming the entry, and a **private** key is
refused with an explicit statement that it is private.

Before any runtime call, because the alternative is a container that starts and
admits nobody — a lockout discovered from the device that cannot fix it. This is
the same placement rule Feature 017 used for the pre-deploy consequences: refuse
while nothing has been created yet.

The private-key check is not paranoia about format. `~/.ssh/id_ed25519` and
`~/.ssh/id_ed25519.pub` differ by four characters, the mistake is one `cat` away,
and it is the only mistake here whose cost is not recoverable by editing a file.

---

## R6 — Declared-empty admits nobody, and says so loudly

**Decision**: an existing but empty collection is a **declaration** that admits
nobody (Constitution VIII); an absent file is **undeclared** and changes nothing.

The empty case is a legitimate instruction and also a lockout, so it is **warned
about at deploy** rather than silently honoured. An operator who meant it loses
nothing by being told; one who did not has been saved from an environment they
cannot enter.

`--authorized-key` remains additive to the resolved collection, and the resulting
set is stated — so neither source appears to have won silently (FR-008).


---

## R7 — The 003 `file:` defect, fixed by DELIVERY (Constitution IX)

`configs: {file:}` was measured (C20) to be a daemon-side bind, so every injected
config failed against a daemon that could not see the operator's filesystem. The
first repair attempted — inline everything — was reverted: it would have written API
keys into the file that describes the deployment. Constitution IX was ratified from
that near-miss.

**What shipped.** Public material (known_hosts, canonical config, the aac spec, the
task) is inlined as `content:` — it is public, and inline is the only form that
crosses. Secret material (provider API keys, declared credential keys) never enters
the model at all: `split_injected` routes it to `deliver_secrets`, which pushes it
into the already-running container through the runtime channel. For a remote host
that channel is carried inside the context's `ssh://` transport, so it is
authenticated and encrypted **without the tool holding any key of its own** — the
container's key pair stays inside the container and only its public half is ever
captured, which is for VERIFYING which container answered, the opposite direction
from authenticating to one.

**The ordering obligation.** The entrypoint consumes credentials at boot, so it now
waits for a delivery sentinel — but only when the CLI says to expect one, so a
deployment declaring no secrets is unaffected. sshd also moved earlier and became
unconditional: it is the primary interaction surface, and a headless run is exactly
when an operator needs to look inside a container they cannot attach to.

**Delivery runs as the container's root and hands each file to `dev` at 0400.**
`/run/agent-container` is the runtime's own root-owned mount point, so `dev` cannot
create a directory beneath it. This grants the AGENT nothing — it is the operator's
existing daemon access acting from outside, and under rootless podman the
container's root is the operator's own uid.

**Verified on BOTH runtimes, for the SSH channel**: the delivery test and the
no-identity refusal both pass under docker and under the podman `lima` connection,
asserting that the key is absent from the compose file and from every file under the
state dir, and present inside the container at 0400 owned by `dev`.

The first podman attempt failed on an unrelated image-build step (a nodesource apt
fetch) and was reported as unverified rather than assumed fine; a retry passed. Worth
noting only because "it failed once" and "it does not work" are different claims, and
the commit that shipped this said the weaker one until the retry settled it.

**Superseded note**: the delivery test passes under docker AND under the
podman `lima` connection, asserting that the key is absent from the compose file and
from every file under the state dir, and present inside the container at 0400 owned
by `dev`.

**Still open, and recorded rather than smoothed over**: under the
rootless-podman-over-Lima acceptance harness, `agent-container logs` returns rc=0 with
**no output at all**, so a container's own log lines cannot be observed there. The
headless-sshd assertion is therefore measured on docker and skipped — with that reason
named — under podman. It is a harness observability gap, not evidence that sshd fails
to start; worth closing because other assertions could silently become unobservable
the same way.

**Also open**: nothing constrains the scheme of a registered runtime context. That no
longer affects secrets (they no longer use that channel at all), but a `tcp://`
context would still carry every other API call in the clear.


---

## R8 — Credentials PERSIST. FR-012's "always ephemeral" was a misreading

**Decided by the operator, against what I argued.** I defended ephemerality by citing
Feature 003's FR-012, and the objection that settles it is operational, not
philosophical: **a container whose credentials die with it cannot survive a restart.**
A host reboot, a daemon restart, or `restart: unless-stopped` brings the container back
with no CLI present to re-deliver — so it would wait for a delivery nobody sends, time
out, and come up broken. Re-delivering on `start` only helps when the CLI is the thing
doing the restarting, which is the minority of restarts that matter.

Two of my supporting arguments were also wrong, and are retracted here so they are not
re-derived:

1. *"Removal becomes `--purge`, which destroys the container's SSH identity."* False. A
   credential on its own volume is removable with `docker volume rm` and never touches
   the `ssh` volume.
2. *"On `/run` the plaintext never reaches disk."* False, and measured false: `/run` is
   not a tmpfs in this image, it is the container's overlay writable layer. The
   property was lifetime, not medium, and I wrote it as though it were both.

**The design, which follows from naming (Principle IV).** One volume per credential:
`agent-container-<name>-cred-<kind>-<slug>`. That gives all three properties at once:

- **Survives** restarts, reboots and daemon failures, because it is a volume.
- **Independently revocable**: `docker volume rm agent-container-acme-cred-apikey-anthropic`
  removes exactly one credential and nothing else.
- **Enumerable by prefix**, which is what keeps the DECLARATION authoritative: on each
  deploy the tool reconciles — a credential no longer declared has its volume removed.
  Without that step persistence reintroduces the union bug this whole feature exists to
  remove (config says gone, container still holds it), so **reconciliation is not
  optional**; it is what makes persistence safe. Same lesson as the managed region:
  replace the set, do not append to it.

**Constitution IX is unaffected.** It governs how a secret TRAVELS — to the running
container, never through its description — not how long it lives once delivered. The
receiver script already owns the layout, so persisting to a volume is a change inside
the receiver, not to the channel.

**Not yet implemented.** What it touches: `per_container_volumes` (the fixed
ten-volume identity contract — credential volumes are dynamic and belong beside it, not
in it), `--purge` and `wipe` (must enumerate the `-cred-` prefix, which is exactly the
"manage lifecycle by naming" the operator proposed), the compose model (declare and
mount the volumes it delivers to), the receiver (write into the mounted volume), the
entrypoint (read from there, and stop waiting for a delivery that already persisted),
and FR-012 itself, which needs restating rather than silently contradicting.
