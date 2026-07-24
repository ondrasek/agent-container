---
description: "Task list for Guided Setup Wizard (specs/007)"
---

# Tasks: Guided Setup Wizard (state-aware next-step guidance)

**Input**: Design documents from `specs/007-guided-wizard/` (plan.md, spec.md, research.md, data-model.md, contracts/guided-wizard.md, quickstart.md).

**Scope**: replace the wizard's flat menu with a **state-aware guide** — a **pure recommendation engine** (`build_snapshot → assess_stages → recommend_next_step`, no I/O) driving a **thin interactive shell** that reuses the tool's **existing** probes and action handlers. **Additive** over proven code; **no new dependency** (Constitution VI) and **no new underlying operation**. Inherited (driven, not rebuilt): `probe_host_runtime`, `image_exists`, `resolve_env_file`, `host_ps_rows`, `probe_session`, `resolve_deploy_host`, and the `wizard_start`/`wizard_attach`/`wizard_logs`/`wizard_stop`/orphan-purge handlers.

**Tests**: INCLUDED (Constitution V; the engine is a pure function precisely so its rules are hermetically testable — the plan's central decision).

## ⚠️ Single-file constraint (read before using [P])

Almost all implementation is in the one PEP 723 file **`bin/agent-container`** (the pure engine + the rewritten `wizard_loop`). Tasks that edit `bin/agent-container` are mutually **SEQUENTIAL** — never `[P]` with each other. `[P]` is ONLY for genuinely separate files: the new test module (`bin/tests/test_guided_wizard.py`), the acceptance module (`bin/tests/test_acceptance.py`), and docs (`README.md`, `CLAUDE.md`).

**Complexity budget**: the gate enforces xenon rank B (CC ≤ 10). `recommend_next_step` is branchy — keep it under budget by extracting per-case helpers (a stage-assessor per stage, a corrective-picker), not one large conditional.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [X] T001 [P] Add `bin/tests/test_guided_wizard.py` (new module) with hermetic fixtures: reuse the `wiz` fixture from `bin/tests/conftest.py`; a factory that builds an `EnvSnapshot` from plain args (no live runtime, no TTY) so every engine rule is asserted against an injected snapshot.

**Checkpoint**: a place for the engine's hermetic unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared, pure substrate every user story consumes — the snapshot data model, the stage assessment, the snapshot assembler (stage → existing probe), and active-target resolution. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); the test task is `[P]`.

- [X] T002 [P] Write failing tests in `bin/tests/test_guided_wizard.py`: `StageStatus` tri-state (`satisfied`/`unsatisfied`/`unusable`); `assess_stages` returns the ordered chain (`runtime→host→image→credentials→container→running`) with `credentials` marked **soft** and all others hard (data-model + contracts §2); the assembler classifies **unusable** distinctly from **absent** (host registered-but-unreachable; container present-but-exited); `resolve_active_target` defaults the host to the implicit local target, flags `ambiguous_host` when >1 registered, and reuses the sole existing container name else offers a default (FR-017/019).
- [X] T003 Add the dataclasses in `bin/agent-container`: `StageStatus` (enum), `SetupStage`, `ActiveTarget`, `EnvSnapshot`, `RecommendedAction`, `ActionOutcome` (fields per data-model.md), with `RecommendedAction.equivalent_cmd` secret-free by construction.
- [X] T004 Add `assess_stages(snapshot) -> list[SetupStage]` (pure, no I/O) — the ordered tri-state assessment walking the fixed prerequisite chain (FR-016); `credentials` is soft (FR-018); in `bin/agent-container`.
- [X] T005 Add `build_snapshot(target) -> EnvSnapshot` — the thin assembler mapping each stage to its **existing** probe (`detect_runtime`/`probe_host_runtime`, `image_exists`, `resolve_env_file`, `host_ps_rows`, `probe_session`), **bounded to the active target's host** (FR-017), plus the host container inventory and the orphan-volume scan; in `bin/agent-container`.
- [X] T006 Add `resolve_active_target(selected_host, selected_name) -> ActiveTarget` — host via `resolve_deploy_host` (implicit-local default; `ambiguous_host` when >1 registered and none selected), container name reusing the sole existing container else a default (FR-017/019, reusing `container_name`); in `bin/agent-container`.

**Checkpoint**: a snapshot can be assembled and assessed, and the active target resolved — the engine substrate is ready. User stories can begin.

---

## Phase 3: User Story 1 — Zero to attached, guided the whole way (Priority: P1) 🎯 MVP

**Goal**: from an empty machine, the wizard leads the operator through host → image → (soft credentials) → name+start → attach, one reasoned recommendation at a time.

**Independent Test**: on a machine with no host, no image, no container, follow only the recommendations and land in a running, attachable session; every step names one recommended action with a reason (quickstart A/B/C).

- [X] T007 [P] [US1] Write failing tests in `bin/tests/test_guided_wizard.py`: `recommend_next_step` forward path — the empty→attached ordering; **exactly one** recommendation each step (SC-002); it never returns an action whose **hard** prerequisites are unmet, returning the prerequisite's action instead (SC-003); a missing image yields a **build** recommendation (US1-2); soft credentials produce a `supply_credentials` recommendation that does **not** gate `start` — `start` stays in the valid set (FR-018); each recommendation carries a plain-language `reason` (FR-003) and a **secret-free** `equivalent_cmd` (FR-010, Constitution III).
- [X] T008 [US1] Add `recommend_next_step(snapshot) -> RecommendedAction` forward-progress logic (first unsatisfied **hard** stage → its action; all hard satisfied + not running → `start`; running → `attach`), each with a `reason` and `equivalent_cmd`; keep xenon rank B via per-case helpers; in `bin/agent-container`.
- [X] T009 [US1] Rewrite `wizard_loop` as **gather → render → act → re-evaluate**: `build_snapshot(resolve_active_target(...))` → show the state summary + the single marked recommendation → perform via existing handlers (`wizard_start`/`wizard_attach`, the build path) → re-run on a fresh snapshot (FR-005); keep the no-TTY guard (FR-013); add the container-naming prompt (FR-019); and honor **FR-015** — quit is always selectable, and cancelling an in-progress recommended action returns to the (re-evaluated) guided state, never a dead end; in `bin/agent-container`.
- [X] T010 [P] [US1] Acceptance in `bin/tests/test_acceptance.py`: on a real local runtime with no container, driving the wizard's recommended steps (scripted input) reaches a running/attachable container (SC-001); and the no-TTY invocation declines cleanly pointing to the subcommands (FR-013).

**Checkpoint**: a first-time operator reaches an attached session by following recommendations alone — the shippable MVP.

---

## Phase 4: User Story 2 — Adapts to a healthy, in-use environment (Priority: P2)

**Goal**: with containers already running, lead with day-to-day actions (attach/logs/manage), not setup.

**Independent Test**: with ≥1 running container, the recommended step is a day-to-day action; with multiple, the wizard helps pick which (quickstart D).

- [X] T011 [P] [US2] Write failing tests in `bin/tests/test_guided_wizard.py`: a snapshot with a running container → `recommend_next_step` returns a **day-to-day** action (attach), not a setup step (US2-1); multiple running containers → the recommendation/`valid_actions` carry the **which-one** requirement (FR-014); logs/stop appear among the valid actions.
- [X] T012 [US2] Extend `recommend_next_step` for the healthy/running case (day-to-day action) and add the **which-one** target-selection hook consumed by the shell (FR-014, reusing `host_ps_rows`); in `bin/agent-container`.

**Checkpoint**: the guide stays useful after first-run — it reflects where the operator actually is.

---

## Phase 5: User Story 3 — Detects and guides out of a broken/partial state (Priority: P2)

**Goal**: name the specific fault (runtime unreachable, container exited/crash-looping, missing credential, orphaned volumes) and recommend the corrective step with a reason.

**Independent Test**: simulate each broken state and verify the wizard identifies it and recommends the corrective step, ahead of unrelated actions (quickstart E).

- [X] T013 [P] [US3] Write failing tests in `bin/tests/test_guided_wizard.py`: each `problem` (runtime unreachable, exited/`Restarting`, missing credential, orphaned volumes) → its corrective recommendation, taking **precedence over forward progress** (SC-004); `unusable` (present-but-broken) is treated distinctly from `unsatisfied` (absent).
- [X] T014 [US3] Add problem detection to `build_snapshot` (the R4 signal→problem mapping) and the **corrective-precedence** branch in `recommend_next_step` (a detected problem outranks forward progress); keep complexity in budget; in `bin/agent-container`.

**Checkpoint**: the wizard is most helpful exactly when something is broken — it names the fault and leads out.

---

## Phase 6: User Story 4 — Always explains, never traps (Priority: P3)

**Goal**: every step shows a state summary + a distinctly-marked recommendation, still lets the operator choose any valid action, and shows the equivalent non-interactive command.

**Independent Test**: at any step, the state summary + marked recommendation are shown together, a valid non-recommended action can still be chosen, and the equivalent command is displayed for the chosen action (quickstart F).

- [X] T015 [P] [US4] Write failing tests in `bin/tests/test_guided_wizard.py`: `valid_actions(snapshot)` lists **every** currently-valid action (escape hatch, SC-007) and **always includes `quit`** (FR-015); withholds any action whose **hard** prerequisites are unmet (FR-004 — withheld, not shown-marked); the recommendation is flagged distinct from the alternatives (FR-002); every action's `equivalent_cmd` is present and **secret-free** for a snapshot carrying a resolved credential (SC-006, Constitution III); destructive actions carry the confirm flag (FR-011).
- [X] T016 [US4] Add `valid_actions(snapshot) -> list[RecommendedAction]` (withholding hard-unmet actions per FR-004; always including `quit` per FR-015) and wire the shell to: render the compact state summary + the marked recommendation (FR-009/002), offer the escape-hatch actions (FR-008), show the equivalent command for the chosen action (FR-010), confirm destructive ones (FR-011), and on a failed **or cancelled** action **report + re-evaluate** rather than advance (FR-012/FR-015); in `bin/agent-container`.

**Checkpoint**: the wizard teaches — state + reasoned recommendation + CLI equivalent — while never hiding a valid choice.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell) and fix all findings; confirm `recommend_next_step`/`build_snapshot` stay within xenon rank B (extract helpers if needed).
- [X] T018 [P] Update `README.md` and the `CLAUDE.md` Decisions bullet: the guided wizard (state-aware next-step guidance replacing the flat menu; the pure-engine/thin-shell split; single active target with bounded probing; soft credentials; the equivalent-command teaching aid) — within the CLAUDE.md 2000-token budget (prune before adding).
- [X] T019 Run quickstart.md Scenarios A–G (local) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → the test module. Blocks the engine tests.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (the data model, `assess_stages`, `build_snapshot`, `resolve_active_target`).
- **US1 (P3)** → depends on Foundational. **The MVP** (forward journey + shell rewrite).
- **US2 (P4)** → depends on Foundational + US1's `recommend_next_step` (extends it for the healthy case).
- **US3 (P5)** → depends on Foundational + US1 (adds corrective precedence over the forward path).
- **US4 (P6)** → depends on US1's shell (adds the escape hatch + equivalent-command rendering across all cases).
- **Polish (P7)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation task(s) (single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 (new test file, `[P]`).
- Foundational: T002 (tests, `[P]`) alongside; impl T003→T004→T005→T006 sequential (same file).
- US1: T007 ∥ T010; impl T008→T009 sequential.
- US2: T011 ∥; impl T012.
- US3: T013 ∥; impl T014.
- US4: T015 ∥; impl T016.
- Polish: T018 `[P]`; T017/T019 sequential (gate, then record).

## Implementation Strategy

### MVP first (US1 — zero to attached)

1. Phase 1 Setup → 2. Phase 2 Foundational (data model + `assess_stages` + `build_snapshot` + `resolve_active_target`) → 3. Phase 3 US1 (forward `recommend_next_step` + the rewritten `wizard_loop`) → **STOP & VALIDATE** a first-time operator reaches an attached session by following recommendations alone (quickstart A/B/C), and the no-TTY guard holds → ship. This alone delivers the headline "guide from nothing to running" value.

### Incremental delivery

US2 (healthy → day-to-day), US3 (broken-state detection + corrective precedence), and US4 (escape hatch + equivalent-command teaching) each layer onto the same engine, each independently testable by injecting the corresponding snapshot into `recommend_next_step`/`valid_actions`. Polish (gate, docs, quickstart run) closes the feature.
