---
description: "Task list for Multi-Host Deployment (specs/001)"
---

# Tasks: Multi-Host Deployment (named hosts, drivers, provisioners, compose run)

**Input**: Design documents from `specs/001-multi-host-deployment/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md — all present.

**Tests**: INCLUDED. Not optional for this project — Constitution V (validation-first, inverted pyramid), the existing `bin/tests/` suite, and the plan's explicit test changes (compose-file content replacing `docker run` argv assertions; registry/identity/provisioner units; acceptance scenarios) make them part of the deliverable.

## ⚠️ Single-file constraint (read before using [P])

The whole CLI is **one file**: `bin/agent-container` (1631 lines, PEP 723). Per the plan's Structure Decision it stays one file (the wheel `force-include` maps it to `agent_container/__init__.py`). Therefore **implementation tasks that edit `bin/agent-container` are mutually SEQUENTIAL** — they are never marked `[P]` with each other (same-file conflict). `[P]` is used ONLY for genuinely separate files: distinct test modules, the two completion scripts, and docs. This is the honest application of "avoid same-file conflicts."

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] Write ADR `docs/decisions/0002-host-driver-provisioner-and-compose-run.md` capturing research decisions R1–R8 (docker-context universal runtime, compose-as-JSON, hosts.json registry, Hetzner-via-urllib, secrets/configs injection, per-host identity, remote build, safe teardown).
- [X] T002 [P] Add hermetic fixtures in `bin/tests/conftest.py`: a temp `XDG_STATE_HOME`/`XDG_CONFIG_HOME` home and a fake-registry factory, so registry/identity/compose unit tests never touch the real config/state.

**Checkpoint**: ADR recorded; test harness can isolate config/state.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the driver/registry/compose/identity engine every user story consumes. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]` (distinct files).

### Host registry (data-model: Host, Host Registry)

- [X] T003 [P] Write failing unit tests for the host registry (round-trip, atomic temp+`os.replace` write, `default` resolution, legacy `hosts.conf`→`existing-ssh` synthesis, no file eval) in `bin/tests/test_registry.py`.
- [X] T004 Implement the `Host` record + `hosts.json` load/save (atomic write, `version`, `default`, per-`data-model.md` schema) in `bin/agent-container`.
- [X] T005 Implement read-only legacy `hosts.conf` → `existing-ssh` Host synthesis (deprecation window) in `bin/agent-container`.

### Per-host identity + migration (data-model: Deployment identity; R6)

- [X] T006 [P] Extend `bin/tests/test_pure_logic.py` with failing tests: per-host state paths `<state>/<host>/<name>.*`, flat→`local/` migration, and that `container_name`/`port_for_name`/volume-name **values are unchanged** for an existing name (stable contract).
- [X] T007 Namespace runtime state per host (`state_file` and the SSH-staging paths become `<host>/<name>.*`) and implement the one-time flat→`local/` migration in `bin/agent-container`.

### Driver seam (contracts/driver.md)

- [X] T008 [P] Extend `bin/tests/test_command_construction.py` with failing tests for driver argv builders: `runtime_argv`/`compose_argv`/`up_argv`/`down_argv` for `DockerContextDriver`, `PodmanConnectionDriver`, and `ExistingSshDriver` (deploy rejected, attach allowed).
- [X] T009 Implement the Driver seam (`runtime_argv`, `compose_argv`, `up_argv`, `down_argv`, `reachable_address`, `capability_check`, `ps_on_host`) with the three driver kinds in `bin/agent-container`.

### Compose generation (data-model: Generated Compose Model; R2, R5)

- [X] T010 [P] Write failing unit tests for the compose builder in `bin/tests/test_compose.py`: JSON-as-YAML output is deterministic, declares the 7 volumes, maps host key→`secrets` and authorized_keys→`configs`, and contains **no inline secret** (only `file:` refs).
- [X] T011 Implement the compose-model builder + JSON writer to `<state>/<host>/<name>.compose.yaml` (services/volumes/secrets/configs, `restart: unless-stopped`, `build.context`) in `bin/agent-container`.

**Checkpoint**: registry, per-host identity, driver seam, and compose generation exist and are unit-tested. User stories can begin.

---

## Phase 3: User Story 1 — Deploy and attach on a named local host (Priority: P1) 🎯 MVP

**Goal**: register a local docker/podman host, deploy a container via generated compose, attach over SSH+tmux, tear down keeping volumes — replacing the imperative `docker run` path.

**Independent Test**: `host add local … --default` → `up alpha` → `attach alpha` (tmux) → detach → `down alpha` → immediate `up alpha` (no stale-port failure), all local (quickstart Scenario A).

- [X] T012 [P] [US1] Write failing CLI test: `host add --driver docker --docker-context <ctx> --default` writes `hosts.json`, `host ls` shows it as default, in `bin/tests/test_host_cli.py`.
- [X] T013 [P] [US1] Rewrite `bin/tests/test_command_construction.py` deploy assertions: `up alpha` generates the compose file (7 volumes + secrets/configs) and invokes `<rt> --context <ctx> compose -p agent-container-alpha up -d --build` — **replacing** the old `docker run` argv assertions.
- [X] T014 [US1] Implement `host add` for local `docker`/`podman` (with `--docker-context`/`--connection`, `--default`, `capability_check` at registration) in `bin/agent-container`.
- [X] T015 [US1] Rewrite `do_up`/`launch_container` to resolve the target Host, generate compose (T011), and run `up_argv` on the host; report reachable address+port; in `bin/agent-container`.
- [X] T016 [US1] Move SSH identity injection from bind mounts to compose injected material (update `resolve_ssh_injection`). NOTE: both the host key AND authorized_keys ship as compose **`configs`** (0644), not `secrets` — a compose `secret` with an absolute `target` crash-loops the container on some daemons, and secret files staged 0600 are unreadable by the container's `dev` uid (host uid ≠ container uid). See R5 / `contracts/provisioner.md`; this deviates from FR-015's "host key as secret" for portability. In `bin/agent-container`.
- [X] T017 [US1] Rewrite `down_container` to `compose down` (keep the 7 volumes; `--purge`→`--volumes`) then `wait_port_released` before returning, in `bin/agent-container`.
- [X] T018 [US1] Make `attach` host-address-aware (resolve `Host.address`; local→localhost; `existing-ssh` legacy fallback) in `bin/agent-container`.
- [X] T019 [US1] Implicit-local upgrade: a bare `up`/`down`/`attach` with no registered hosts assumes a `local` docker host from `detect_runtime()` and tells the operator, in `bin/agent-container`.
- [X] T020 [P] [US1] Update shell completions to offer `host` subcommands and read `--host` values from `hosts.json`, in `completions/agent-container.bash` and `completions/agent-container.zsh`.
- [X] T021 [P] [US1] Add local acceptance scenario (register→up→attach→detach→down→immediate re-up; assert compose file content + volumes retained + no stale port) in `bin/tests/test_acceptance.py`.

**Checkpoint**: local deploy works end-to-end via compose — the shippable MVP.

---

## Phase 4: User Story 2 — Provision a fresh cloud host and deploy to it (Priority: P2)

**Goal**: register a Hetzner host with `--create`, provision a server (cloud-init installs docker), build the image on the server, deploy, attach over the public address.

**Independent Test**: (tokened, opt-in) `host add hz1 --provider hetzner --create …` → `up beta --host hz1` (image built on server) → `attach beta --host hz1` → `down` (quickstart Scenario C). Depends on US1's deploy path existing.

- [X] T022 [P] [US2] Write failing provisioner tests in `bin/tests/test_provisioner.py`: token never on argv (passed via urllib headers), `create` returns a `docker`-driver Host with `created_by_tool=true`, and `cleanup_on_failure` runs on post-allocation failure.
- [X] T023 [US2] Implement the Hetzner provisioner (stdlib `urllib` REST: create/destroy; docker-only cloud-init user-data; root authorized via the Hetzner **ssh_keys API** — cloud-init's `ssh_authorized_keys` does not on this image — with **both** a tool-generated file-based **automation key** and the operator key; readiness polled over an **ssh `-L` socket-forward**) in `bin/agent-container`.
- [X] T024 [US2] Wire `host add --provider hetzner` with `--create`/`--reuse`/`--server-type`/`--location`/`--ssh-key` to the provisioner; register the resulting Host; on failure invoke cleanup and report (no orphaned billable server), in `bin/agent-container`.
- [X] T025 [US2] Deploy path builds on the remote over the provisioned host's docker context (no local image transfer). NOTE: the context targets a local `unix://<sock>` bridged to the remote daemon by an ssh `-L` socket-forward using the automation key (not a bare `ssh://` context) — so it authenticates unattended regardless of the operator's `~/.ssh/config`/agent; in `bin/agent-container` (`do_up` build path).
- [X] T026 [P] [US2] Add opt-in tokened acceptance (marker-gated, never CI): provision→docker/compose reachable over a fresh socket-forward→destroy (host-add success proves reachability), plus the partial-failure cleanup path, in `bin/tests/test_acceptance.py`. **Validated live** against a real Hetzner cpx22/hel1 server (0.4.0).

**Checkpoint**: one flow yields an attachable cloud agent; image built remotely; identity transferred via secrets/configs.

---

## Phase 5: User Story 3 — Manage the host registry and tear down safely (Priority: P3)

**Goal**: list/inspect/remove hosts; keep server lifecycle distinct from container lifecycle; refuse to destroy a server that still hosts containers; never destroy infrastructure not created by the tool.

**Independent Test**: two containers on one host → `host rm --destroy` refused → `down` one → server + sibling intact → `host rm --destroy` succeeds when empty (quickstart Scenario D). Depends on US1 (deploy) and US2 (a cloud host to destroy).

- [X] T027 [P] [US3] Write failing tests in `bin/tests/test_host_cli.py`: `host rm --destroy` refused while containers remain, `existing-ssh`/`--reuse` host never destroys a server, and registration-only `host rm` leaves infrastructure untouched.
- [X] T028 [US3] Implement `host show` (--json) and registration-only `host rm` (repoints/nulls the default pointer; warns on a tool-created host) in `bin/agent-container`. (`host ls` already existed from US1.)
- [X] T029 [US3] Implement `host rm --destroy`: refuse unless `created_by_tool` + hetzner provider + **provably empty**, then deprovision. Hardened after adversarial review to be **fail-CLOSED** (`assert_host_empty`): a failed/unreachable `docker ps` refuses rather than being read as empty; `ensure_tunnel(required=True)`; `hetzner_delete_server(strict=True)` so a failed delete retains the registry entry (no orphaned server); unregister only after a successful deprovision. In `bin/agent-container`.
- [X] T030 [US3] `list`/`gather_rows` already shows the HOST column + per-host state rows. Live remote-daemon reconciliation (querying every host on each `list`) is **deferred to Feature 002 (container-lifecycle)** per gather_rows' own docstring — it would make `list` N remote round-trips with real latency/failure surface, out of scope for the US3 safety increment.
- [X] T031 [P] [US3] Acceptance in `bin/tests/test_acceptance.py`: real-container emptiness guard (two containers → destroy refused; down one → still refused; empty → guard releases, fails only at the token gate, no cloud call) + fail-closed-when-daemon-unreachable. Tokened real-deprovision left as an opt-in follow-up.

**Checkpoint**: fleet is manageable and teardown is safe; all three stories independently testable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T032 [P] Update `README.md`: host workflow (`host add/ls`), `--host`, Hetzner provisioning, compose run mechanism, `hosts.json` supersedes `hosts.conf`. (`host show/rm` deferred with US3.)
- [X] T033 [P] Update `CLAUDE.md` Decisions (host/driver/provisioner split, compose run, `hosts.json`) within the 2000-token project budget — prune before adding.
- [X] T034 Run `scripts/quality-gate.sh` (ruff · ty · bandit · pytest · shell suites) and fix all findings. (Gate green; enforced continuously via the Stop hook + CI.)
- [ ] T035 Run quickstart.md Scenarios A/B/E (local + inspection + multi-host no-collision) and the local acceptance tier; record results.
- [ ] T036 Retire the legacy `hosts.conf`-only code paths behind the deprecation note and reconcile any `orchestration/` quadlet references with the compose run path, in `bin/agent-container` and `orchestration/`.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all user stories**.
- **US1 (P3)** → depends on Foundational. The MVP.
- **US2 (P4)** → depends on Foundational **and US1** (reuses the deploy path; adds provisioning in front).
- **US3 (P5)** → depends on Foundational **and US1** (needs deployed containers to test teardown), **and US2** for real cloud deprovision (guard logic testable locally sooner).
- **Polish (P6)** → after the desired stories.

> Note: unlike the generic template, US2/US3 here are **not** independent of US1 — they build on the single deploy path. US1 is the genuine standalone MVP; US2/US3 are increments on it.

### Within a story

- Write the failing test task first (it targets a distinct file → `[P]`), then the sequential `bin/agent-container` implementation tasks.
- `bin/agent-container` edits are strictly ordered (same file).

### Parallel opportunities (distinct files only)

- Setup: T001 (docs) ∥ T002 (conftest).
- Foundational: the test tasks T003 ∥ T006 ∥ T008 ∥ T010 (different test modules) can be authored together; their impl tasks T004→T005→T007→T009→T011 are sequential (same file).
- US1: T012 ∥ T013 ∥ T020 ∥ T021 (distinct files); T014–T019 sequential.
- Polish: T032 ∥ T033 (different docs).

## Parallel Example: Foundational test authoring

```bash
# Distinct test modules — safe to write together (then watch them fail):
Task: "Registry tests in bin/tests/test_registry.py"          # T003
Task: "Per-host identity tests in bin/tests/test_pure_logic.py" # T006
Task: "Driver argv tests in bin/tests/test_command_construction.py" # T008
Task: "Compose builder tests in bin/tests/test_compose.py"     # T010
# Then implement T004→T005→T007→T009→T011 sequentially in bin/agent-container.
```

## Implementation Strategy

### MVP first (US1)

1. Phase 1 Setup → 2. Phase 2 Foundational (critical) → 3. Phase 3 US1 → **STOP & VALIDATE** local deploy/attach/teardown (quickstart A) → ship. This alone replaces the imperative run path with the compose engine and delivers named local hosts.

### Incremental delivery

- US1 (MVP, local compose deploy) → US2 (Hetzner provisioning) → US3 (registry mgmt + safe teardown) → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential (single-file contract).
- Zero new Python dependencies (stdlib `json` + `urllib`) — verify no import creep in T034.
- Secrets discipline (Constitution III) is a standing check: T016/T023 must keep keys/token off argv and out of the image (asserted in T013/T022).
- Commit after each task or logical group; keep `main` green (Constitution VII).
- Quality gate excludes the acceptance tier; run acceptance (T035, and tokened T026/T031) outside the gate.
