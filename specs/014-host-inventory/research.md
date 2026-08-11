# Research: Durable Host Inventory (Feature 014)

Phase 0. Each entry records a **decision**, its **rationale**, and what was **rejected** — and where
a fact is claimed, how it was established.

---

## R1 — The location already exists; the inventory is a sibling, not a seventh row

**Decision**: `$XDG_DATA_HOME/agent-container/inventory/<entry-id>.json`.

**Rationale**: the spec asks for "a **sixth** location in the Feature 011 vocabulary", and that was
true when it was written. **Feature 016 got there first.** `docs/layout.md` already carries, verified:

```
| Run records   | $XDG_DATA_HOME/agent-container/runs/<host>/<environment>/   | durable
| Egress events | $XDG_DATA_HOME/agent-container/egress/<host>/<environment>/ | durable
```

So the durable-user-data location exists and has two tenants. The inventory is a **third sibling**
inside it — which is precisely the "shared placement" FR-012a permits and expects — and
`docs/layout.md` gains a tenant row rather than a location.

**Rejected**: a seventh location (there is nothing to distinguish it from the sixth); anywhere under
`~/.config` (configuration is what the operator writes; this is what the tool observes); the state
dir (documented "computed; safe to delete", and R2 below is fatal to it anyway).

---

## R2 — Flat, NOT per host — and this is the one place 016's shape must not be copied

**Decision**: `inventory/<entry-id>.json`, with `host` as an attribute of the entry.

**Rationale**: `runs/` and `egress/` are scoped `<host>/<environment>/`, and copying that would be
the natural thing to do. It is **fatal here**. FR-003 requires an entry to survive *the host's
removal from the registry and the host's deprovisioning*, and a per-host directory is deleted with
its host — destroying exactly the entries FR-003 exists to keep, and with them the answer to the
spec's sharpest question: *"something is billing me — did this tool create it?"*

The two layouts differ because the two lifetimes differ. A run record is meaningful only in the
context of the host and environment that produced it; an inventory entry is meaningful **precisely
when** that context is gone.

**Rejected**: `inventory/<host>/…` (fails FR-003 by construction); a single `inventory.json` (see R3).

---

## R3 — One file per entry, MUTATED in place by atomic rewrite

**Decision**: one JSON file per entry, rewritten atomically when its outcome changes.

**Rationale**: 016's records are written once and never change; an inventory entry changes outcome
over its life (`active` → `removed` / `vanished` / `host-gone`). That difference does **not** call for
a different mechanism: an atomic rewrite of the same filename is the same primitive as an atomic
create, and 016's `atomic_write_json` already performs exactly that (temp file in the target
directory, then `os.replace`).

FR-009's concurrency guarantee still falls out of the shape rather than out of a lock: two
invocations touching *different* entries touch different files, and two touching the *same* entry
serialise on the rename, with the loser's write simply superseded rather than interleaved.

**Rejected**: a single `inventory.json` mutated in place (every write contends with every other,
and a torn write loses the whole inventory rather than one entry — the blast radius argument);
an append-only event log (correct but it makes every read reconstruct current outcome, for a store
whose value is being cheap to consult); SQLite (a dependency, Constitution VI).

---

## R4 — Shared write path, deliberately UNSHARED retention

**Decision**: reuse `atomic_write_json` and the directory-listing helper. Do **not** reuse 016's
retention.

**Rationale**: this is the third consumer of those helpers — 012's egress events were the second —
so reuse is proven rather than hoped for, and FR-012a explicitly permits "shared placement and
shared write-safety machinery".

Retention is the opposite. 016 prunes by **age and count** (90 days / 500) because a run's value
decays once its commits are ordinary history. FR-012 says the inventory keeps everything
**indefinitely**, and forbids age-based pruning as a default in as many words: *"the entries most
worth having are the oldest forgotten ones, which it deletes first."* The bound is a large backstop
cap for pathological cases, not tidying.

**This is the concrete reason FR-012a forbids a shared store.** One store means one retention rule,
and either the valuable old inventory entries are pruned or the run log grows without bound. The
machinery is shared; the policy must not be, and the policy must not live in the shared helper.

---

## R5 — The hook point is `compose_up_exec`, and the mutation census is the real risk

**Decision**: create entries in `compose_up_exec`; mutate on the teardown paths; enumerate them by
census with a test that fails when a new one appears unhooked.

**Rationale**: SC-001 requires **100%** of created environments recorded, and US1 states why the
bar is absolute — *"a record that begins late has a permanent blind spot."*

016 already chose this choke point and recorded the reason, which applies unchanged: `do_up` serves
`up` and `apply`, but **`do_redeploy` and the wizard call `compose_up_exec` directly**, so a hook in
`do_up` leaves those unrecorded.

The mutation points found by reading the CLI:

| Path | Effect on an entry |
|---|---|
| `compose_up_exec` | create (`active`) |
| `down_container` | `removed` |
| `do_wipe` | `removed` |
| `host rm` | `host-gone` for that host's entries |
| `host rm --destroy` | `host-gone` (deprovisioned — same outcome; FR-004 keys on *what* disappeared, not who caused it) |

**A census is not a substitute for a guard.** The list above is correct today and will rot: the
failure mode is a *new* path added later that creates an environment and records nothing, which is
invisible because everything it does works. So the census must be expressed as a test over the
source — every function that reaches `compose_up_exec`'s siblings must be accounted for — not as a
comment.

**Rejected**: recording in `do_up` (misses redeploy and the wizard, measured by reading the call
graph); recording in the entrypoint (this is operator-machine state and the container has no access
to it — and unlike 016's records, nothing here needs to survive the CLI being absent).

---

## R6 — `unknown` is computed and unrepresentable as stored state

**Decision**: the stored set is exactly `active` · `removed` · `vanished` · `host-gone`, enforced
where an entry is constructed. `unknown` exists only as a reconciliation result.

**Rationale**: FR-004 says so explicitly and SC-003 measures "**zero** entries carrying `unknown` as
a stored outcome". 016 enforces its kind/outcome pairing at construction for the same reason: a rule
kept by convention becomes prose the first time someone adds a state, and then the criterion cannot
be measured.

The temptation this closes is real — a reconciliation that cannot reach a host has an obvious place
to write `unknown`, and doing so would make the record permanently lie about a host that comes back.

---

## R7 — Unreachable is not gone, and `unrecorded` is not a claim

**Decision**: an unreachable host yields the computed `unknown`; a departed host yields the stored
`host-gone`. A container present but not in the record is reported `unrecorded`.

**Rationale**: FR-006 and SC-004 forbid *missing* for an unreachable host — Feature 002's
fail-closed rule, which exists because "invisible is indistinguishable from gone". Conflating them
makes reconciliation lie in the direction that loses things.

FR-007/SC-005 forbid claiming a container the tool did not create. `unrecorded` is the honest
report, and **the wording matters**: it names an observation, not ownership. The tool recognises its
own containers by `CONTAINER_PREFIX` (`agent-container-`, verified), and that prefix is a *naming
convention an operator could imitate* — so a prefix match is evidence of nothing more than a name.
Reporting it as `unrecorded` is exactly right; upgrading that to "ours" would be the false claim
SC-005 counts.

---

## R8 — The absent store must be invisible, and only deletion proves it

**Decision**: every read tolerates a missing store; no command's exit status depends on the
inventory existing.

**Rationale**: FR-013 and SC-008 require every existing command to behave **exactly as before** with
the record absent — zero regressions. That is a claim about the *whole* CLI, not about the new code,
and the only way to test it is to **delete the store and run the existing suite**. A unit test that
constructs an empty store proves something weaker: that the new code tolerates emptiness, not that
nothing else grew a dependency on it.

**Rejected**: creating the store lazily on first read (it would make the "absent" case
unreachable in tests, and a store that appears merely because something read it is a side effect on
a read path).

---

## R9 — FR-014's authority split, stated rather than inferred

**Decision**: **live state is authoritative for "what is running"; the record is authoritative for
"what we created".** Documented in `docs/orchestration.md`.

**Rationale**: FR-014 requires the division be defined. Without it, the first disagreement gets
resolved by whoever is reading the code that day, and both possible mistakes are bad: trusting the
record about the present resurrects containers that are gone, and trusting live state about the past
is the amnesia this feature removes.

The spec's own Assumptions already contain the answer — *"a memory aid, not a source of truth about
the present"* — so this is a promotion from assumption to documented contract, not a new decision.

---

## R10 — There is no free-text field, and that is what bounds Constitution III

**Decision**: every field is tool-generated — id, name, host, timestamps, outcome, provisioned flag.
No operator-authored text is stored.

**Rationale**: FR-010/SC-006 forbid any credential in the record. 016 had to *state* its exposure
because FR-002 there required the task text, which an operator writes and which can carry a secret.
**This feature has no equivalent field**, so the bound is structural rather than stated: there is
nowhere for a credential to arrive.

That is worth asserting with a test rather than trusting, in the same shape as 016's closed-field-set
check: the guarantee holds only while the field set stays closed, and a future field carrying an
environment description or a note would quietly reopen it.
