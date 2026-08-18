# Tasks: `doctor` — Preflight Validation

**Feature**: `013-doctor-preflight` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: spec.md, plan.md, research.md (R1–R10), data-model.md, contracts/doctor-contract.md
(C1–C17), quickstart.md (S1–S14)

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelisable: different file or independent region, no incomplete dependency
- **[US1/US2/US3]** — the user story a task serves (user-story phases only)

## Path Conventions

Single-file CLI. Nearly everything lands in `bin/agent-container`; tests in `bin/tests/`; one line
in `image/Dockerfile`. No new module — the checks are readers over state this tool already
understands (Constitution VI).

## Tests

**Requested and load-bearing.** The plan's verification section names both tiers, and Constitution V
is validation-first. Note the ordering inversion in Phase 2: **the zero-side-effect gate lands
before the checks it guards**, because a gate written after the code it constrains gets written to
pass whatever exists (R1).

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Add the `Check` / `Finding` / `Scope` model to `bin/agent-container` per data-model
      §1–§3 — three statuses (`pass`/`fail`/`unknown`), severity on the CHECK not the outcome, and
      `remedy` **required at construction** so a remedy-less finding cannot be built (FR-004, C3,
      SC-003)
- [X] T002 [P] **Reuse** the existing `EXIT_OK` / `EXIT_FAILURE` / `EXIT_REFUSED` (0/1/2) in
      `bin/agent-container` for `doctor`'s three outcomes, and record doctor's reading of each in the
      existing `EXIT_CODES` table (FR-011, R4). **Do NOT add `DOCTOR_EXIT_*` aliases**: they would
      duplicate the same three values under a second name, and a second namespace is precisely how
      doctor's `2` and the tool-wide `2` drift apart in meaning. Feature 019 made that table the
      single source and pinned `--help` to it; keep it that way
- [X] T003 [P] Register the `doctor` command skeleton in `bin/agent-container` — `[NAME]`,
      `--host`, `--json` — returning an empty report, so the surface exists before any check does.
      The name is **`doctor`**, never `status`, which is already an alias of `plan` answering a
      different question (FR-001, R6)
- [X] T004 [P] Add `doctor` to the command list in `completions/agent-container.bash` and
      `completions/agent-container.zsh`; the sibling test pins the completions' list to the CLI's
      and fails until both are updated (FR-001)

**Checkpoint**: `agent-container doctor` runs, reports nothing, and exits 0.

---

## Phase 2: Foundational (Blocking Prerequisites)

**These block every user story. T005 and T006 are the two that make the rest trustworthy.**

- [X] T005 **THE GATE: acceptance S1** in `bin/tests/test_acceptance.py` — snapshot the project,
      state and user-config trees (**naming `hosts.conf` and the inventory explicitly**, not merely
      "the config dir"), plus containers, volumes and images, around a `doctor` run, and assert
      **byte-identical** (C1, FR-002, SC-002).
      **Land this BEFORE any check** — written afterwards it is written to pass whatever was
      implemented, which is how a read-only claim becomes a claim rather than a property.
      **But it is a REGRESSION gate, not a one-time proof.** Authored here it passes trivially:
      `doctor` runs no checks yet, so there is nothing that could mutate anything. It only starts
      carrying weight as checks land, so **every task that adds a check re-runs it** (T017–T021,
      T038, T045, T048), and a task is not done until it is green with that check present. A gate
      that cannot fail on the day it is written is the exact defect this feature exists to prevent,
      reproduced inside the guard against it
- [X] T006 [P] Extend T005 to a project on the **pre-011 layout** — the path where a deploy would
      call `migrate_flat_state()`, which relocates files, is idempotent, and documents itself as
      *"safe to call repeatedly"*. It is the trap R1 exists to name, and the only deploy-path
      helper that looks harmless
- [X] T007 [P] Hermetic test in `bin/tests/test_doctor.py` asserting the `doctor` code path
      references none of `migrate_flat_state`, `drain_host_records`, `record_inventory_creation`
      (R1). Structural, because T005 catches a mutation only when the test project happens to
      trigger it — an unused-but-reachable call passes T005 and fails here.
      **Delimit the path mechanically**, since a 14k-line single file has no natural boundary: walk
      the transitive closure of `__code__.co_names` from the `doctor` command object and assert the
      forbidden names are absent from it. A grep over the whole file would pass or fail for reasons
      unrelated to `doctor`
- [X] T008 Add the check REGISTRY to `bin/agent-container`: an ordered collection of named checks,
      each invoked independently, each returning a `Check`. **No check may call `die()`** (C2, R9)
- [X] T009 Add the `Fatal`-trapping adapter in `bin/agent-container` that runs an existing
      validator and converts its `Fatal` into a `Finding`, preserving the message VERBATIM (R8, R9)
- [X] T010 [P] Hermetic test for T009: a raising validator becomes a finding, the run continues,
      and the finding's `remedy` is the validator's own string — not a paraphrase (C4)
- [X] T011 [P] Hermetic test that a check raising an **unexpected** exception becomes `unknown`
      rather than propagating (C10). The registry must survive a check author's mistake, or one
      bad check silences every other
- [X] T012 Assemble the `Report` (data-model §4) and wire `--json` through the Feature 009
      envelope; confirm `NO_JSON_COMMANDS` still reads `{host env, completions, attach, menu}`
      (C-Command, R7)
- [X] T013 [P] Hermetic test that `--json` carries **every** check including passes — a consumer
      that cannot see which checks ran cannot tell "checked and fine" from "never asked"
      (data-model §4)

**Checkpoint**: the gate exists and is green **against an empty report**, and no single check
can end the run. Read-only is not yet *proven* — there is nothing to be read-only about until
Phase 3 adds checks and re-runs T005 behind each one.

---

## Phase 3: User Story 1 — Ask whether a deploy would work (Priority: P1) 🎯 MVP

**Goal**: one command, one ordered account of what a deploy would find, changing nothing.
**Independent test**: S2 — a project with several deliberate problems reports **all** of them in
one pass, with remedies, having changed nothing.

### Tests for User Story 1

- [X] T014 [P] [US1] Acceptance S2 in `bin/tests/test_acceptance.py` — break three things at once
      (pre-011 layout, a credential pointing at a nonexistent file, an unreachable host) and assert
      all three appear in ONE run (C2, FR-003, SC-001)
- [X] T015 [P] [US1] Acceptance S3 — `doctor --json` yields **zero** findings with a null or empty
      `remedy` (C3, SC-003)
- [X] T016 [P] [US1] Acceptance S4 — the layout remedy is **byte-identical** to the one a deploy
      prints (C4, SC-008). Assert the identity, not a substring match: two strings that agree today
      drift the moment one is edited, and both still read correctly alone

### Implementation for User Story 1

- [X] T017 [US1] The **layout** check in `bin/agent-container` — reuses `refuse_superseded_layout`
      through T009's adapter so the remedy is the same producer's string (C4, R8) — **re-run T005**
- [X] T018 [P] [US1] The **per-environment configuration resolution** check — parses
      `.agent-container/environments.yaml` with `yaml.safe_load` (never a regex) and reports each
      environment's resolution independently (FR-012, C17) — **re-run T005**
- [X] T019 [P] [US1] The **credential resolvability** check per R3: `env` → is the variable set;
      `file` → does the path exist and is it git-tracked plaintext; manager sources → is the
      resolver binary on `PATH`, else **unknown**. **Never calls `resolve_credential_value()`**
      (C8, C9) — **re-run T005**
- [X] T020 [P] [US1] The **host reachability** check — each registered host independently, bounded
      per host, `unknown` on timeout (C5, C10, C12) — **re-run T005**
- [X] T021 [P] [US1] The **port availability** check — a **blocking** finding only when the port is
      held by something that is NOT this environment's own container (C14, R10) — **re-run T005**
- [X] T022 [US1] Order the report: blocking, then advisory, then unknown; stable within each group,
      so two runs can be diffed and an operator can confirm they fixed something (data-model §4)
- [X] T023 [P] [US1] Hermetic tests for T019's classification table — one case per source, and one
      proving `resolve_credential_value` and `_run_resolver` are **unreachable** from the check
      (FR-009, FR-010, C8, C9). This is the machine-checkable half of "never prompts"; the other
      half is T053a, because a prompt is a UI event no assertion can observe
- [X] T024 [P] [US1] Hermetic test for T021 asserting a RUNNING environment's own port is `pass`
      (C14, R10). Without it, `doctor` fails on every healthy deployment — the port derives from the
      name

**Checkpoint**: US1 is independently usable. It reports; it changes nothing.

---

## Phase 4: User Story 2 — Distinguish "broken" from "not yet" (Priority: P1)

**Goal**: severity and an actionable exit status, so an operator knows whether to act now.
**Independent test**: S6 — one blocking and one advisory condition are distinguishable by a human
and by a program, and the advisory-only run exits 0.

### Tests for User Story 2

- [X] T025 [P] [US2] Acceptance S6 — advisory-only exits **0** and `doctor && up` **proceeds**;
      a blocking failure exits **1** (C6, C7, FR-011, SC-004)
- [X] T026 [P] [US2] Hermetic test of the full status×severity → exit mapping (data-model §1),
      including the two that are easy to get wrong: an advisory `fail` contributes nothing, and an
      **`unknown` never yields 1** (FR-011a, SC-004a)
- [X] T027 [P] [US2] Hermetic test that **no** input combination produces an exit above **2**
      (SC-004a, S7, R4). `3` is *pending registration* tool-wide — a `doctor` returning it tells an
      automated caller something false about an SSH key
- [X] T028 [P] [US2] Acceptance S14 — a healthy run's human output is **≤ 24 lines** (the threshold
      SC-007 now pins) while `--json` still carries every check (C16, FR-014, SC-007). Assert the
      number: "fits one screen" is unfalsifiable, and a criterion nothing can fail is not a criterion

### Implementation for User Story 2

- [X] T029 [US2] Assign a severity to every check from Phase 3, declared BY THE CHECK, not derived
      per-run from the outcome (C6, FR-005) — the same condition must not be blocking on Tuesday
      and advisory on Wednesday
- [X] T030 [US2] The exit mapping in `bin/agent-container` per data-model §1: blocking `fail` → 1;
      advisory `fail` → 0; `unknown` → **never 1** (FR-011, FR-011a)
- [X] T031 [US2] Exit **2** with a message naming the *command* as the thing that failed, never
      presented as a finding about the environment (C15, FR-013)
- [X] T032 [P] [US2] Hermetic test for T031: a `doctor` that cannot run is distinguishable from a
      `doctor` reporting an unhealthy environment — assert on both the code and the wording (FR-013,
      C15)
- [X] T033 [US2] The brief all-clear output: findings plus a one-line summary of passes, not a wall
      of green (C16, FR-014)

**Checkpoint**: the report is readable by a human and branchable by a program.

---

## Phase 5: User Story 3 — Check the machine, not just one project (Priority: P2)

**Goal**: a useful answer with no project at all — the new-machine case.
**Independent test**: S11 — run outside any project; machine-level checks report and it does not
fail.

### Tests for User Story 3

- [X] T034 [P] [US3] Acceptance S11 — outside a project, machine-level checks report, the output
      says plainly that no project was found, and the exit is **0** when the machine is fine
      (C11, FR-007). Failing here would make the command useless in the case US3 exists for
- [X] T035 [P] [US3] Acceptance S10 — with one reachable and one unreachable host, **both** are
      listed; neither suppresses the other and the unreachable one is never silently absent
      (C10, C12, FR-008, SC-005)
- [X] T036 [P] [US3] Hermetic test that `Scope` resolves to `environment` / `project` / `machine`
      from the invocation and cwd, and that the report states which (data-model §3)

### Implementation for User Story 3

- [X] T037 [US3] Scope resolution in `bin/agent-container`: a NAME narrows to one environment; in a
      project with no name, every declared environment; outside a project, `machine` — **a success
      state, not an error** (FR-007, C11)
- [X] T038 [P] [US3] Machine-level checks: registered hosts, user configuration, the installed tool
      itself (FR-007, FR-012) — **re-run T005**
- [X] T039 [US3] Per-host isolation — one unreachable host must not extend the run past its bound
      nor suppress the others (C10, FR-008)
- [X] T040 [US3] Report the scope in both views, including what was NOT looked at, so an operator
      is not misled by a narrow run reading as a clean one (data-model §3)

**Checkpoint**: useful on a fresh machine, before any project exists.

---

## Phase 6: Image freshness (FR-012a/b) — a build-time change with a diagnostic payoff

**Both halves land together, or the check reports `unknown` forever.**

- [X] T041 Add an `ARG` + `LABEL org.opencontainers.image.version` to `image/Dockerfile` (R5, C13)
- [X] T042 Pass the build arg from `build` in `bin/agent-container`, sourced from
      `_resolve_version()` — currently `[rt, "build", "-t", tag, ctx]` with no args (FR-012a, C13)
- [X] T043 **OMIT the label when the version is unresolvable** rather than stamp `0.0.0+unknown`
      (R5). A meaningless value that looks like an answer is worse than the absence FR-012b already
      handles correctly
- [X] T044 [P] Hermetic test for T043: an unresolvable version produces build argv with **no**
      version arg — not one carrying the sentinel (FR-012b, C13, R5)
- [X] T045 The **image freshness** check in `bin/agent-container` — `image inspect` for the label,
      compared LOCALLY against the installed version; no network, no container registry (C13,
      FR-012a). A label rather than an `ENV` precisely because reading it must not start a container.
      **Name which image**: the tag the environment under check would deploy, per environment; in
      `machine` scope, the default tag. A project declaring several environments may pin several
      tags, so "the image" is undefined without this rule — **re-run T005**
- [X] T046 [P] An image with **no** label reports `unknown` — never fresh, never stale (C13,
      FR-012b). Reporting it stale nags every operator into a rebuild they may not need; reporting
      it fresh asserts something unknown
- [X] T047 [P] Acceptance S12 — an image built before stamping reports `unknown`; after
      `agent-container build` it reports `pass`; and the label read back is the real version, never
      `0.0.0+unknown`

---

## Phase 7: The honest edges

- [X] T048 A check that times out or errors reports `unknown` with a remedy naming the manual
      check (C5, FR-006) — *unknown* must still be actionable, not a shrug — **re-run T005**
- [X] T049 [P] Acceptance S5 — a host at an unroutable address yields `unknown` for reachability,
      **never `pass`** (C5). The scenario the feature exists to get right: a diagnostic reporting
      healthy is what stops an operator looking further
- [X] T050 [P] Acceptance S9 — no credential value appears in `--json` or in human output, compared
      against the real file contents (C9, FR-010, SC-006)
- [X] T051 [P] Acceptance S13 — a running environment's own port is `pass`, against a real deployed
      container (C14, R10)
- [X] T052 Implement the **settled** provisioned-host tunnel policy (R2, decided 2026-08-17):
      `doctor` MAY call `ensure_tunnel()`; it MUST NOT create or remove a container, volume, image or
      host-registry entry. The line is **nothing that outlives the command**. Without the forward
      every provisioned host reads *unreachable*, which is a false negative on the check FR-012 asks
      for. This was an open judgment call and is now closed — an implementation task must not carry a
      decision, or whoever happens to run it decides. Reversible: the alternative is reporting
      provisioned hosts as `unknown` with a remedy naming the manual check
- [X] T053 [P] Hermetic test pinning T052's settled behaviour, so the judgment call lives in a test
      rather than only in research.md (FR-002, C1, R2)
- [X] T053a **Quickstart S8, AUTOMATED** (FR-009, C8): a `command` credential pointing at a script
      that records its own execution; assert the marker is absent after `doctor` runs, plus a
      hermetic sibling proving `resolve_credential_value` DOES create it, so the sentinel is known
      to fire. Originally specified as a by-hand check for a 1Password dialog — wrong instrument:
      the property is *the resolver was never invoked*, of which a dialog is merely one consequence,
      and an unlocked manager would show no dialog while still having run. This version is
      deterministic, needs nothing installed, and is not gated on an operator's attention

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T054 [P] `docs/` — document `doctor`: the three statuses, severity, the 0/1/2 exit table,
      what is checked, and that it is read-only (FR-002, FR-005, FR-006, FR-011). Name the file in
      `CLAUDE.md`'s "where the detail lives" index (Constitution: docs track behaviour)
- [X] T055 [P] `README.md` — a short `doctor` section, matching how 018/019 treat their commands
      (FR-001; Constitution: docs track behaviour)
- [X] T056 [P] `docs/threat-model.md` — reconcile the **013 row** (Constitution MUST). It alters no
      trust boundary but **touches a credential path**: record that no value is ever retrieved
      (stronger than not printed), and record the new residual — a report enumerating declared
      credentials and registered hosts is a **reconnaissance aid** on the operator's own machine,
      the same class as Feature 014's inventory
- [X] T057 [P] `docs/agent-interface.md` — the `doctor` payload shape, and that every check appears
      including passes (FR-011, C16, data-model §4)
- [X] T058 One-line invariant in `CLAUDE.md` (Constitution: docs track behaviour). **The file is
      ALREADY over its 2000-token budget**
      (~2090 against a ~2016 baseline), so this task **prunes before adding** and reports the
      before/after number. Do not add without cutting
- [ ] T059 Confirm the commit is `feat` — MINOR (Constitution VII). A new command plus an additive
      image label; nothing removed, no flag changes meaning
- [ ] T060 Run `scripts/quality-gate.sh` **unpiped** (read its exit code, never through `| tail`),
      then the full acceptance tier with **no `-k` selection**, then walk quickstart S1–S14 by
      hand. **Do not edit the tree while the acceptance tier runs** — it reads
      `bin/agent-container` from disk on every invocation, so a mid-edit run measures nothing (this
      cost two invalid runs during Feature 019)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** → no dependencies
- **Phase 2 (Foundational)** → blocks everything. **T005 blocks T017–T021**: no check is built
  before the gate that constrains it
- **Phase 3 (US1)** → needs Phase 2
- **Phase 4 (US2)** → needs Phase 3's checks to exist to assign severity to
- **Phase 5 (US3)** → needs Phase 3; independent of Phase 4
- **Phase 6 (freshness)** → needs Phase 2's registry; independent of Phases 4–5
- **Phase 7/8** → last

### User Story Dependencies

- **US1** — independent once Phase 2 lands. The MVP.
- **US2** — refines US1's output; does not add checks.
- **US3** — widens US1's scope; independent of US2.

### Within Each User Story

Tests → checks → ordering/severity → output shape.

### Parallel Opportunities

- T002/T003/T004 together (different files/regions)
- T006/T007 together, after T005
- T014/T015/T016 together — three independent acceptance scenarios
- T018/T019/T020/T021 together — four independent checks, one file but disjoint regions
- T025/T026/T027/T028 together
- T034/T035/T036 together
- T054/T055/T056/T057 together — four different documents
- T053 and T053a are independent; T053a needs a human at a screen

## Parallel Example: User Story 1

```text
# The three acceptance scenarios first, together:
T014  all problems in one pass
T015  every finding has a remedy
T016  the layout remedy is byte-identical

# Then the four independent checks, together:
T018  configuration resolution
T019  credential resolvability (never resolves)
T020  host reachability
T021  port availability
```

## Implementation Strategy

### MVP First (User Story 1 only)

Phases 1–3. That yields a command which answers "would a deploy work" for a project, reports every
problem with a remedy, and provably changes nothing. **Shippable on its own** — without severity it
is a flat list, which is less good and still useful.

### Incremental Delivery

1. **Phases 1–2** → a read-only harness, proven read-only before it can check anything
2. **Phase 3** → US1, the MVP
3. **Phase 4** → US2, severity and exit codes; `doctor && up` becomes an idiom
4. **Phase 5** → US3, the new-machine case
5. **Phase 6** → freshness, the check with no failure today
6. **Phases 7–8** → edges, docs, threat model, gates

### Ordering that is deliberate rather than conventional

**T005 before T017.** A read-only gate written after the checks is written against what the checks
happen to do. This is the same inversion Feature 019 needed for its no-private-key gate, and for
the same reason: **the property is an absence, and an absence is the one thing working output never
demonstrates.**

## Notes

- **61 tasks.** US1: 11 · US2: 9 · US3: 7 · freshness: 7 · setup/foundational: 13 · edges: 7 ·
  polish: 7
- **No check calls `die()`.** The existing validators all do; that is right for a deploy and fatal
  for FR-003 (R9)
- **`unknown` is a result, not a gap** (FR-006). Three tasks exist only to keep it from collapsing
  into `pass`
- **Every finding has a remedy at construction** (T001), so SC-003 cannot be violated by a
  forgotten field
