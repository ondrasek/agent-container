# Tasks: Run Observability (Feature 016)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R11) · [data-model.md](./data-model.md) ·
[contracts/runs-contract.md](./contracts/runs-contract.md) (C1–C16) · [quickstart.md](./quickstart.md) (S1–S13)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: P1 must prove a record survives `down --purge` (S2) before
anything is built on top of it. If it does not survive, the feature has no foundation and every
later phase is decoration.

---

## Phase 1: Setup

- [x] T001 Create `/var/lib/agent-container/runs` in `image/Dockerfile`, **dev-owned** — a
      runtime-created mount point is `root:root` and rootless cannot write it even under a
      dev-owned parent (CLAUDE.md invariant, research R2)
- [x] T002 Add `runs_volume_name()` and wire the tenth volume into `per_container_volumes`,
      `other_container_volumes` and the compose model in `bin/agent-container`
- [x] T003 Update the exact-equality doctests on `per_container_volumes` / `other_container_volumes`
      — they pin nine names and will fail; that failure is the contract noticing, not a nuisance
- [x] T004 [P] Add the sixth location to `docs/layout.md` (research R1). Feature 011 declares that
      file the one map, so the row belongs there and not in this feature's docs

---

## Phase 2: Foundational — blocking prerequisites for every story

- [x] T005 `runs_store_dir(host, environment)` resolving `$XDG_DATA_HOME/agent-container/runs/...`
      with the `~/.local/share` fallback, in `bin/agent-container`
- [x] T006 Atomic write helper: serialise to a temporary name in the target directory, then
      `os.replace`. **Takes a directory as a parameter and knows nothing about run records** — this
      is the machinery FR-011a says Feature 014 adopts (research R3)
- [x] T007 [P] Directory listing helper with the same neutrality, newest-first
- [x] T008 Record construction with the schema of data-model §1, **refusing an illegal
      kind/outcome pair at construction** (C5) — a rule kept by convention becomes prose the first
      time a kind is added, and then SC-002 cannot be measured
- [x] T009 [P] Unit tests for T008: every legal pair accepted; `interactive`+`finished` and
      `interactive`+`failed` refused; a proof-it-can-fail case that neuters the check and asserts
      the guard then fails
- [x] T010 **THE MIGRATION (research R2, and the T118/T129d lesson).** Detect an environment
      deployed with nine volumes, announce the recreation, and handle it in **both directions** —
      T129d proved the reverse path is the one that gets forgotten. Name, port and all nine existing
      volumes are unchanged, so the identity check passes while the shape differs
- [x] T011 [P] Test T010 both ways: adopting the tenth volume, and rolling back to nine

---

## Phase 3: User Story 1 — the record exists and survives (P1)

**Goal**: every run leaves a durable record that outlives its container.
**Independent test**: run headlessly, tear down completely, record still retrievable and accurate.

- [x] T012 [US1] Capture start state in `image/entrypoint.sh` and write the **pending** record to
      the runs volume. Written at START, not only at exit: SIGKILL runs no trap, and the pending
      file is the only reason a killed run is recoverable at all (data-model §7, SC-008)
- [x] T013 [US1] Exit path in `image/entrypoint.sh`: complete the record, atomically rename.
      **Must not alter the run's own exit status** (FR-008, C11) — the exit path must not become a
      new way for a successful run to report failure
- [x] T014 [US1] SIGTERM trap → `outcome: stopped`, completing and exiting **within the runtime's
      stop grace period**, or the record is lost to the SIGKILL that follows (research R5)
- [x] T015 [US1] Ingestion: `docker run --rm -v <runs-volume>:/mnt … tar cf - -C /mnt .` streamed
      to stdout (research R10). Belongs with the `driver_*` argv builders — it needs the **runtime**,
      not the filesystem, because the operator's machine shares no filesystem with a remote host
- [x] T016 [US1] Drain-on-contact: any command that talks to a host ingests that host's pending
      records first, stamping `host` at ingestion (the container does not reliably know what the
      operator calls its host)
- [x] T017 [US1] **Teardown drains BEFORE removing volumes** (FR-001b, C4). Ordering is the
      property: a drain after removal is not a late drain, it is no drain
- [x] T018 [P] [US1] Test T017 by **swapping the order and asserting the test fails** — otherwise
      it passes for a build where the drain does nothing
- [x] T019 [US1] `never-started` authored by the CLI (C6, research R5) — nothing inside the
      container existed to report, so this is the one record the tool writes directly
- [x] T020 [US1] `runs list [<environment>] [--json]` (C1), newest-first, with a plain line rather
      than an empty screen when there are none
- [x] T021 [US1] `runs show <run-id> [--json]` (C2)
- [x] T022 [P] [US1] Completions for `runs list` / `runs show` in both shells, plus the assertion
      in `test_completions.sh` — the completions' command list is pinned to the CLI's
- [x] T023 [US1] **Acceptance: S2 — a record survives `down --purge`** (C3, SC-001). This is the
      feature. Land it before Phase 4 and stop if it fails
- [x] T024 [US1] Acceptance: S3 — a **detached** run is ingested on next contact, with the CLI
      never attached when the run ended (SC-002a). This is the case the whole design is shaped for
- [X] T025 [US1] Acceptance: S4 — a `docker kill`ed run still yields a record marked `stopped`
      (SC-008). **A wrong answer that looks right is no record at all**: SIGKILL runs no trap, so
      this passes only if T012's start-side write exists.
      This is one of the two tests that failed on Linux CI and passed on macOS. Two causes, both
      fixed: the entrypoint opened the record after the shell-env seed, host-key generation and git
      identity (now section `1r`, first), and the test killed on the runtime's `Up` status, which is
      published BEFORE the entrypoint executes a line — 0/8 records on native Linux. The precondition
      is now `_wait_run_started`, which waits for the workload process to exist. It reads
      `/proc/<pid>/cmdline` INSIDE the container via `<runtime> exec`, not `<runtime> top`: `docker
      top` runs `ps -ef` on the daemon host so its CMD column carries arguments, while `podman top`'s
      default COMMAND column is `comm` alone — the needle `sleep 600` could never match there, and
      ADR 0001 decided on podman. The two runtimes do not even take the same kind of argument for
      that column, so /proc is the only answer that means the same thing to both

---

## Phase 4: User Story 2 — the record means something (P1)

**Goal**: link a run to what it changed and whether it pushed.
**Independent test**: an agent commits and pushes; the record names the commit and confirms the push.

- [x] T026 [US2] Capture `HEAD`, branch and upstream position at start and exit in
      `image/entrypoint.sh`; derive `commits` and `pushed` (FR-004a). **No agent involvement** — the
      run that most needs a record is the one where the agent crashed
- [x] T027 [US2] Populate `repository.state` from the measured cases (research R4): `ok`,
      `no-repository`, `no-upstream`, `detached`, `unreadable`. Each is a **record, not an error** —
      an `ephemeral` workspace with no clone is the common case for a throwaway run
- [x] T028 [P] [US2] Unit tests per state, asserting the **true exit codes measured in R4**
      (`@{u}` → 128, `symbolic-ref -q` → 1, outside a repo → 128), read **unpiped**
- [x] T029 [US2] `pushed: null` when there is no upstream — **never `false`** (C8). `false` means
      "committed and did not push", the failure Constitution I exists to prevent; conflating it
      with "could not tell" makes the loudest signal in the feature unreliable
- [x] T030 [US2] Make commit-without-push **loud** in both human and `--json` output (FR-005, C8)
- [X] T031 [P] [US2] Acceptance: S5 — a run that commits without pushing is identifiable, and a
      run with no upstream reports `null` rather than `false` (SC-003).
      **GAP CLOSED.** `test_committing_without_pushing_is_LOUD_and_no_upstream_is_NOT`
      (`bin/tests/test_acceptance.py:3320`): one interactive seed plus three real headless runs
      building three mutually exclusive git positions, all exiting 0 and recorded `finished` —
      which is the point, since SC-003's failure is a run that looks like a clean success. Asserts
      `set(payload["unpushed"]) == {blind, plain}` (set equality, so an invented alarm fails too),
      the human alarm line exactly once naming both ids and NOT the no-upstream one, and
      `pushed: false` / `pushed: null` on the right records. VERIFIED PASSING in the full tier
- [X] T032 [P] [US2] Acceptance: S6 — an `ephemeral` workspace with no clone yields
      `state: no-repository`, not a crash and not a null record.
      **GAP CLOSED.** `test_an_ephemeral_workspace_with_no_clone_records_no_repository`
      (`bin/tests/test_acceptance.py:3479`), asserting `repository is not None` with
      `state: no-repository`, and the rendered rows POSITIVELY (a null repository renders one row
      and a captured one four, so their presence is what separates "looked and found nothing" from
      "never looked"). Needed one additive `acc` fixture change — an optional keyword-only
      `mount=[…]` — because a stand-in agent cannot live on an ephemeral workspace. VERIFIED
      PASSING in the full tier

---

## Phase 5: User Story 3 — what it cost (P2)

**Goal**: capture usage where the agent reports it; say *unknown* where it does not.

- [x] T033 [US3] `usage` per data-model §4: `{"reported": false}` by default, agent's own units and
      the agent's name when reported
- [x] T034 [US3] Per-agent extraction for the agents that report anything — and **nothing invented
      for those that do not**
- [x] T035 [P] [US3] Render `unknown` as the word in human output and as `reported: false` in JSON
      — **never `0`** (C9, SC-004). A false zero silently understates every total it enters
- [x] T036 [US3] Aggregation stating `unknown_components` rather than excluding them (FR-007)
- [x] T037 [P] [US3] Test that usage is **not normalised across agents** (FR-015, C10) — no
      cross-agent total is offered, and `units` keeps the agent's own keys

---

## Phase 5b: User Story 2 (cont.) — which run changed this file (SC-007)

Added after `/speckit-analyze` found SC-007 with **zero** implementing tasks (finding G1). One
design decision (research R11) settles it and also resolves the rewritten-history edge case (G3):
**capture the paths at exit, do not resolve the SHAs at query time.**

- [x] T051 [US2] Capture changed paths at exit in `image/entrypoint.sh`
      (`git diff --name-only <start_head>..<end_head>`) into `repository.paths` (data-model §3).
      Captured at WRITE time, so the answer needs no repository months later and survives a rebase
      — query-time resolution fails exactly when the record is most valuable (research R11)
- [x] T052 [US2] Cap the path list and set `paths_truncated`. **Never a silent cap**: a truncated
      list that looks complete answers SC-007 with a confident *"no run changed that file"* when one
      did — the defect shape this project keeps finding
- [x] T053 [US2] `runs list --changed <path>` (C16), reading **stored records only** — no
      repository access, so it works on another machine and against rewritten history
- [x] T054 [P] [US2] A candidate record with `paths_truncated: true` that does not match MUST be
      reported as **uncertain**, not silently omitted (C16). Test both: a match, and an uncertain
      non-match
- [x] T055 [US2] Acceptance S13: with **N ≥ 5** runs, `--changed` returns exactly the runs that
      touched the file (SC-007) — and still does with the repository **deleted**, which is what
      proves the capture-at-write-time property rather than assuming it
- [x] T056 [P] [US2] A commit SHA that no longer resolves degrades gracefully (spec edge case,
      finding G3): `paths` still answers, and `commits` is rendered as unresolvable rather than
      dropped or crashing

---

## Phase 6: The honest edges

- [x] T038 A record write that fails **surfaces without failing the run** (FR-008, C11) — as a
      `notes` entry when a record exists, as a tool warning when it does not
- [x] T039 [P] Concurrency: N environments produce N complete, non-interleaved records (FR-009,
      C12). Guaranteed by construction via one-file-per-record (R3), so the test exists to prove
      the construction was actually used.
      Discharged by T047's five REAL concurrent environments — there is no separate unit-level
      test, because a unit test with one writer cannot exercise the property this task names
- [X] T040 Retention: prune by age and count at ingestion, with documented defaults (FR-011, C14).
      **The COUNT rule was rewritten after review found the first two versions defeated.** Plain
      newest-first let one night of restart records evict every older record; the per-UTC-day share
      that replaced it held only while the burst stayed inside one day, and the motivating scenario
      is an OVERNIGHT loop, which crosses UTC midnight by construction — measured, 600 records on
      one day preserved all 30 days of history and the SAME burst split across two days deleted
      every one of them with 500 records. The rule is now `_round_robin_keeps` over the UTC day,
      parameter-free (no share constant to be defeated at `bound/S` buckets), and SHARED with the
      egress store, which passes the destination as its bucket instead. Two further fixes here:
      `_record_epoch` clamps `started_at` to the moment the store wrote the record down, so a
      container clock in the future can no longer make a record immortal under the age bound; and
      the age bound skips whatever the CURRENT drain just took custody of, because a host switched
      off for four months was having its records stored, its volume copy cleared and its stored
      copy deleted inside one command
- [x] T041 [P] Test that pruning is bounded and that the documented default is the enforced one —
      a documented number the code does not use is the recurring defect of this repo
- [x] T057 **Records lost to an out-of-band volume removal must be VISIBLE** (spec edge case,
      finding G2). T017 drains on tool teardown, but `docker volume rm` behind the tool's back
      loses pending records silently. Detect the gap — a known environment whose runs volume has
      vanished with records never ingested — and say so
- [x] T058 [P] **Test that the record's field set is CLOSED** (finding U1, SC-005): every field
      except `task` is tool- or git-derived. The 100%-no-credentials claim rests entirely on that
      closure, and nothing currently asserts it — a new free-text field could be added and SC-005
      would still "pass"
- [x] T042 Interactive sessions recorded as a distinct kind with the interactive vocabulary and the
      same repository capture (FR-013); acceptance S8 asserts an ended session is never `finished`.
      The vocabulary is enforced at the write (`runs_outcome_is_legal`) and measured by hand in
      T050. **S8's own script cannot produce the value it predicts**: detaching does not end a
      session, and even `tmux kill-server` does not end the container — the entrypoint waits on
      `tail -f /dev/null`, so an operator-driven session ends via SIGTERM as `stopped`. `ended` is
      reachable (measured: killing that `tail` yields `ended` plus a note naming the status) but it
      is the ABNORMAL-exit outcome, not the ordinary end of a session. See T050's note

---

## Phase 7: Polish & cross-cutting

- [x] T043 [P] `docs/observability.md` — what a record is, what it is **not** (C15, FR-014), where
      records live, retention, and the task-text rule
- [x] T044 **Reconcile `docs/threat-model.md`** for the task-text exposure (research R9,
      Constitution III + the Development Workflow clause). Every other field is tool- or git-derived,
      which is what makes this bounded and statable rather than open-ended
- [x] T045 [P] State the task-text rule **where a task is given**, not only in docs — the operator
      types the task there, and that is where the warning is read
- [x] T046 [P] Update `docs/layout.md` cross-references and `CLAUDE.md`'s one-line invariant;
      re-measure CLAUDE.md against its 2000-token budget and **prune before adding**
- [x] T047 Acceptance: S10 — five concurrent environments each yield exactly one complete record
- [x] T048 Acceptance: S12 — the task text round-trips verbatim, confirming no accidental redaction
      crept in and that the recorded field is the one documented
- [x] T049 **Ingestion exercised against a REMOTE context** (research R10). A test that only runs
      locally passes while the remote path — the entire reason the tar-over-stdout mechanism exists
      — is never executed
- [x] T050 Run `scripts/quality-gate.sh` **unpiped** plus the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S12 by hand. A `-k` pattern matching nothing is
      indistinguishable from one whose tests all passed.
      Gate exit 0; acceptance 67 passed / 2 skipped (both Hetzner, billable, no `HCLOUD_TOKEN`),
      no `-k`. S5–S13 executed by hand against real containers; S8's script does not produce the
      value it predicts (see T042). Two defects found and fixed here: the gate's own
      `TOOL_HINTS` lookup never fired (`local a=$1 b=${T[$a]}` expands before it binds, so every
      failure since the table was written lost its hint), and `bin/tests/test_entrypoint_repository.sh`
      was a suite the gate never ran.
      **RE-RUN after the post-merge CI failure and the review findings**: `scripts/quality-gate.sh`
      unpiped → 0; `pytest -m acceptance bin/tests/test_acceptance.py` with no `-k` → **69 passed,
      2 skipped** in 11m15s (the same two Hetzner skips; +2 over the previous run are T031 and
      T032). `pytest bin/tests -m acceptance` — CI's own invocation — collects the identical 71.
      Both CI failures reproduced first and then fixed: `bin/tests/test_entrypoint_repository.sh`
      was creating its fixture with `git init --bare` and no `-b`, so the bare repo's HEAD followed
      the HOST's `init.defaultBranch` — `main` in this operator's `~/.gitconfig`, `master` on a CI
      runner with no global config — and the clone landed on an unborn `master` with no upstream, so
      eleven assertions were reading a correct entrypoint answer as a capture failure. Now
      `git init -q --bare -b main`; all five shell suites verified under `HOME=<empty dir>`, the CI
      condition (repository suite 45 passed/11 failed → **56 passed/0 failed**)

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
