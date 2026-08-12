# Implementation Plan: Durable Host Inventory

**Branch**: `014-host-inventory` | **Date**: 2026-08-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-host-inventory/`

## Summary

The tool can only see what is currently answering. `list` asks each registered host's daemon and
reconciles against local port state — right for *"what is running now"*, and deliberately
fail-closed. But it has **no memory**, so it cannot answer *"is there a container on a host I
removed from the registry?"* or *"something is billing me — did this tool make it?"*

This gives the tool a durable, operator-machine inventory of everything it created: what, where,
when, and what became of it. **It does not delete anything** — remembering, comparing and reporting
is the whole scope; acting on the result is the kill switch's job (015).

## The decisions this plan settles first

### 1. NOT a seventh location — a sibling inside the sixth

The spec asks for "a **sixth** location in the Feature 011 vocabulary". That was true when it was
written. **Feature 016 got there first**: `docs/layout.md` now carries
`$XDG_DATA_HOME/agent-container/runs/` and `.../egress/` as durable user data.

So the inventory is `$XDG_DATA_HOME/agent-container/inventory/` — a **third sibling in the existing
sixth location**, not a new one. That *is* the "shared placement" FR-012a anticipated, and saying so
keeps `docs/layout.md` from growing a row it does not need.

**But NOT scoped per host.** `runs/` and `egress/` are `<host>/<environment>/`. FR-003 requires the
inventory to survive the host's removal, and a per-host directory dies with its host — the very
entries FR-003 exists to keep. So the inventory is **flat**: `inventory/<entry-id>.json`, with host
as an *attribute*. The two shapes differ because their lifetimes differ.

### 2. Shared write path, emphatically NOT shared retention

016 built `atomic_write_json` and the listing helper deliberately neutral — they take a directory and
know nothing about the record kind. 012's egress events already adopted them, so this is a third
consumer of a proven path, not a bet.

**Retention is where the two must not touch.** 016 prunes by age and count (90 days / 500), because
a run's value decays once its commits are ordinary history. The inventory is the **opposite**: its
value *is* the entry you forgot six months ago, so FR-012 forbids age-based pruning as a default and
asks only for a large backstop cap.

**The cap is 5000 entries, count only, with no time dimension at all.** Named here rather than left
as "a large cap", because FR-012 requires the bound to exist and T035 checks that the *documented*
number is the *enforced* one — which is unanswerable while no number is written down. 5000 is roughly
an order of magnitude past the spec's own estimate that years of heavy use is hundreds of rows, which
is what makes it a backstop rather than tidying. **No age criterion exists at any level**: the
entries most worth having are the oldest forgotten ones, so a time dimension would delete the
feature's whole value first.

Sharing a retention policy would give one of them the wrong one —
which is exactly the reason FR-012a forbids a shared store while permitting shared machinery.

### 3. Entries are MUTATED; run records are not

A run record is written once and never changes. An inventory entry changes outcome over its life:
`active` → `removed` / `vanished` / `host-gone`. One-file-per-entry still holds, because an atomic
rewrite of the same filename is the same primitive as an atomic create — and FR-009's concurrency
guarantee still falls out of it, since two invocations touching *different* entries touch different
files, and two touching the same entry serialise on the rename.

### 4. Recording hooks where 016 already proved the choke point is

**`compose_up_exec`, not `do_up`.** 016 recorded its reason and it applies unchanged: `do_up` serves
`up` and `apply`, but `do_redeploy` and the wizard call `compose_up_exec` directly, so a hook in
`do_up` leaves those paths unrecorded. SC-001 demands **100%**, and a record that begins late has a
permanent blind spot — the spec says so in US1's own priority note.

The removal side is `down_container` and `do_wipe`; the host side is host removal and
deprovisioning. **Enumerating those exhaustively is the single biggest risk in this feature**, and it
is why the first task is a census of mutation points with a test that fails if a new one appears
unhooked.

### 5. `unknown` is computed, never stored

FR-004's stored set is exactly four values; `unknown` is a *reconciliation result*. Enforced where
the entry is constructed, as 016 enforces its kind/outcome pairing — a rule kept by convention
becomes prose the first time someone adds a state, and then SC-003's "zero entries carrying
`unknown`" cannot be measured.

### 6. Absent record degrades; it never fails

FR-013 and SC-008 (this feature's) require every existing command to behave **exactly as before**
when the store is missing. So every read is tolerant and no command's exit status depends on the
inventory existing. This is the one requirement that can only be verified by *deleting* the store
and re-running the suite.

## Technical Context

**Language/Version**: unchanged — Python ≥ 3.14 single-file CLI.

**New dependencies**: **none** (Constitution VI). Reuses 016's stdlib write path.

**Storage**: `$XDG_DATA_HOME/agent-container/inventory/<entry-id>.json`, flat, one file per
deployment.

**Testing**: hermetic pytest for entry construction, the closed outcome set, id generation,
reconciliation classification and the absent-store degradation; acceptance for what only real hosts
show — an entry surviving host removal, an unreachable host yielding `unknown` rather than `missing`,
and a container created outside the tool never being claimed.

**Constraints**:

- **100% of creations recorded** (SC-001) — the census in decision 4.
- **A write failure must not fail the deploy** (FR-008), but must be surfaced.
- **An unreachable host is never `missing`** (FR-006, SC-004) — Feature 002's fail-closed rule.
- **Never claim a container we did not create** (FR-007, SC-005).

## Constitution Check

| Principle | Verdict |
|---|---|
| **I. Ephemerality** | **PASS, and it sharpens the principle.** The container is disposable; the *record* of it is not. The spec's own framing |
| **II. Least Privilege, Immutable Runtime** | **PASS** — no new capability, nothing in the image; this is entirely operator-side |
| **III. Least Exposure** | **PASS** — FR-010. Every field is tool-generated (id, name, host, timestamps, outcome); unlike 016 there is **no free-text field at all**, so the bound is structural rather than stated |
| **IV. Deterministic Identity** | **PASS, and untouched.** No new volume, no port, no container-name change. The inventory observes identity; it does not participate in it |
| **V. Durable Spec** | **PASS** — clarified in two sessions |
| **VI. Least Dependencies** | **PASS** — no new dependency; third consumer of 016's write path |
| **VII. Continuous Deployment** | **PASS** — `feat`, minor pre-1.0 |

## Project Structure

```text
bin/agent-container       entry construction, the mutation hooks, reconciliation, `inventory` cmd
docs/layout.md            the inventory as a THIRD sibling of runs/ and egress/ (decision 1)
docs/orchestration.md     FR-014's authority split: live state for "what runs", record for
                          "what we created"
docs/threat-model.md      reconcile — the record names hosts and environments (Constitution)
bin/tests/                hermetic construction/classification; acceptance for survival + fail-closed
```

## Design decisions carried into tasks

1. **A generated id per deployment** (FR-015). Name and host are attributes, so a reused name yields
   *another* entry and FR-015 holds by construction — there is no overwrite path to get wrong.
2. **Four stored outcomes, closed at construction** (FR-004).
3. **Reconciliation is an explicit command** (FR-005) plus a one-line hint in `list` (FR-005a) —
   because a discrepancy an operator must already suspect in order to look for is one nobody finds.
4. **Unreachable ≠ gone** (FR-006). Unreachable is the computed `unknown`; gone is the stored
   `host-gone`. Conflating them makes reconciliation lie.
5. **`unrecorded` is not a claim** (FR-007). Reporting a container we did not create is the
   opposite of claiming it, and the wording must not drift into ownership.
6. **Live state is authoritative for the present; the record for what we created** (FR-014), stated
   in `docs/orchestration.md` rather than left to be inferred.

## Phasing

**P1 — the record exists and survives.** US1. The mutation-point census, entry construction, the
hooks, `inventory list --json`. **Prove an entry survives host removal before building
reconciliation on it**; if it does not, the feature has no foundation.

**P2 — the record stays honest.** US2. Reconciliation, the four classifications, the fail-closed
`unknown`, and the `list` hint.

**P3 — age and provenance.** US3. How long an environment has existed, and whether its host was
tool-provisioned.

**P4 — the honest edges.** Write failures surfaced without failing the deploy, concurrency, the
backstop cap, absent-store degradation, and the threat-model reconciliation.

## Complexity Tracking

| Deviation | Why needed | Rejected alternative |
|---|---|---|
| A flat store, unlike `runs/<host>/<env>/` | FR-003: the entry must outlive its host, and a per-host directory dies with the host | mirroring 016's layout — it would delete exactly the entries this feature exists to keep |
| Entries mutated in place | outcome changes over an entry's life | append-only event log — reconstructing current outcome on every read, for a store whose whole point is being cheap to consult |
| Retention deliberately unlike 016's | the valuable entries are the oldest; age-pruning deletes those first | reusing 016's age+count policy — it would silently delete the forgotten environment this feature exists to surface |
