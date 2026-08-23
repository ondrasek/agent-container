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
# BEGIN agent-container managed keys (replaced on every boot; edit outside this block)
<resolved admit set>
# END agent-container managed keys
```

Everything outside the block is preserved byte-for-byte; the block is **replaced**,
not merged. Adding and removing both work, and a hand-added key survives.

**This is not a new idiom** — the entrypoint already manages `~/.ssh/config` with
`# BEGIN agent-container` sentinels. The difference is deliberate and must be
stated: that block is **write-once** (an agent's own settings must survive),
whereas this one is **rewritten every boot**, because a block that is never
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
