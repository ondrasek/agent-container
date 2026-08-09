# Tasks: Run Observability (Feature 016)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R10) · [data-model.md](./data-model.md) ·
[contracts/runs-contract.md](./contracts/runs-contract.md) (C1–C15) · [quickstart.md](./quickstart.md) (S1–S12)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: P1 must prove a record survives `down --purge` (S2) before
anything is built on top of it. If it does not survive, the feature has no foundation and every
later phase is decoration.

---

## Phase 1: Setup

- [ ] T001 Create `/var/lib/agent-container/runs` in `image/Dockerfile`, **dev-owned** — a
      runtime-created mount point is `root:root` and rootless cannot write it even under a
      dev-owned parent (CLAUDE.md invariant, research R2)
- [ ] T002 Add `runs_volume_name()` and wire the tenth volume into `per_container_volumes`,
      `other_container_volumes` and the compose model in `bin/agent-container`
- [ ] T003 Update the exact-equality doctests on `per_container_volumes` / `other_container_volumes`
      — they pin nine names and will fail; that failure is the contract noticing, not a nuisance
- [ ] T004 [P] Add the sixth location to `docs/layout.md` (research R1). Feature 011 declares that
      file the one map, so the row belongs there and not in this feature's docs

---

## Phase 2: Foundational — blocking prerequisites for every story

- [ ] T005 `runs_store_dir(host, environment)` resolving `$XDG_DATA_HOME/agent-container/runs/...`
      with the `~/.local/share` fallback, in `bin/agent-container`
- [ ] T006 Atomic write helper: serialise to a temporary name in the target directory, then
      `os.replace`. **Takes a directory as a parameter and knows nothing about run records** — this
      is the machinery FR-011a says Feature 014 adopts (research R3)
- [ ] T007 [P] Directory listing helper with the same neutrality, newest-first
- [ ] T008 Record construction with the schema of data-model §1, **refusing an illegal
      kind/outcome pair at construction** (C5) — a rule kept by convention becomes prose the first
      time a kind is added, and then SC-002 cannot be measured
- [ ] T009 [P] Unit tests for T008: every legal pair accepted; `interactive`+`finished` and
      `interactive`+`failed` refused; a proof-it-can-fail case that neuters the check and asserts
      the guard then fails
- [ ] T010 **THE MIGRATION (research R2, and the T118/T129d lesson).** Detect an environment
      deployed with nine volumes, announce the recreation, and handle it in **both directions** —
      T129d proved the reverse path is the one that gets forgotten. Name, port and all nine existing
      volumes are unchanged, so the identity check passes while the shape differs
- [ ] T011 [P] Test T010 both ways: adopting the tenth volume, and rolling back to nine

---

## Phase 3: User Story 1 — the record exists and survives (P1)

**Goal**: every run leaves a durable record that outlives its container.
**Independent test**: run headlessly, tear down completely, record still retrievable and accurate.

- [ ] T012 [US1] Capture start state in `image/entrypoint.sh` and write the **pending** record to
      the runs volume. Written at START, not only at exit: SIGKILL runs no trap, and the pending
      file is the only reason a killed run is recoverable at all (data-model §7, SC-008)
- [ ] T013 [US1] Exit path in `image/entrypoint.sh`: complete the record, atomically rename.
      **Must not alter the run's own exit status** (FR-008, C11) — the exit path must not become a
      new way for a successful run to report failure
- [ ] T014 [US1] SIGTERM trap → `outcome: stopped`, completing and exiting **within the runtime's
      stop grace period**, or the record is lost to the SIGKILL that follows (research R5)
- [ ] T015 [US1] Ingestion: `docker run --rm -v <runs-volume>:/mnt … tar cf - -C /mnt .` streamed
      to stdout (research R10). Belongs with the `driver_*` argv builders — it needs the **runtime**,
      not the filesystem, because the operator's machine shares no filesystem with a remote host
- [ ] T016 [US1] Drain-on-contact: any command that talks to a host ingests that host's pending
      records first, stamping `host` at ingestion (the container does not reliably know what the
      operator calls its host)
- [ ] T017 [US1] **Teardown drains BEFORE removing volumes** (FR-001b, C4). Ordering is the
      property: a drain after removal is not a late drain, it is no drain
- [ ] T018 [P] [US1] Test T017 by **swapping the order and asserting the test fails** — otherwise
      it passes for a build where the drain does nothing
- [ ] T019 [US1] `never-started` authored by the CLI (C6, research R5) — nothing inside the
      container existed to report, so this is the one record the tool writes directly
- [ ] T020 [US1] `runs list [<environment>] [--json]` (C1), newest-first, with a plain line rather
      than an empty screen when there are none
- [ ] T021 [US1] `runs show <run-id> [--json]` (C2)
- [ ] T022 [P] [US1] Completions for `runs list` / `runs show` in both shells, plus the assertion
      in `test_completions.sh` — the completions' command list is pinned to the CLI's
- [ ] T023 [US1] **Acceptance: S2 — a record survives `down --purge`** (C3, SC-001). This is the
      feature. Land it before Phase 4 and stop if it fails
- [ ] T024 [US1] Acceptance: S3 — a **detached** run is ingested on next contact, with the CLI
      never attached when the run ended (SC-002a). This is the case the whole design is shaped for
- [ ] T025 [US1] Acceptance: S4 — a `docker kill`ed run still yields a record marked `stopped`
      (SC-008). **A wrong answer that looks right is no record at all**: SIGKILL runs no trap, so
      this passes only if T012's start-side write exists

---

## Phase 4: User Story 2 — the record means something (P1)

**Goal**: link a run to what it changed and whether it pushed.
**Independent test**: an agent commits and pushes; the record names the commit and confirms the push.

- [ ] T026 [US2] Capture `HEAD`, branch and upstream position at start and exit in
      `image/entrypoint.sh`; derive `commits` and `pushed` (FR-004a). **No agent involvement** — the
      run that most needs a record is the one where the agent crashed
- [ ] T027 [US2] Populate `repository.state` from the measured cases (research R4): `ok`,
      `no-repository`, `no-upstream`, `detached`, `unreadable`. Each is a **record, not an error** —
      an `ephemeral` workspace with no clone is the common case for a throwaway run
- [ ] T028 [P] [US2] Unit tests per state, asserting the **true exit codes measured in R4**
      (`@{u}` → 128, `symbolic-ref -q` → 1, outside a repo → 128), read **unpiped**
- [ ] T029 [US2] `pushed: null` when there is no upstream — **never `false`** (C8). `false` means
      "committed and did not push", the failure Constitution I exists to prevent; conflating it
      with "could not tell" makes the loudest signal in the feature unreliable
- [ ] T030 [US2] Make commit-without-push **loud** in both human and `--json` output (FR-005, C8)
- [ ] T031 [P] [US2] Acceptance: S5 — a run that commits without pushing is identifiable, and a
      run with no upstream reports `null` rather than `false` (SC-003)
- [ ] T032 [P] [US2] Acceptance: S6 — an `ephemeral` workspace with no clone yields
      `state: no-repository`, not a crash and not a null record

---

## Phase 5: User Story 3 — what it cost (P2)

**Goal**: capture usage where the agent reports it; say *unknown* where it does not.

- [ ] T033 [US3] `usage` per data-model §4: `{"reported": false}` by default, agent's own units and
      the agent's name when reported
- [ ] T034 [US3] Per-agent extraction for the agents that report anything — and **nothing invented
      for those that do not**
- [ ] T035 [P] [US3] Render `unknown` as the word in human output and as `reported: false` in JSON
      — **never `0`** (C9, SC-004). A false zero silently understates every total it enters
- [ ] T036 [US3] Aggregation stating `unknown_components` rather than excluding them (FR-007)
- [ ] T037 [P] [US3] Test that usage is **not normalised across agents** (FR-015, C10) — no
      cross-agent total is offered, and `units` keeps the agent's own keys

---

## Phase 6: The honest edges

- [ ] T038 A record write that fails **surfaces without failing the run** (FR-008, C11) — as a
      `notes` entry when a record exists, as a tool warning when it does not
- [ ] T039 [P] Concurrency: N environments produce N complete, non-interleaved records (FR-009,
      C12). Guaranteed by construction via one-file-per-record (R3), so the test exists to prove
      the construction was actually used
- [ ] T040 Retention: prune by age and count at ingestion, with documented defaults (FR-011, C14)
- [ ] T041 [P] Test that pruning is bounded and that the documented default is the enforced one —
      a documented number the code does not use is the recurring defect of this repo
- [ ] T042 Interactive sessions recorded as a distinct kind with the interactive vocabulary and the
      same repository capture (FR-013); acceptance S8 asserts an ended session is never `finished`

---

## Phase 7: Polish & cross-cutting

- [ ] T043 [P] `docs/observability.md` — what a record is, what it is **not** (C15, FR-014), where
      records live, retention, and the task-text rule
- [ ] T044 **Reconcile `docs/threat-model.md`** for the task-text exposure (research R9,
      Constitution III + the Development Workflow clause). Every other field is tool- or git-derived,
      which is what makes this bounded and statable rather than open-ended
- [ ] T045 [P] State the task-text rule **where a task is given**, not only in docs — the operator
      types the task there, and that is where the warning is read
- [ ] T046 [P] Update `docs/layout.md` cross-references and `CLAUDE.md`'s one-line invariant;
      re-measure CLAUDE.md against its 2000-token budget and **prune before adding**
- [ ] T047 Acceptance: S10 — five concurrent environments each yield exactly one complete record
- [ ] T048 Acceptance: S12 — the task text round-trips verbatim, confirming no accidental redaction
      crept in and that the recorded field is the one documented
- [ ] T049 **Ingestion exercised against a REMOTE context** (research R10). A test that only runs
      locally passes while the remote path — the entire reason the tar-over-stdout mechanism exists
      — is never executed
- [ ] T050 Run `scripts/quality-gate.sh` **unpiped** plus the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S12 by hand. A `-k` pattern matching nothing is
      indistinguishable from one whose tests all passed

---

## Dependencies

```
Setup (T001–T004)
  └─ Foundational (T005–T011)          ← T010 migration blocks any real deployment
       ├─ US1 (T012–T025)  P1          ← T023 is the go/no-go gate
       │    └─ US2 (T026–T032) P1      ← needs a record to attach the repository effect to
       │         └─ US3 (T033–T037) P2 ← needs a record to attach usage to
       └─ Edges (T038–T042) after US1
Polish (T043–T050) last
```

US2 and US3 both depend on US1 because they populate fields of a record that must first exist and
survive. They do **not** depend on each other.

## Parallel opportunities

- **Setup**: T004 alongside T001–T003.
- **Foundational**: T007 with T006; T009 and T011 with their subjects.
- **US1**: T018 and T022 alongside the command work.
- **US2**: T028, T031, T032 once T026/T027 land.
- **US3**: T035 and T037 alongside T033/T034.
- **Polish**: T043, T045, T046 are all independent files.

## Implementation strategy

**MVP is US1 alone** — a record that exists, survives teardown, and is listable. That is a shippable
increment: it answers *"which of last night's runs is which, and how did it end?"* with no
repository link and no cost.

**T023 is the go/no-go.** If a record does not survive `down --purge`, stop — US2 and US3 are
fields on a record that does not persist, and building them first would produce a feature that
demos well and loses its data.
