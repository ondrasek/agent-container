# Tasks: Kill Switch (Feature 015)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R7) · [data-model.md](./data-model.md) ·
[contracts/kill-contract.md](./contracts/kill-contract.md) (C1–C15) · [quickstart.md](./quickstart.md) (S1–S12)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: **T014 — the unreachable host — is written before the happy
path.** A kill switch that stops the reachable things and reports success is easy to build and passes
every other test in this file. The one outcome that must be impossible is invisible in a green run,
so it is built first and everything else assembles around it.

**What this feature must NOT reuse, and why** — read before starting:

| Tempting | Why it fails |
|---|---|
| `do_stop` per environment | requires `compose_file_path`, which lives in **derived host state that dies with its host**. The forgotten environments this feature exists for are exactly the ones it refuses (research R1) |
| `<runtime> stop <container-name>` | halts the agent and leaves the **egress sidecar and operator helpers running**, while the report says everything stopped |
| verifying a **stop** against `ps -a` | a stopped container still exists, so every stop would report failed (research R2) |
| `RUNS_PROBE_TIMEOUT` (10s) as the per-host budget | **below** the 20s bound `host_ps_rows` already applies, so it expires before the call it bounds and misreports a healthy host |
| enumerating live and filtering by name prefix | stops containers belonging to no recorded deployment (FR-009 — 014 *reported* those, this feature *acts*). The **project label** of a recorded deployment is the boundary; the naming convention is not |

---

## Phase 1: Setup

- [ ] T001 `KILL_HOST_TIMEOUT = 30.0` in `bin/agent-container`, with a comment stating its **floor**:
      it must stay above the 20s bound `host_ps_rows` applies to its own query, or the budget expires
      before the call it bounds (FR-004a, research R6). Not `RUNS_PROBE_TIMEOUT` — that is 10s and
      inherits the bug
- [ ] T002 [P] `KILL_OUTCOMES = ("stopped", "already-stopped", "failed", "undetermined")` — closed at
      construction, as Feature 014 closes its own set (data-model §3)

---

## Phase 2: Foundational — blocking prerequisites for every story

- [ ] T003 `kill_candidates(scope)` in `bin/agent-container` — the inventory's **`active`** entries
      only, filtered by host and name (FR-002, FR-011, data-model §5). `removed`/`host-gone` are
      already accounted for; re-attempting them manufactures failures
- [ ] T004 The scope resolves from **stored fields alone, contacting no host** (FR-011, clarified).
      Scoping that needed a daemon would depend on the very reachability this feature cannot assume
- [ ] T005 `kill_read_inventory()` — distinguishes **unreadable** (refuse, naming the store) from
      **absent/empty** (succeed, "nothing recorded") (FR-013, C14, research R3). The empty message
      says **nothing recorded, not nothing exists** — the tool cannot make the second claim, and at
      this moment the weaker reading sounds like reassurance
- [ ] T006 [P] Unit tests for T005 both ways: an unreadable store refuses **and does not enumerate
      live**; an absent one exits 0 with wording that does not imply nothing exists
- [ ] T007 `project_containers(host_rec, project, include_stopped)` — enumerate a deployment's
      containers by **`com.docker.compose.project` label**, never via the compose file (research R1,
      measured). This is what reaches an environment whose host state was cleared, and what covers
      sidecars
- [ ] T008 [P] Unit test that T007 builds a label filter and **never** references
      `compose_file_path` — the regression this feature exists to avoid, asserted over the call rather
      than trusted
- [ ] T009a `kill_snapshot(host_rec, form)` — the **pre-snapshot** of what is running on a host,
      taken BEFORE its work (C4, data-model §3). Without it `already-stopped` is underivable: once a
      container is not running, nothing distinguishes *we stopped it* from *it was already stopped*.
      Two host queries per host, not one — the first draft of the plan budgeted one
- [ ] T009 `kill_verify(host_rec, form)` — ONE re-query per host after its work (FR-014, C4, C5).
      **`stop` checks the RUNNING set; `destroy` checks `ps -a`.** Two queries for two forms;
      conflating them breaks one completely (research R2)
- [ ] T010 [P] Unit tests for T009: a stopped-but-existing container verifies as stopped under `stop`
      and would NOT verify under `destroy` — the test that catches the conflation
- [ ] T011 `classify(entry, before, after, form)` returning exactly one `KILL_OUTCOMES` value
      (FR-004, data-model §3, C3). Every entry lands in exactly one; zero unclassified
- [ ] T012 [P] Unit test that `undetermined` is produced for **both** its causes — an unreachable host
      **and** a contended `deployment_lock` (research R5) — and that neither is ever `stopped`

---

## Phase 3: User Story 1 — stop everything, and know what didn't (P1)

**Goal**: one action stops every recorded environment, and the result tells the truth about what it
could not reach.
**Independent test**: S2 — with one host unreachable, the reachable environments stop, the unreachable
one is `undetermined`, and the exit is non-zero.

- [ ] T013 [US1] `do_kill(scope, form, preview)` in `bin/agent-container` — enumerate, act per host,
      verify, classify, report (FR-001, C1)
- [ ] T014 [US1] **THE GATE: the unreachable host** (C3, SC-002, S2). A host that does not answer
      within `KILL_HOST_TIMEOUT` yields `undetermined` for **all** of its environments, and **zero**
      of them may be reported `stopped`. **Write this before the happy path** — a build that reports
      success for a host it never reached passes every other test here
- [ ] T015 [US1] [P] Unit test for T014 asserting the ABSENCE of `stopped` for the unreachable host
      **and** a positive control on a reachable one — asserting only the absence would pass for a
      build that classifies nothing at all (the 014 lesson)
- [ ] T016 [US1] Per-host parallelism with a per-host timeout (C5); **environments sequential within a
      host** so that host's single verification re-query stays meaningful (FR-004a, research R6).
      `concurrent.futures.ThreadPoolExecutor` — stdlib, Constitution VI
- [ ] T017 [US1] One host's failure does not abort the others (FR-003, C2) — each host's task is
      independent, and a timeout or exception yields `undetermined` for its environments only
- [ ] T018 [US1] [P] Unit test T017 by making one host raise: the others still complete. A run that
      aborts on first failure leaves an operator worse off than doing it by hand
- [ ] T019 [US1] `stopped` is written **only** after observation (FR-014, SC-002b). A command exiting
      zero is not evidence and must not reach the classifier as one
- [ ] T020 [US1] Exit status follows the worst outcome: anything not `stopped`/`already-stopped` means
      overall failure (FR-005, SC-003, C6). **`undetermined` counts as failure** — "we do not know" is not
      success, and this is the requirement the feature turns on
- [ ] T021 [US1] [P] Unit test that a single `undetermined` among many `stopped` still fails the run
- [ ] T022 [US1] A contended `deployment_lock` yields `undetermined`, never a `die` and never a silent
      skip (research R5). Dying violates FR-003; skipping reports success for something never touched
- [ ] T023 [US1] [P] Acceptance S2 in `bin/tests/test_acceptance.py` — real containers, one host made
      unreachable: reachable stop, unreachable `undetermined`, non-zero exit
- [ ] T024 [US1] [P] Acceptance S5 — every environment reported `stopped` is **absent from the running
      listing**, and still present in `ps -a` (which is correct for a stop)
- [ ] T025 [US1] [P] Acceptance S1 + S3 (SC-001) — everything stops; one failure does not abort the rest

---

## Phase 4: User Story 2 — choose how far it goes (P1)

**Goal**: stop and destroy are distinct, destruction is never implicit, and either can be previewed.
**Independent test**: S7 — stopping preserves volumes; destroying without confirmation destroys
nothing.

- [ ] T026 [US2] The **stopping** form: halt the project's containers, volumes untouched (FR-006,
      SC-005)
- [ ] T027 [US2] The **destroying** form with **purge reach** — containers and their volumes, and
      **never** locally-built images (FR-006, clarified). An image is a shared build artifact holding
      no credential; deleting it costs a slow rebuild mid-emergency and mitigates nothing
- [ ] T028 [US2] [P] Test that the destroying form leaves images intact — the assertion that keeps
      `destroy` from drifting into `wipe`
- [ ] T029 [US2] `destroy` requires explicit confirmation; **`stop` requires none** (FR-007, C7). The
      asymmetry is deliberate: stopping is recoverable and a prompt is friction on the action whose
      value is speed
- [ ] T030 [US2] [P] Acceptance S7 (SC-005, SC-006) — volumes survive a stop; `destroy` without `-y`
      performs **zero** destructive operations
- [ ] T031 [US2] `--preview` prints exactly what would be affected and **changes nothing** (FR-008,
      SC-007, C9). It **contacts hosts** (clarified) so it reports what is actually RUNNING rather
      than only what is recorded — an operator previews in order to decide. It reuses the same
      pre-snapshot path as T009a, inherits the per-host timeout, and reports an unreachable host as
      *undetermined*
- [ ] T031a [US2] Preview **never hangs and never fails the invocation**: an unreachable host during a
      preview is information, not an error. Preview is a query, so unlike the action (T020) it exits 0
      even with an undetermined host — and says which host it could not reach
- [ ] T032 [US2] [P] Acceptance S8 — capture container and volume state before and after a preview
      and assert they are identical. Contacting a host is a read; SC-007 is unaffected by T031
- [ ] T033 [US2] Write back per data-model §4: a **stop** appends to the entry's `notes`, **retaining
      the 5 most recent** (clarified); a
      **VERIFIED destroy** sets `outcome = removed` through 014's existing `set_inventory_outcome`
      (FR-012, C13). **Do not add a `stopped` outcome** — 014's set is closed and describes existence,
      not runstate, and a test pins it
- [ ] T033a [US2] **An `undetermined` or `failed` destroy writes NOTHING** — the entry stays `active`
      (C13, data-model §4). Recording `removed` for an environment whose host never answered puts a
      lie in the store a later audit and a later kill run both read; 014 refuses to store `unknown`
      for exactly this reason, and this would smuggle the same lie in under an accepted value
- [ ] T033ab [US2] [P] Unit test the `notes` cap: six runs leave five notes, newest kept, and the
      entry does not grow without bound. Feature 014 caps the store by ENTRY COUNT only — nothing
      bounds an entry's size, and this feature writes on every run
- [ ] T033b [US2] [P] Unit test T033a: a destroy against an unreachable host leaves the entry
      `active`. **This is the test that would otherwise be missing** — the happy path passes without
      it, and the bug only shows in a store nobody reads until it matters
- [ ] T034 [US2] [P] Unit test that a stop leaves `outcome` untouched while recording what happened,
      and that a destroy marks `removed` — the pair that proves §4 rather than either half alone
- [ ] T035 [US2] Document **which form suits which emergency** in `docs/orchestration.md` (FR-006a,
      C8): a runaway or looping agent → **stop**; a suspected credential leak → **destroy**, because
      stopping leaves volumes that may hold an operator-interactive login. State plainly that
      revoking a credential at the provider is **outside this tool**

---

## Phase 5: User Story 3 — stop a subset (P2)

**Goal**: scope the action, and say what was excluded.
**Independent test**: S11 — scoping to one host leaves other hosts untouched, and the report names
what it skipped.

- [ ] T036 [US3] `--host` and `--name`, both repeatable, applied to T003's candidates (FR-011)
- [ ] T037 [US3] The report **states what the scope excluded** (FR-011, C12) — a kill switch that
      silently narrowed itself is the same false guarantee as one that fell back to live enumeration
- [ ] T038 [US3] A scope matching nothing **says so** rather than silently doing nothing (C12). When
      the store is ALSO empty, the store's message wins — "nothing recorded" is the more surprising
      condition and the one an operator most needs to hear
- [ ] T039 [US3] [P] Acceptance S11 — one host scoped, others untouched, exclusions named

---

## Phase 6: The honest edges

- [ ] T040 **The compose project label is the ownership boundary** (FR-009, C10, clarified): every
      container in a RECORDED deployment's project is in scope, including one an operator attached by
      hand. A container matching the tool's naming but belonging to **no recorded deployment** is
      never acted on (SC-004) — Feature 014 *reported* those without claiming them, and this feature
      **acts**, so the rule now has teeth
- [ ] T041 [P] Acceptance S9 — create `agent-container-impostor` with a plain `docker run`, kill, and
      assert it is **still running**. The naming convention can be imitated; a match is evidence of a
      name and nothing more
- [ ] T042 Repeatability (FR-010, C11): a second run over already-stopped environments exits 0 —
      (SC-008) **but a still-unreachable host still yields `undetermined` and still fails the run**.
      Repetition never launders an unknown (clarified)
- [ ] T043 [P] Acceptance S10 + the clarified case: a clean repeat succeeds; a repeat with a host
      still unreachable does not. Both halves, or the test asserts the easy one
- [ ] T044 Interruption partway leaves a truthful record and a repeat is safe (FR-016). **The record
      IS the inventory write-back** (data-model §4): each environment's result is written as it is
      classified, not batched at the end, so an interrupted run has recorded exactly what it
      completed and nothing it did not
- [ ] T044a [P] Unit test T044: interrupt after some environments are classified and assert the store
      reflects those and only those. Every other honesty requirement here has a test; this one had
      none
- [ ] T045 [P] Acceptance S4 — with N hosts and one unreachable, elapsed time is **one** timeout, not
      N (SC-002a). Measured, because a sequential implementation passes every other test in this file
- [ ] T046 [P] Acceptance S12 — an unreadable store refuses; an absent one succeeds saying *nothing
      recorded* (SC-009)

---

## Phase 7: Polish & cross-cutting

- [ ] T047 `--json` carries the full result including per-environment outcomes (FR-015, C15), through
      the existing envelope
- [ ] T048 [P] Completions for the new command in both shells, plus the assertion in
      `bin/tests/test_completions.sh` — the completions' command list is pinned to the CLI's by a
      test, so it fails until updated
- [ ] T049 [P] `docs/inventory.md` — the kill switch as the inventory's consumer: 014 remembers and
      reports, 015 acts. State that 014's deliberate refusal to delete anything is what makes this a
      separate, explicit action
- [ ] T050 [P] Reconcile `docs/threat-model.md`'s 015 row against what was built — a single-command
      DoS, and 014's record as a target list. Structural guards in `bin/tests/` parse that file
- [ ] T051 [P] One-line invariant in `CLAUDE.md`; measure against the 2000-token budget and **prune
      before adding**. Report the before/after number
- [ ] T052 Register the command as **`panic`** (settled by clarification; FR-001). Named so a
      habitual typo cannot reach it — `kill` is overloaded and `stop-all` reads oddly with
      `--destroy`. Discoverability is the accepted cost: name it in the help text and in
      `docs/orchestration.md` so someone scanning for "stop" still finds it
- [ ] T053 Run `scripts/quality-gate.sh` **unpiped**, then the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S12 by hand. A selector matching nothing is
      indistinguishable from one whose tests all passed — that happened in this project

---

## Dependencies

```text
Setup (T001–T002)
  └─ Foundational (T003–T012)      ← enumeration, label-stop, verify, classify
       └─ US1 (T013–T025)  P1      ← T014 is the go/no-go gate; write it FIRST
            ├─ US2 (T026–T035) P1  ← needs a working act+verify to have two forms of
            └─ US3 (T036–T039) P2  ← needs candidates to scope
       └─ Edges (T040–T046) after US1
Polish (T047–T053) last            ← T052 (the name) must land before T048 hardens it
```

**US1 is the feature**; US2 and US3 are shape around it. US2 is P1 alongside US1 because confusing
stop with destroy causes unrecoverable data loss, not because it is needed for US1 to work.

## Parallel opportunities

- **Phase 2**: T006, T008, T010, T012 (tests, distinct concerns) alongside their subjects.
- **Phase 3**: T015, T018, T021 in parallel; T023–T025 are independent acceptance tests.
- **Phase 4**: T028, T030, T032, T034 in parallel; T026/T027/T029/T031/T033 all touch
  `bin/agent-container` and serialise.
- **Phase 6/7**: T041, T043, T045, T046, T048–T051 are independent of each other.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** One command that stops everything recorded and tells the
truth about what it could not reach. That is shippable on its own: without US2 it only stops, which is
the safe half, and without US3 it only does everything, which is the case that cannot be done reliably
by hand.

**What "done" looks like here is unusual.** The measure is not that things stopped — that is the easy
half and it will look right immediately. It is that **S2 fails the run**, that **T045 costs one
timeout rather than N**, and that **T041's impostor is still running**. Each of those is invisible in
an otherwise green suite, and each is a way this feature could ship as a false guarantee.
