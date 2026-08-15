# Tasks: Durable Host Inventory (Feature 014)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R10) · [data-model.md](./data-model.md) ·
[contracts/inventory-contract.md](./contracts/inventory-contract.md) (C1–C15) ·
[quickstart.md](./quickstart.md) (S1–S12)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: US1 must prove an entry survives its host's removal (S3)
before reconciliation is built on it. Reconciliation compares a record against reality; if the
record does not outlive the host, there is nothing to compare and every later phase is decoration.

---

## Phase 1: Setup

- [X] T001 `inventory_store_dir()` in `bin/agent-container` resolving
      `$XDG_DATA_HOME/agent-container/inventory/` with the `~/.local/share` fallback — **flat, no
      `<host>/` component** (FR-002, research R2). A per-host directory is deleted with its host, which would
      destroy exactly the entries FR-003 exists to keep
- [X] T002 [P] Add the inventory as a **third tenant row** under the existing durable location in
      `docs/layout.md`, beside `runs/` and `egress/` (FR-002 — which requires it be named there;
      research R1) — not a new location; Feature 016
      already established that one, and FR-012a calls this shared placement
- [X] T003 [P] Note in `docs/layout.md` **why this one is flat** while its two siblings are
      `<host>/<environment>/` — the difference is load-bearing and a future reader will otherwise
      "fix" the inconsistency

---

## Phase 2: Foundational — blocking prerequisites for every story

- [X] T004 `inventory_entry_id()` — generated per deployment, sortable, also the filename
      (FR-015, data-model §1). Host and name are **attributes**, never the key: that is what makes
      FR-015 hold by construction rather than by careful handling
- [X] T005 Entry construction per data-model §1, **refusing any outcome outside the four** and
      refusing `unknown` specifically (FR-004, C4). Enforced at construction, as Feature 016 enforces
      its kind/outcome pairing — a rule kept by convention becomes prose the first time someone adds
      a state, and then SC-003 cannot be measured
- [X] T006 [P] Unit tests for T005: each of the four accepted; `unknown` refused; a
      proof-it-can-fail case that neuters the check and asserts the guard then fails
- [X] T007 Read/write the store using **016's existing** `atomic_write_json` and listing helper — do
      NOT add a second copy (research R3/R4, FR-012a). This is the third consumer after 012's egress
      events; a second implementation is a second thing to drift
- [X] T008 **THE MUTATION CENSUS (research R5) — the highest-risk task in this feature.** Enumerate
      every path that creates or destroys an environment and express the census as a **test over the
      source**, not a comment. Known today: `compose_up_exec` (create), `down_container` and
      `do_wipe` (removed), `host rm [--destroy]` (host-gone). The failure mode is a NEW path added
      later that records nothing — invisible, because everything else it does works correctly
- [X] T009 [P] Prove T008's census guard can fail: add a fake creating path that does not record and
      assert the guard rejects it

---

## Phase 3: User Story 1 — remember everything the tool created (P1)

**Goal**: every environment the tool creates is recorded, and the record survives the container, the
host and the registry entry.
**Independent test**: create across two hosts, remove one host, stop one container, and confirm the
inventory accounts for all of them with an accurate state each.

- [X] T010 [US1] Create an entry in `compose_up_exec` — **not `do_up`** (FR-001, research R5). `do_up` serves
      `up` and `apply`, but `do_redeploy` and the wizard call `compose_up_exec` directly, so a hook in
      `do_up` silently misses them and SC-001's 100% is unreachable
- [X] T011 [US1] Record `host_provisioned` at creation from the host record, so US3 can later
      distinguish a host the tool created from one merely registered
- [X] T012 [US1] Mark `removed` in `down_container` and `do_wipe` (FR-004) — torn down while its host
      remained
- [X] T013 [US1] Mark `host-gone` for a host's `active` entries on `host rm`, **with and without
      `--destroy`** (FR-004). The outcome keys on WHAT disappeared, not who caused it, so
      deprovisioning is not a separate value
- [X] T014 [US1] `inventory list [--json]` (C1, FR-011 — the existing machine-readable interface), newest-first, with a plain line rather than an empty
      screen when there are none
- [X] T015 [P] [US1] Completions for `inventory list` in both shells plus the assertion in
      `bin/tests/test_completions.sh` — the completions' command list is pinned to the CLI's by a
      test, so it will fail until updated
- [X] T016 [US1] A write failure **surfaces without failing the deploy** (FR-008, C10). An
      unrecorded environment is the blind spot this feature exists to remove, so silence here is
      worse than the failed write
- [X] T017 [P] [US1] Unit test T016 both ways: the deploy's exit status is untouched, AND the warning
      is emitted — asserting only the first would pass for a build that records nothing silently
- [X] T018 [US1] **Acceptance S3 — THE GATE.** An entry survives container removal, `host rm`, and
      the host's state directory being gone (C3, FR-003, SC-002). Land this before Phase 4 and stop
      if it fails: the most likely cause is the store being placed under `<state>/<host>/` or scoped
      per host in the durable location
- [X] T019 [US1] Acceptance S2 — `redeploy` also records (C2, SC-001). A hook in the wrong place
      records some deploys and not others, and the gap is invisible
- [X] T020 [P] [US1] Acceptance S4 — create/remove/create with one name yields **two** entries and
      the first is unchanged (C5, SC-003a). **A wrong answer that looks right is `1`**: it means name
      is the key and every recreation is erasing history

---

## Phase 4: User Story 2 — reconcile memory against reality (P1)

**Goal**: compare what the tool remembers against what hosts report, and show the differences.
**Independent test**: create a container outside the tool and delete one it created; confirm both
discrepancies are reported distinctly.

- [X] T021 [US2] `inventory reconcile [--json]` classifying every entry into exactly one of
      `agreeing` / `missing` / `unrecorded` / `unknown` (C6, FR-005, SC-003) — zero unclassified
- [X] T022 [US2] An unreachable host yields **`unknown`, never `missing`** (C7, FR-006, SC-004) —
      Feature 002's fail-closed rule, because invisible is indistinguishable from gone
- [X] T023 [P] [US2] Unit test T022 with a host that cannot be reached, asserting the ABSENCE of any
      `missing` classification — and a positive control with a reachable host, or the test passes for
      a build that classifies nothing at all
- [X] T024 [US2] `unrecorded` for a container present but not in the record, and **the wording must
      not claim ownership** (C8, FR-007, SC-005). `CONTAINER_PREFIX` is a naming convention an
      operator can imitate, so a match is evidence of a name and nothing more
- [X] T025 [P] [US2] Test that neither human nor `--json` output describes an `unrecorded` container
      as the tool's — assert on the words, not only the classification
- [X] T026 [US2] Reconciliation may set `vanished` for a confirmed absence, and **only
      reconciliation may** (data-model §5). It is the one path that has seen a reachable host report
      the container gone; anything else would record an inference as a fact
- [X] T027 [US2] `list` surfaces a **one-line hint** when record and live state disagree, without
      performing or printing the classification (C9, FR-005a). `list` already queries every host, and
      a discrepancy an operator must already suspect is one nobody finds
- [X] T028 [P] [US2] Acceptance S6 — an unreachable host produces zero `missing` classifications
- [X] T029 [P] [US2] Acceptance S7 — a container created outside the tool is reported `unrecorded`
      and never claimed

---

## Phase 5: User Story 3 — what a deployment costs to leave running (P3)

**Goal**: see how long each environment has existed, and whether its host was tool-provisioned.

- [X] T030 [US3] Render age from `created_at` so it is **evident without arithmetic** (SC-009) — a
      timestamp an operator has to subtract from today is not the answer they asked for
- [X] T031 [P] [US3] Show `host_provisioned` so a tool-created host is distinguishable from a merely
      registered one (SC-009), read from the **entry**, not from the live host record
- [X] T032 [P] [US3] Test both renderings for an entry **whose host is gone** (SC-009's trailing
      clause, the one that can actually fail). The host reference is retained (FR-003), so age must
      still answer — and a rendering that reaches for the live host to derive either value breaks
      exactly where this feature is most useful

---

## Phase 6: The honest edges

- [X] T033 Concurrency: N concurrent deployments produce N complete entries (FR-009, C11, SC-007).
      Guaranteed by shape — separate entries are separate files — so the test exists to prove the
      shape was actually used
- [X] T034 The backstop cap (FR-012, C14): **5000 entries, count only**. Age-pruning deletes the
      oldest forgotten entries first, which are the ones this feature exists to surface — so there is
      **no time-based criterion at any level**, and the code must not grow one later as an obvious
      improvement (finding U1)
- [X] T035 [P] Test that the documented cap is the **enforced** one, and that age is NOT a pruning
      criterion — a documented number the code does not use is this project's recurring defect
- [X] T036 **An absent store changes nothing** (FR-013, C13, SC-008). Every read tolerates a missing
      store and no command's exit status depends on the inventory existing
- [X] T037 Verify T036 by **deleting the store and running the existing suite** (research R8) — a
      unit test over an empty store proves the new code tolerates emptiness, not that nothing ELSE
      grew a dependency on it
- [X] T038 [P] Test that the entry's field set is **CLOSED** (FR-010, C12, SC-006). Unlike Feature
      016 there is no free-text field, so the no-credentials guarantee is structural — and that
      closure is the only thing keeping it structural

---

## Phase 7: Polish & cross-cutting

- [X] T039 State FR-014's **THREE-way** authority split in `docs/orchestration.md` (C15): the live
      daemon for *what is running now*; local port state (`<state>/<host>/*.port`) for the **port
      number** and per-host enumeration, dying with its host; this record for *what we ever created*.
      Say that the purposes do not overlap, and that a disagreement between port state and the record
      is **information, not a conflict** — it means a host's state was cleared while the record kept
      its entries, which is FR-003 working. Without this the first disagreement is resolved by whoever
      reads the code that day, and both possible mistakes are bad
- [X] T040 [P] `docs/inventory.md` — what an entry is, the four outcomes, why `unknown` is computed
      rather than stored, retention, and that this feature **deletes nothing** (015's job).
      **Must state that the inventory begins at install and is not backfilled**: an empty inventory
      otherwise reads as "nothing exists" rather than "nothing recorded yet", and pre-install
      environments reconciling as `unrecorded` reads as a bug rather than as the accurate answer it
      is. Say why backfilling was rejected — `*.port` is a census of ports allocated and not
      released, so reconstructed entries would describe gone environments with an undeterminable
      outcome, and a fabricated entry is worse than an absent one in the store a kill switch reads
- [X] T041 [P] **Reconcile `docs/threat-model.md`** — the record names hosts and environments, and
      the Constitution's Development Workflow clause makes this MUST for any feature altering what is
      persisted. Read the existing structure first: structural guards in `bin/tests/` parse that file
- [X] T042 [P] One-line invariant in `CLAUDE.md`; measure against the 2000-token budget and **prune
      before adding**. Report the before/after number
- [X] T043 Run `scripts/quality-gate.sh` **unpiped** plus the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S12 by hand. A `-k` pattern matching nothing is
      indistinguishable from one whose tests all passed

---

## Dependencies

```
Setup (T001–T003)
  └─ Foundational (T004–T009)        ← T008's census guard blocks trusting SC-001 at all
       └─ US1 (T010–T020)  P1        ← T018 is the go/no-go gate
            ├─ US2 (T021–T029) P1    ← needs a record that outlives the host to compare against
            └─ US3 (T030–T032) P3    ← needs entries to read age and provenance from
       └─ Edges (T033–T038) after US1
Polish (T039–T043) last
```

US2 and US3 both depend on US1 and not on each other. US2 is P1 because a record that silently
diverges from reality is worse than none — it is trusted.

## Parallel opportunities

- **Setup**: T002 and T003 together, alongside T001.
- **Foundational**: T006 and T009 alongside their subjects.
- **US1**: T015, T017, T020 once the hooks land.
- **US2**: T023, T025, T028, T029 once T021/T022/T024 exist.
- **US3**: T031 and T032 together.
- **Edges**: T035 and T038 are independent.
- **Polish**: T040, T041, T042 are separate files.

## Implementation strategy

**MVP is US1 alone** — every creation recorded, and the record surviving container, host and
registry. That already answers *"is there a container on a host I removed?"*, which is the question
the feature exists for, with no reconciliation and no cost view.

**T018 is the go/no-go.** If an entry does not survive `host rm`, stop: US2 compares the record
against reality, and a record that dies with its host has nothing to compare. Building
reconciliation first would produce a feature that demos convincingly and forgets precisely the
environments an operator has lost track of.

**T008 is the risk that outlives this feature.** Every later feature that creates an environment must
record one, and the census is what makes that a build failure rather than a silent blind spot.
