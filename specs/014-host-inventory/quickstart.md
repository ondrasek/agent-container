# Quickstart: Durable Host Inventory (Feature 014)

Runnable validation. Each step names what it proves and **what a wrong answer looks like**, because
several of these fail in ways that resemble success.

**Prerequisites**: a working `agent-container` install, a container runtime, and at least one host
you are willing to remove from the registry.

---

## S1 — A deployment is recorded

```bash
agent-container up demo
agent-container inventory list
```

**Expected**: one entry — name, host, creation time, `outcome: active`. (C1, FR-001)

---

## S2 — Every deploy path records, not just `up`

```bash
agent-container redeploy demo          # goes through compose_up_exec, NOT do_up
agent-container inventory list --json | jq '.entries | length'
```

**Expected**: a second entry. (C2, SC-001)

**Why this step exists**: `do_up` serves `up` and `apply`, but `redeploy` and the wizard call
`compose_up_exec` directly. A hook in the wrong place records some deploys and not others, and the
gap is invisible — everything appears to work.

---

## S3 — The entry outlives the container, the registration and the host

```bash
agent-container down demo --purge -y
agent-container host rm <host> -y
agent-container inventory list
```

**Expected**: the entries are **still there**, marked `removed` / `host-gone`. (C3, FR-003, SC-002)

This is the feature. If they are gone, stop here — most likely the store was placed under
`<state>/<host>/`, which is deleted with the host, or scoped per host in the durable location.

---

## S4 — A reused name does not overwrite history

```bash
agent-container up demo && agent-container down demo -y
agent-container up demo
agent-container inventory list --json | jq '[.entries[] | select(.name=="demo")] | length'
```

**Expected**: `2`, with the first entry's `outcome` and timestamps unchanged. (C5, SC-003a)

**A wrong answer that looks right**: `1`. It means name is being used as the key, and every
recreation is silently erasing the history of the previous one — the exact thing FR-015 makes
impossible by construction.

---

## S5 — Reconciliation is explicit and classifies everything

```bash
agent-container inventory reconcile
agent-container inventory reconcile --json | jq -r '.results[] | "\(.entry_id) \(.classification)"'
```

**Expected**: every entry is exactly one of `agreeing` / `missing` / `unrecorded` / `unknown` —
none unclassified. (C6, FR-005, SC-003)

---

## S6 — An unreachable host is `unknown`, never `missing`

```bash
# point a registered host at an unreachable endpoint, or stop its daemon
agent-container inventory reconcile --json | jq -r '.results[] | select(.classification=="missing") | .entry_id'
```

**Expected**: **nothing** for entries on the unreachable host; they classify `unknown`. (C7,
FR-006, SC-004)

**A wrong answer that looks right**: `missing`. It reads as a clean finding and is a lie — invisible
is indistinguishable from gone, which is why Feature 002 made enumeration fail-closed.

---

## S7 — A container the tool did not create is never claimed

```bash
docker run -d --name agent-container-notmine alpine sleep 600
agent-container inventory reconcile --json | jq -r '.results[] | select(.classification=="unrecorded")'
docker rm -f agent-container-notmine
```

**Expected**: reported as `unrecorded`. (C8, FR-007, SC-005)

**Check the wording, not just the class**: neither rendering may describe it as the tool's. The
prefix is a naming convention anyone can imitate, so a match is evidence of a *name* and nothing
more.

---

## S8 — `list` hints without lecturing

```bash
docker rm -f agent-container-demo     # remove one behind the tool's back
agent-container list
```

**Expected**: the usual output plus **one brief line** noting record and reality disagree — and
**not** the full classification. (C9, FR-005a)

---

## S9 — A store that is absent changes nothing

```bash
mv ~/.local/share/agent-container/inventory /tmp/inv-away
agent-container list; echo "list=$?"
agent-container up demo2; echo "up=$?"
mv /tmp/inv-away ~/.local/share/agent-container/inventory
```

**Expected**: both succeed, output identical to before the feature existed. (C13, FR-013, SC-008)

**The real test of this is deleting the store and running the whole existing suite** — a unit test
over an empty store proves the new code tolerates emptiness, not that nothing *else* grew a
dependency on it.

---

## S10 — A record write failure does not fail the deploy

```bash
chmod a-w ~/.local/share/agent-container/inventory
agent-container up demo3; echo "up=$?"
chmod u+w ~/.local/share/agent-container/inventory
```

**Expected**: `up=0`, plus a warning that the entry could not be recorded. (C10, FR-008)

**A wrong answer that looks right**: a silent success. An unrecorded environment is precisely the
blind spot this feature exists to remove, so silence here is worse than the failed write.

---

## S11 — Concurrency loses nothing

```bash
for n in i1 i2 i3 i4 i5; do agent-container up "$n" & done; wait
agent-container inventory list --json | jq '[.entries[] | select(.name | startswith("i"))] | length'
```

**Expected**: `5`, all complete. (C11, SC-007)

---

## S12 — No field can carry a credential

```bash
agent-container inventory list --json | jq -r '.entries[0] | keys[]'
```

**Expected**: only the tool-generated fields of data-model §1. (C12, FR-010, SC-006)

Unlike Feature 016 there is **no free-text field**, so this guarantee is structural rather than
stated — and it stays structural only while the field set stays closed.
