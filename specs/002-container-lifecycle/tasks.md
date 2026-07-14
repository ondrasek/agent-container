---
description: "Task list for Container Lifecycle Engine (specs/002, net-new scope)"
---

# Tasks: Container Lifecycle Engine (net-new verbs on a configured host)

**Input**: Design documents from `specs/002-container-lifecycle/` (plan.md, spec.md, research.md, data-model.md, contracts/cli-commands.md, quickstart.md).

**Scope**: ONLY the net-new work vs Feature 001 (shipped 0.5.0). Inherited and NOT re-planned: `up` (deploy + idempotent reconcile), `down` (dispose), `down --purge` (dispose+volumes), `logs`, the local view of `list`, per-host deterministic identity, build-on-host, `wait_port_released`, injected identity as compose configs, attach. Tasks below reference those, they do not rebuild them.

**Tests**: INCLUDED (Constitution V; the existing `bin/tests/` suite; plan's explicit test changes).

## ⚠️ Single-file constraint (read before using [P])

The whole CLI is **one file**: `bin/agent-container` (PEP 723). Per the plan's Structure Decision it stays one file. Therefore **implementation tasks that edit `bin/agent-container` are mutually SEQUENTIAL** — never `[P]` with each other (same-file conflict). `[P]` is used ONLY for genuinely separate files: distinct test modules and docs.

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [X] T001 [P] Add `bin/tests/test_lifecycle.py` (new module) with hermetic fixtures for the deployment lock and the reconcile helper (reuse the `wiz`/`make_registry` fixtures from `bin/tests/conftest.py`; no live runtime).

**Checkpoint**: a place for lock + reconcile unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared net-new engine every lifecycle verb consumes — a per-deployment lock (FR-017) and the compose-subcommand argv builders. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]`.

### Deployment lock (data-model: Deployment lock; R6)

- [X] T002 [P] Write failing tests for the deployment lock in `bin/tests/test_lifecycle.py`: a held `(host,name)` lock refuses a second acquire with a clear message (`fcntl.LOCK_NB`), independent `(host,name)` pairs do not contend, and the lock releases on context exit.
- [X] T003 Implement `deployment_lock(host, name)` — a context manager over `fcntl.flock(LOCK_EX|LOCK_NB)` on `$XDG_STATE_HOME/agent-container/<host>/<name>.lock`, failing fast (Fatal) on contention — in `bin/agent-container`.

### Driver argv for the new verbs (contracts/cli-commands.md; R1/R2/R3)

- [X] T004 [P] Write failing argv tests in `bin/tests/test_command_construction.py`: `driver_stop_argv`/`driver_start_argv` emit `<rt> --context H compose -p … -f … stop|start`; `driver_redeploy_argv` emits `… up -d --build --force-recreate`; `driver_down_argv(..., rmi_local=True)` adds `--rmi local` to the existing down argv.
- [X] T005 Implement `driver_stop_argv`, `driver_start_argv`, `driver_redeploy_argv`, and extend `driver_down_argv` with an `rmi_local: bool` parameter, in `bin/agent-container` (alongside the existing `driver_up_argv`/`driver_down_argv`).

**Checkpoint**: lock + driver argv builders exist and are unit-tested. User stories can begin.

---

## Phase 3: User Story 2 — Control across persistence levels (Priority: P1) 🎯 core net-new MVP

**Goal**: pause/reclaim (`stop`/`start`), image-aware `redeploy` (rebuild + recreate, volumes preserved), and `wipe` (container + volumes + built image, confirmed). This is the genuine net-new MVP — the lifecycle verbs 001 did not ship.

**Independent Test**: on a reachable host, `up alpha` → `stop alpha` (Exited, volumes intact) → `start alpha` (running, no recreate) → rebuild image → `redeploy alpha` (new image, same volumes) → `wipe alpha` (prompts; on confirm container+volumes+image gone). Quickstart Scenarios A, C, D.

- [X] T006 [P] [US2] Write failing tests in `bin/tests/test_command_construction.py` / `test_lifecycle.py`: `do_stop`/`do_start` build the compose stop/start argv; `do_redeploy` regenerates the compose file and builds the force-recreate argv; `do_wipe` requires TTY/`-y` confirmation (non-TTY without `-y` → exit 2) and issues `down --volumes --rmi local`.
- [X] T007 [US2] Implement `do_stop` and `do_start` (compose stop/start under `deployment_lock`; no-op-safe; `start` on a disposed deployment errors actionably → suggest `up`) + Typer `stop`/`start` commands, in `bin/agent-container`.
- [X] T008 [US2] Implement `do_redeploy` — regenerate the compose file from current inputs, run `driver_redeploy_argv` (up -d --build --force-recreate, volumes preserved), report the reattach address/port — + Typer `redeploy` command (accepts `--env-file`/`--mount` like `up`), in `bin/agent-container`. `redeploy` is **deliberately non-idempotent** (I1): it always rebuilds + recreates even with no change, and MAY log a "no change detected — rebuilding anyway" warning; the idempotent no-op path stays `up` (FR-010).
- [X] T009 [US2] Implement `do_wipe` — TTY/`-y` confirmation idiom (mirroring `cli_down`/`host rm --destroy`), `driver_down_argv(..., rmi_local=True)`, clear per-`(host,name)` state — + Typer `wipe` command, in `bin/agent-container`.
- [X] T010 [US2] Take `deployment_lock` in every mutating verb (`do_up`, `down_container`/`cli_down`, `do_stop`, `do_start`, `do_redeploy`, `do_wipe`); read-only `list`/`logs` MUST NOT lock, in `bin/agent-container`.
- [X] T011 [P] [US2] Acceptance in `bin/tests/test_acceptance.py`: `up`→`stop`→`start`→ (**SC-003**) `down` (dispose) then `up` restores prior config from the retained volumes →`redeploy` (change the image; assert the 7 volumes are the SAME ones and the new image runs)→`wipe -y` (assert container + volumes + built image gone); plus a concurrency check (a second mutating op while one holds the lock is refused, **FR-017**).

**Checkpoint**: the three persistence levels work end-to-end — the shippable net-new increment.

---

## Phase 4: User Story 1 — Deploy and reach isolated containers (Priority: P1)

**Goal**: mostly **inherited** from 001 (`up` + idempotent reconcile + isolated per-container identity). Net-new here is only the lock wiring (done in T010) and confirming idempotency/isolation still hold with the new verbs present.

**Independent Test**: `up alpha`; `up alpha` again unchanged → idempotent no-op; `up beta` on the same host → both run isolated. Quickstart Scenario B (dispose→recreate non-event, inherited).

- [X] T012 [P] [US1] Add a regression test (extend `bin/tests/test_command_construction.py`): a second `up` of an unchanged deployment is an idempotent no-op (no `--force-recreate`), and two distinct names produce non-colliding project/port/volume argv — guarding that the new verbs did not perturb inherited deploy.
- [X] T013 [US1] Verify `do_up`'s inherited idempotent-reconcile path and ensure it now acquires `deployment_lock` (T010) without changing the no-op semantics, in `bin/agent-container`.

**Checkpoint**: inherited deploy + idempotency intact under the new lock; distinct containers isolated.

---

## Phase 5: User Story 3 — Live state and logs by querying the host (Priority: P2)

**Goal**: `list` reads **live host state** and reconciles it — the T030 deferred from 001 US3 — so status is truthful after a reboot/crash/out-of-band change; a `--local` flag keeps the fast local-only view. `logs` is inherited.

**Independent Test**: `up beta`; out-of-band `docker --context H stop agent-container-beta` (or reboot); next `list` shows beta stopped (real host state); `list --local` is the fast path; a dead host shows `unreachable`, never hangs. Quickstart Scenario E.

- [X] T014 [P] [US3] Write failing tests in `bin/tests/test_lifecycle.py`: `gather_rows` reconciles each registered host via a (mocked) `host_ps_rows`, keys rows by `(host, cname)` (no duplicate of a state-file placeholder + its live row), marks a host whose `ps` raised as `unreachable` (not dropped, not running), and `--local` skips the remote round-trips.
- [X] T015 [US3] Extend `gather_rows` to iterate `registry_hosts(load_registry())`, call `host_ps_rows(h)` (which `ensure_tunnel`s a provisioned host) wrapped in `except (Fatal, OSError, subprocess.SubprocessError)` per host, reconcile against per-host `*.port` state keyed by `(host, cname)`; add a `--local` option to `list`/`do_list`; update the `gather_rows` docstring (it no longer defers remote reconciliation), in `bin/agent-container`.
- [X] T016 [P] [US3] Acceptance in `bin/tests/test_acceptance.py`: deploy, stop the container out-of-band on the host, assert the next `list` reflects the real (stopped) state and recomputes identity from the name; assert a registered-but-unreachable host renders `unreachable` and does not hang the listing.

**Checkpoint**: status is truthful live; the stale-local-record failure mode is closed.

---

## Phase 6: User Story 4 — Sidecar / helper services (Priority: P3)

**Goal**: a deployment may declare helper services (compose override file) that share its lifecycle; every verb acts on the agent + helpers as one unit (R5).

**Independent Test**: declare `agent-container.gamma.services.yaml` with a `cache` helper; `up gamma` starts both; `stop`/`start`/`wipe` act on both; the agent reaches the helper. Quickstart Scenario F.

- [X] T017 [P] [US4] Write failing tests in `bin/tests/test_command_construction.py`: an override file is discovered (`./agent-container.<name>.services.yaml` → `~/.config/agent-container/<name>.services.yaml`), passed as a second `-f` after the generated compose file on every compose invocation, and rejected (Fatal) when it is not a services-only mapping or redefines the agent service's identity fields.
- [X] T018 [US4] Implement `resolve_sidecar_override(name)` (discovery + parse-validation) and thread the second `-f` through the shared compose-invocation path (`driver_compose_argv`) so `up`/`stop`/`start`/`redeploy`/`down`/`wipe` all include it, in `bin/agent-container`.
- [X] T019 [P] [US4] Acceptance in `bin/tests/test_acceptance.py`: deploy a container with a helper (e.g. a tiny public image); assert both start together, `stop`/`start`/`wipe` act on the unit (no orphaned helper), and the agent can reach the helper by service name.

**Checkpoint**: sidecars share the deployment lifecycle; the file-based seam is in place for Feature 006 to build on.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T020 [P] Update `README.md`: `stop`/`start`/`redeploy`/`wipe`, `list --local`, sidecar override file, live-reconcile behavior (FR-019).
- [X] T021 [P] Update `CLAUDE.md` Decisions (net-new verbs, live-reconcile, sidecars) within the 2000-token budget — prune before adding (FR-019).
- [X] T022 Run `scripts/quality-gate.sh` (ruff · ty · bandit · self-test · pytest · shell suites) and fix all findings.
- [X] T023 Run quickstart.md Scenarios A–G (local runtime) + the new acceptance tier; record results.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (lock + driver argv).
- **US2 (P3)** → depends on Foundational. **The core net-new MVP.**
- **US1 (P4)** → depends on Foundational + T010 (lock wiring); mostly inherited verification.
- **US3 (P5)** → depends on Foundational; independent of US2/US1 (touches `gather_rows`, not the verbs).
- **US4 (P6)** → depends on Foundational; extends the shared compose-invocation path used by all verbs, so best applied after US2 exists.
- **Polish (P7)** → after the desired stories.

> Unlike a greenfield feature, US1 is **near-empty** (001 already ships it) and US2 is the genuine MVP. US3 (live reconcile) and US4 (sidecars) are independent increments on the foundational engine.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation tasks.
- `bin/agent-container` edits are strictly ordered (same file).

### Parallel opportunities (distinct files only)

- Setup: T001 alone.
- Foundational: T002 ∥ T004 (different test modules); impl T003 → T005 sequential (same file).
- US2: T006 (tests) ∥ T011 (acceptance) authored alongside; T007→T008→T009→T010 sequential.
- US3: T014 ∥ T016; T015 sequential.
- US4: T017 ∥ T019; T018 sequential.
- Polish: T020 ∥ T021.

## Implementation Strategy

### MVP first (US2 — the net-new lifecycle)

1. Phase 1 Setup → 2. Phase 2 Foundational (lock + driver argv) → 3. Phase 3 US2 (stop/start/redeploy/wipe) → **STOP & VALIDATE** the three persistence levels (quickstart A/C/D) → ship. This alone delivers the lifecycle control 001 lacked.

### Incremental delivery

- US2 (MVP: pause/redeploy/wipe) → US1 (confirm inherited + lock) → US3 (live reconcile — closes the stale-record hole) → US4 (sidecars) → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential (single-file contract).
- **Zero new Python dependencies** — new verbs are compose argv + stdlib `json` + stdlib `fcntl`; verify no import creep in T022.
- Identity is **recomputed from the name** in every verb (FR-012); `list` lets the live host win (FR-011). Never trust a stored identity/state as authoritative.
- The wipe confirmation (FR-009) and the lock refusal (FR-017) are safety properties — assert them in T006/T011.
- **FR-018 (clear diagnostics, no partial/hung state)** is cross-cutting: every new verb (T007-T009, T015, T018) must `die()` with an actionable message on an unreachable host / invalid override / lock contention rather than partial state — checked in the unit tests (T006/T014/T017) and the gate (T022), not a standalone task.
- Commit after each task or logical group; keep `main` green (Constitution VII). Acceptance runs outside the gate (T023, tokened variants opt-in).
