---
description: "Task list for Agent-Operable CLI (specs/009)"
---

# Tasks: Agent-Operable CLI

**Input**: Design documents from `specs/009-agent-operable-cli/` (plan.md, spec.md, research.md, data-model.md, contracts/agent-interface.md, quickstart.md).

**Scope**: make the CLI drivable by an AI agent — a **`--json` flag on every command** emitting a **versioned envelope**, **failures carrying a stable code + entity + remedy**, a **`context`** command, and a **`skill`** command installing an **Agent Skills**-conformant definition for four agents. **Additive**: interactive human behavior is unchanged (FR-019). **No new dependency** (Constitution VI).

**Three reuse facts that shape these tasks** (from plan/research):
1. Every failure already funnels through **one chokepoint** (`die` → `Fatal` → `cli`), so structured errors are a single-site change; the ~100 call sites are annotated **incrementally**.
2. `context` is a **serializer over Feature 007's pure engine** (`build_snapshot`/`recommend_next_step`) — no new assessment logic, and testable with no daemon.
3. `--json` exists on **3 of 23** commands — the work is extending a convention while centralizing emission.

**Tests**: INCLUDED (Constitution V; the envelope, failure descriptor, context serializer and skill installer are all pure or filesystem-scoped, and Constitution III must be pinned by test).

## ⚠️ Single-file constraint (read before using [P])

All implementation is in the one PEP 723 file **`bin/agent-container`**. Tasks that edit it are mutually **SEQUENTIAL** — never `[P]` with each other. `[P]` is ONLY for genuinely separate files: the new test module (`bin/tests/test_agent_interface.py`), other test modules, and docs.

**Constitution III is the gate**: no machine-readable payload may carry a secret value. T012 pins this explicitly and must not be deferred.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [ ] T001 [P] Add `bin/tests/test_agent_interface.py` (new module) with hermetic fixtures: reuse the `wiz` fixture from `bin/tests/conftest.py`; helpers to capture emitted stdout and parse it as JSON; a factory building a Feature 007 `EnvSnapshot` from plain args (no runtime, no TTY) for the `context` tests.

**Checkpoint**: a home for the agent-interface tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the versioned envelope, the single emitter, and the failure descriptor — the substrate every user story consumes. **No user story can begin until this phase is complete.** `bin/agent-container` tasks are sequential; test tasks are `[P]`.

- [ ] T002 [P] Write failing tests in `bin/tests/test_agent_interface.py` for the **envelope** (research R1): every payload carries `schema` = `agent-container/v1` and a boolean `ok`; **exactly one** of `data`/`error` is present; the envelope is the **only** thing on stdout (no colour/progress/table bleed, FR-002); and a success payload round-trips through `json.loads`.
- [ ] T003 Add the envelope constants and the single emitter to `bin/agent-container`: a `SCHEMA_VERSION` constant and `emit_json(data=None, error=None)` writing exactly one JSON object to stdout. All `--json` output goes through this — no command formats its own payload (research R1/R2).
- [ ] T004 [P] Write failing tests in `bin/tests/test_agent_interface.py` for the **failure descriptor** (data-model): `die()` accepts optional `code`/`entity`/`remedy` and `Fatal` carries them; a `die()` with no code yields the documented generic `unspecified` code (research R4) so existing call sites keep working; the human `message` is preserved unchanged (FR-019).
- [ ] T005 Extend `die()`/`Fatal` in `bin/agent-container` with optional `code`, `entity`, `remedy` (defaults preserving today's behavior), and render a **FailureDescriptor** from the existing `cli()` chokepoint when the invocation is in `--json` mode: envelope with `ok: false` on **stdout**, human prose still on **stderr**, exit non-zero (contract §1–2).

**Checkpoint**: any command can emit a versioned success or failure payload. User stories can begin.

---

## Phase 3: User Story 1 — An agent can drive the tool and recover from failure (Priority: P1) 🎯 MVP

**Goal**: every command speaks JSON on demand, every failure is actionable, and nothing ever blocks on a prompt.

**Independent Test**: drive a full lifecycle with `--json` only; force each defined failure class and confirm a stable code + entity + remedy and a non-zero exit, with no blocking (quickstart A/B/C).

- [ ] T006 [P] [US1] Write failing tests in `bin/tests/test_agent_interface.py`: a representative command emits a valid envelope under `--json`; **`--json` is accepted by every command** (introspect the command tree and assert the option exists on each, so a newly added command cannot silently miss it); human decoration never appears on stdout in JSON mode (FR-002).
- [ ] T007 [US1] Add the `--json` option to the remaining commands in `bin/agent-container` (20 of 23 lack it) and route each one's machine-readable branch through `emit_json` — keeping the existing human rendering behind the non-JSON branch, exactly as `do_host_ls`/`do_host_show`/`do_list` already do (FR-001/002, research R2).
- [ ] T008 [P] [US1] Write failing tests in `bin/tests/test_agent_interface.py` for the **non-interactive guarantee**: with no interactive terminal, a destructive command **refuses and names the authorizing flag** rather than prompting, and never blocks (FR-007, SC-003) — generalizing today's `down`/`wipe`/`host rm --destroy` behavior.
- [ ] T009 [US1] Generalize the non-interactive refusal in `bin/agent-container` so **no** command path can block on a prompt when stdin/stdout is not a TTY; each refusal names the flag that authorizes it (FR-007).
- [ ] T010 [US1] Enumerate the **defined failure classes** and annotate their `die()` call sites with `code`/`entity`/`remedy` in `bin/agent-container` — at minimum: no host registered, host unreachable, port unavailable, credential missing/unresolvable, invalid spec, container absent, image absent. Document the code set (contract §2). Un-annotated sites keep the generic `unspecified` code (research R4).
- [ ] T011 [P] [US1] Write failing tests in `bin/tests/test_agent_interface.py`: **each defined failure class** yields its stable `code`, the affected `entity`, and a `remedy`, with `ok: false` and a non-zero exit (SC-002); an agent can branch on `code` alone without reading `message`.
- [ ] T012 [P] [US1] **Constitution III guard** — write tests in `bin/tests/test_agent_interface.py` asserting that with a credential configured through each supported source, the resolved secret value appears in **no** `--json` payload and in **no** failure descriptor (SC-005). This is the load-bearing gate and must not be deferred.
- [ ] T013 [US1] Add **machine-readable help** to `bin/agent-container` by introspecting the existing Typer command tree (names, parameters, help text) into the envelope — never a hand-maintained catalogue, which would drift (FR-008, research R8).
- [ ] T014 [P] [US1] **Eval-contract regression guard** in `bin/tests/test_shell_integration.py`: `host env` and `attach --print`/`--ssh-config` still produce **empty stdout + non-zero** on error and do **not** accept `--json` (research R3, quickstart C). This is the one place the two output disciplines meet — assert it rather than assume it.

**Checkpoint**: an agent can complete a full lifecycle on machine-readable output alone and recover from every defined failure — the shippable MVP.

---

## Phase 4: User Story 2 — An agent can load the tool's context in one call (Priority: P2)

**Goal**: one command returns hosts, environments, conventions and the suggested next step — valid in every state, leaking nothing.

**Independent Test**: request `context` in an empty world, a healthy one, a broken one, and inside a declarative project; confirm valid output in all four and no secret anywhere (quickstart D/E).

- [ ] T015 [P] [US2] Write failing tests in `bin/tests/test_agent_interface.py`: `context` serializes a **constructed** Feature 007 snapshot (pure — no daemon) into the documented payload (target, stages with tri-state status, hosts, environments, conventions, credentials, problems, next_step); an **empty world** yields empty collections and `ok: true`, **not** an error; an **unreachable host** appears as a described state rather than failing the call (FR-010, SC-004); `unusable` remains distinct from `absent`.
- [ ] T016 [US2] Add the `context` command to `bin/agent-container` as a **serializer over the existing Feature 007 engine** (`build_snapshot` → `assess_stages` → `recommend_next_step`), extended with Feature 006 project conventions (governing `.agent-container/`, applicable env-file **path**) and Feature 008 credential **locators**; bounded to the active target so cost does not scale with host count (research R5).
- [ ] T017 [P] [US2] Write failing tests in `bin/tests/test_agent_interface.py`: the `context` payload names credential **locators only** (source kind + reference) and **never a resolved value** (FR-011); an env-file appears as a **path**, never its contents.

**Checkpoint**: an agent orients itself in one call, in any state, with no secret exposure.

---

## Phase 5: User Story 3 — An operator installs the skill (Priority: P3)

**Goal**: install / update / remove an Agent Skills-conformant definition for any of the four agents — idempotently, never clobbering, leaving no residue.

**Independent Test**: install into a scratch config, reinstall (no-op), hand-edit then update (refused), remove (no trace) — for each agent (quickstart F/G).

- [ ] T018 [P] [US3] Write failing tests in `bin/tests/test_agent_interface.py`: the rendered `SKILL.md` conforms to the **Agent Skills standard** (a folder containing `SKILL.md`; frontmatter carries at least `name` and `description`, FR-012a); and **FR-012c** — the body instructs the agent to pass `--json` on every invocation and **every command example in it carries the flag** (assert no example line invokes the tool without `--json`).
- [ ] T019 [US3] Add the **skill template** to `bin/agent-container` as an **embedded string constant** (not package data — that would break the `uv run --script` path, research R6), rendering a standard-conformant `SKILL.md` whose examples all carry `--json`.
- [ ] T020 [P] [US3] Write failing tests in `bin/tests/test_agent_interface.py` for the **install lifecycle** against a scratch config tree: install writes to the **project** scope by default and `--user` to the home scope (FR-012b), reporting exactly what it wrote and where (FR-016); a second install is an **idempotent no-op** (FR-013, SC-006); a **hand-edited** definition is **refused** with the difference reported, never overwritten (FR-014); `remove` leaves **no residue** (FR-015, SC-007); an absent/unsupported agent config **refuses** naming what was sought and where (FR-018).
- [ ] T021 [US3] Add the `skill install|update|remove` command to `bin/agent-container`: the four **SkillTarget** discovery paths (project + user per agent — a target is only a path, since all four consume the same standard format, FR-017); checksum-in-frontmatter **drift detection** (research R7); and the report of what was written/changed/removed.

**Checkpoint**: an agent gains a documented, standard-conformant way to invoke the tool, installed safely and reversibly.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T022 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell) and fix all findings; keep `emit_json`, `context` and the skill installer within xenon rank B (extract helpers rather than growing one branchy function).
- [ ] T023 [P] Add `docs/agent-interface.md`: how an agent drives the tool (the envelope + its compatibility rules, the failure contract and code set, `context`, `skill`), and **what is not promised** (human output is unstable; no API/daemon; no autonomous action).
- [ ] T024 [P] Update `README.md` and the `CLAUDE.md` Decisions bullet: the `--json` surface, the versioned envelope, structured failures, `context`, and the standard-conformant `skill` command — within the CLAUDE.md 2000-token budget (prune before adding).
- [ ] T025 Run quickstart.md Scenarios A–G and record the results in quickstart.md (A needs a local runtime; B–E need none; F uses a scratch agent config — **never** the operator's real one).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → the test module. Blocks the envelope tests.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (the envelope, the emitter, the failure descriptor).
- **US1 (P3)** → depends on Foundational. **The MVP.**
- **US2 (P4)** → depends on Foundational for the envelope; independent of US1's per-command work (it adds one new command).
- **US3 (P5)** → depends on Foundational; its content depends on **US1 existing in spirit** (the skill documents a `--json`-driven CLI, so shipping it before US1 would document a surface that is not there).
- **Polish (P6)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation task (single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 `[P]`.
- Foundational: T002 ∥ T004 (tests); impl T003→T005 sequential.
- US1: T006 ∥ T008 ∥ T011 ∥ T012 ∥ T014 (tests, and T014 is a different module); impl T007→T009→T010→T013 sequential.
- US2: T015 ∥ T017; impl T016.
- US3: T018 ∥ T020; impl T019→T021 sequential.
- Polish: T023 ∥ T024; T022/T025 sequential (gate, then record).

## Implementation Strategy

### MVP first (US1 — the agent-drivable CLI)

1. Phase 1 Setup → 2. Phase 2 Foundational (envelope + emitter + failure descriptor) → 3. Phase 3 US1 (`--json` everywhere, non-blocking refusals, failure codes, machine-readable help) → **STOP & VALIDATE** an agent completes a lifecycle on machine-readable output alone, every defined failure is actionable, **no secret appears in any payload**, and the Feature 005 eval contract is intact (quickstart A/B/C) → ship. This alone makes the existing 23 commands agent-operable.

### Incremental delivery

US2 (`context`) is a small serializer over an existing pure engine and can land immediately after the MVP. US3 (`skill`) is the distribution mechanism and lands last, because it documents the surface US1 creates. Polish (gate, docs, quickstart run) closes the feature.
