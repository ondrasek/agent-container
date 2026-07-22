---
description: "Task list for Agent Execution & Session Management (specs/004)"
---

# Tasks: Agent Execution & Session Management

**Input**: Design documents from `specs/004-agent-execution/` (plan.md, spec.md, research.md, data-model.md, contracts/execution.md, quickstart.md).

**Scope**: *what runs inside the container and how the operator interacts with it* — interactive vs headless execution, detach/reattach, workspace modes (persistent/bind/ephemeral), and clone-on-start. **Inherited** (not rebuilt): hosts + the compose run mechanism + restart-on-crash (001/002), attach transport + the six non-workspace volumes + the name/port identity (Constitution IV), and the git credentials + `injected_configs` seam (003).

**Tests**: INCLUDED (Constitution V; the existing `bin/tests/` suite — Python unit + shell suites + acceptance).

## ⚠️ Single-file constraint (read before using [P])

Two files carry almost all implementation: the CLI **`bin/agent-container`** (one PEP 723 file) and the container **`entrypoint.sh`** (one bash file). Tasks that edit **the same file are mutually SEQUENTIAL** — never `[P]` with each other. `[P]` is used ONLY for genuinely separate files: distinct test modules (`test_execution.py`, `test_command_construction.py`, the shell suites, `test_acceptance.py`) and docs.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [ ] T001 [P] Add `bin/tests/test_execution.py` (new module) with hermetic fixtures for the compose-model / flag assertions (reuse the `wiz`/`make_registry` fixtures from `bin/tests/conftest.py`; no live runtime).

**Checkpoint**: a place for the execution-mode/workspace unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared net-new plumbing every story consumes — a parameterized `restart`, the workspace-mode mount + conditional workspace volume, and the mode/agent/repo/task delivery into the compose model. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]`.

- [ ] T002 [P] Write failing tests in `bin/tests/test_execution.py` / `bin/tests/test_command_construction.py`: `build_compose_model` accepts a `restart` value and emits it (default `unless-stopped`); a workspace mode selects the right `/workspace` mount (persistent named volume / local bind / **omitted** for ephemeral); the workspace volume appears in `volumes:` ONLY for persistent; `mode`/`agent`/`repo` land in the service `environment`; a task rides `injected_configs` at an ephemeral `/run` target (never argv/inlined). **FR-016**: mode and workspace are **independently selectable** — assert each execution mode × each workspace mode (e.g. `headless`×`persistent`, `interactive`×`ephemeral`) builds a coherent model with **no silent alteration** of either axis.
- [ ] T003 Parameterize `restart` in `build_compose_model(...)` (replace the hardcoded `"unless-stopped"` with a param, default `unless-stopped`), in `bin/agent-container`.
- [ ] T004 Add workspace-mode resolution: a `resolve_workspace(mode, dir, host)` helper returning the `/workspace` mount (persistent named volume / `<local-abs>:/workspace` bind / **none** for ephemeral); a **bind on a non-local host is refused** with a clear message (FR-011); wire the mount into `build_compose_model` and make the workspace named volume **conditional** in the model `volumes:` + `per_container_volumes` (purge tolerant), in `bin/agent-container`.
- [ ] T005 Thread `mode`/`agent`/`repo` into the service `environment` (`AGENT_CONTAINER_MODE`/`AGENT_CONTAINER_AGENT`/`AGENT_CONTAINER_CLONE_URL`) and deliver the initial `task` as an injected file (`injected_configs`, ephemeral `/run/agent-container/task`); set `restart` per mode (`unless-stopped` interactive / `on-failure` headless) — in `build_compose_model`/`compose_up_exec`, in `bin/agent-container`. **NOTE:** the clone-URL env is `AGENT_CONTAINER_CLONE_URL` — **not** `AGENT_CONTAINER_REPO`, which already denotes the CLI's host-side build-context override (`bin/agent-container` / `test_packaging.py`); the two must not collide.

**Checkpoint**: the compose model expresses mode/restart/workspace/agent/repo/task and refuses a remote bind. User stories can begin.

---

## Phase 3: User Story 1 — Interactive agent over SSH+tmux (Priority: P1) 🎯 MVP

**Goal**: run the chosen agent in a persistent tmux session the operator attaches to; optionally seed an initial task. The canonical, human-in-the-loop use.

**Independent Test**: `up --mode interactive --agent claude`; attach → an interactive agent session; a second deployment with `--task` begins it without an attach (quickstart A).

- [ ] T006 [P] [US1] Write failing tests in `bin/tests/test_execution.py`: `up`'s `--mode`/`--agent`/`--task` thread into the compose env + the task inject; interactive sets `restart: unless-stopped`.
- [ ] T007 [US1] Add `--mode`/`--agent`/`--task` options to `up` (and `redeploy`), resolve `@file` for `--task`, and thread through `do_up`/`do_redeploy` → `compose_up_exec` → `build_compose_model`, in `bin/agent-container`.
- [ ] T008 [US1] In `entrypoint.sh`, branch on `AGENT_CONTAINER_MODE` (default interactive = the existing sshd+tmux flow) and, in interactive mode, **launch `AGENT_CONTAINER_AGENT` in a dedicated tmux window** seeded with the injected task if present (per-agent invocation map: claude/codex/pi); PID 1 stays alive as today.
- [ ] T009 [P] [US1] Shell test in `bin/tests/test_entrypoint.sh`: with `AGENT_CONTAINER_MODE=interactive` + an agent + a task file, the agent is launched in a tmux window with the task; bare-shell windows still exist; no agent launched when `--agent`/task absent (backward-compatible default).
- [ ] T010 [P] [US1] Acceptance in `bin/tests/test_acceptance.py`: `up --mode interactive` → a tmux window running the agent process exists; a `--task` deployment shows the agent started on the task. (The agent actually *responding* — SC-001 — is the opt-in/tokened extension.)

**Checkpoint**: an interactive agent session runs and is attachable — the shippable MVP.

---

## Phase 4: User Story 2 — Detach / reattach without interrupting (Priority: P1)

**Goal**: the session survives disconnect; reattach from any machine lands on the same session; a dead session is reported, never a silent empty attach.

**Independent Test**: attach, start a long action, disconnect; confirm still running; reattach (incl. from another machine); attach to an ended session → clear report (quickstart B/C).

- [ ] T011 [P] [US2] Write failing tests in `bin/tests/test_execution.py` / `test_command_construction.py`: the attach path issues an explicit `tmux has-session -t main` probe and maps its result to (attach / fresh session / clear "nothing running") — never a silent empty attach.
- [ ] T012 [US2] Implement the dead-session probe in the attach path (`cli_attach`/`ssh_argv`/`wizard_handover`): before/at attach, check `tmux has-session -t main`; on a live session attach as today; on none, present a freshly (re)started session OR `die`/report "nothing running" clearly (FR-008); reattach stays machine-independent (FR-007), in `bin/agent-container`.
- [ ] T013 [P] [US2] Acceptance in `bin/tests/test_acceptance.py`: attach → detach (session persists) → reattach lands on the same `main` (SC-002/003); kill the session, then attach → a clear "nothing running"/fresh-session result, never a blank attach (FR-008); **restart the container (simulated crash) → reattach lands on a freshly started `main`, the prior session is NOT resumed (FR-009)** — distinct from detach/reattach, which preserves the session.

**Checkpoint**: detach/reattach preserves the running session; dead-session attach is never silent.

---

## Phase 5: User Story 3 — Headless disposable job (Priority: P2)

**Goal**: run the agent non-interactively as the container's workload; it exits with its result; a success is not resurrected; launchable foreground (stream) or detached (retrieve later).

**Independent Test**: foreground headless streams + ends with a result; detached returns immediately, output/result retrievable; success not auto-restarted (quickstart D/E).

- [ ] T014 [P] [US3] Write failing tests in `bin/tests/test_execution.py`: headless mode sets `restart: on-failure`; `up --foreground` builds the attached compose-up argv while detached builds `-d`; the headless agent invocation carries the task; **`--foreground` without `--mode headless` `die`s with a clear message (FR-017)** — `--foreground` is headless-only.
- [ ] T015 [US3] In `entrypoint.sh` (the headless branch of T008), run `AGENT_CONTAINER_AGENT`'s **non-interactive** form with the injected task as PID 1's workload and **exit with the agent's exit code** (FR-002); sshd/tmux not required for the run.
- [ ] T016 [US3] Add `--foreground` to `up` (headless): **reject `--foreground` unless `--mode headless` — `die` with a clear message (FR-017), it is headless-only**; a foreground launch runs `compose up` **attached** with `--abort-on-container-exit --exit-code-from agent` so the CLI's own exit status is the agent container's exit code (FR-002/SC-004) — otherwise `compose up` returns `0` regardless of the workload; detached stays `-d`; result = container exit code + `logs`; ensure `list` surfaces the exited status/code, in `bin/agent-container`. **Re-`up` of an exited headless deployment** reports the prior exited status/code and directs the operator to `redeploy` to re-run — it does **not** silently resurrect the finished job (`up` stays the running-deployment no-op; `redeploy` re-runs). **Sidecar caveat (002 US4):** `--abort-on-container-exit` stops **every** service in the project when **any** one exits, so a one-shot/crashing sidecar that exits before the agent finishes will SIGTERM the agent mid-run and `--exit-code-from agent` will then report that forced-stop code, not the true task result (SC-004). Document that a headless-foreground deployment's sidecars must be **long-lived** (not one-shot), and note the exit-code semantics under premature sidecar exit.
- [ ] T017 [P] [US3] Acceptance in `bin/tests/test_acceptance.py`: a headless run (use a trivial deterministic task/stub) **exits with a code** distinguishing success/failure (SC-004), is **not** auto-restarted on success, foreground streams + returns, detached returns immediately with `logs`/result retrievable (SC-005).

**Checkpoint**: headless runs to completion with a retrievable result and no resurrection on success.

---

## Phase 6: User Story 4 — Workspace modes + clone-on-start (Priority: P2)

**Goal**: select persistent/bind/ephemeral workspace; populate persistent/ephemeral from a repo on start (layered credential by URL scheme); bind is local-only; durability is explicit.

**Independent Test**: persistent survives recreate; bind edits appear locally + remote-bind refused; ephemeral gone after teardown; clone-on-start populates or fails fast (quickstart F/G/H).

- [ ] T018 [P] [US4] Write failing tests in `bin/tests/test_execution.py`: `--workspace persistent|bind|ephemeral` resolves the right mount (T004) and a **bind on a non-local host is refused** (FR-011); an SSH-URL `--repo` with **no** push key dies before compose (FR-014); an HTTPS `--repo` needs no push key; **the workspace mode is orthogonal to `--mode` (FR-016)** — a bind/ephemeral/persistent workspace pairs with either execution mode without silently altering the other.
- [ ] T019 [US4] Add `--workspace`/`--workspace-dir`/`--repo` to `up`/`redeploy`, wire workspace resolution (T004) + the clone-credential fail-fast pre-check (SSH-URL repo requires an injected push key, FR-014) before `compose up`, in `bin/agent-container`.
- [ ] T020 [US4] Add **clone-on-start** to `entrypoint.sh`: for persistent/ephemeral with `AGENT_CONTAINER_CLONE_URL` set and `/workspace` empty, `git clone` choosing the credential by URL scheme (`git@…` → the injected push key via `core.sshCommand`; `https://…` → `GH_TOKEN`); `die` on an SSH URL with no key (FR-014); **idempotent** (skip if a working copy exists); a bind workspace is never cloned; runs BEFORE the agent launch (T008/T015).
- [ ] T021 [US4] Surface the ephemeral **durability warning** (FR-015) at deploy (a clear NOTE that uncommitted ephemeral work is lost on teardown), in `bin/agent-container` (and/or entrypoint log).
- [ ] T022 [P] [US4] Acceptance in `bin/tests/test_acceptance.py`: persistent retains its working copy across recreate (SC-006); bind edits appear on the local FS and a remote bind is refused (SC-007); ephemeral is gone after teardown (SC-006); clone-on-start populates `/workspace` (HTTPS) and fails fast on an SSH URL with no key (SC-008).

**Checkpoint**: all three workspace modes behave per durability; clone-on-start populates or fails fast.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T023 [P] Update `README.md`: execution modes (interactive/headless, `--mode`/`--agent`/`--task`/`--foreground`), detach/reattach + dead-session behavior, workspace modes + `--workspace`/`--repo`, clone-on-start (FR-018).
- [ ] T024 [P] Update `CLAUDE.md` Decisions (execution modes, workspace-mode + conditional workspace volume, clone-on-start) within the 2000-token budget — prune before adding (FR-018).
- [ ] T025 [P] Update the relevant `docs/` (e.g. a docs/execution.md or the existing docs) with the mode/session/workspace semantics + the ephemeral-durability caveat (FR-015/FR-018).
- [ ] T026 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell suites) and fix all findings.
- [ ] T027 Run quickstart.md Scenarios A–H (local + the opt-in/tokened agent-responds ones) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (restart param + workspace-mode mount + mode/agent/repo/task delivery).
- **US1 (P3)** → depends on Foundational. **The MVP** (interactive session).
- **US2 (P4)** → depends on US1 (a session to detach/reattach from); adds the dead-session probe.
- **US3 (P5)** → depends on Foundational; independent of US1/US2 (the headless branch of the same mode switch).
- **US4 (P6)** → depends on Foundational; independent of the execution-mode stories (workspace mount + clone-on-start).
- **Polish (P7)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` / `entrypoint.sh` implementation tasks (each file is single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 alone.
- Foundational: T002 (tests) authored alongside; impl T003→T004→T005 sequential (same file).
- US1: T006 ∥ T009 ∥ T010 (distinct test files); impl T007 (CLI) → T008 (entrypoint).
- US2: T011 ∥ T013; impl T012.
- US3: T014 ∥ T017; impl T015 (entrypoint) → T016 (CLI) — different files but T016 depends on T015's contract, so ordered.
- US4: T018 ∥ T022; impl T019 (CLI) → T020 (entrypoint) → T021 (CLI).
- Polish: T023 ∥ T024 ∥ T025.

## Implementation Strategy

### MVP first (US1 — interactive agent session)

1. Phase 1 Setup → 2. Phase 2 Foundational (restart + workspace + delivery) → 3. Phase 3 US1 (mode branch + agent-in-tmux + task) → **STOP & VALIDATE** attach to a running interactive agent (quickstart A) → ship. This alone delivers the canonical human-in-the-loop use.

### Incremental delivery

- US1 (interactive, MVP) → US2 (detach/reattach + dead-session) → US3 (headless) → US4 (workspace modes + clone-on-start) → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential, and every `entrypoint.sh` edit is sequential (single-file contracts).
- **Zero new Python dependencies** — modes are compose env/restart/mounts + the baked agents + stdlib (verify no import creep in T026).
- **Identity refinement (Constitution IV)**: the workspace named volume is conditional (persistent only); the other six volumes + name/port are unchanged, and default/pre-004 deployments stay persistent → no migration. `--purge`/`wipe` tolerate the volume's absence (assert in T004/T018).
- **Clone-on-start credential is layered by URL scheme** (operator-confirmed): `git@…` → push key (fail-fast if missing, FR-014); `https://…` → `GH_TOKEN` (always present).
- **Fail-fast diagnostics (FR-017)** are cross-cutting: bind-on-remote (T004/T019), missing clone credential (T019/T020), dead-session reattach (T012) — asserted in the unit/shell/acceptance tiers, not a standalone task.
- The **agent-actually-responds** acceptance (SC-001) and any headless run needing a real model call are **opt-in/tokened**, outside the CI cost boundary (no cost/secret in CI). Mechanism tests use a trivial/stub task where a real agent is not needed.
- Commit after each task or logical group; keep `main` green (Constitution VII).
