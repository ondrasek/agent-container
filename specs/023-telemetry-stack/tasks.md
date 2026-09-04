# Tasks: Telemetry stack container

**Feature**: `023-telemetry-stack` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Tests**: REQUESTED. The repository gates on `scripts/quality-gate.sh` and a CI-authoritative
acceptance tier, and this feature's own goal names real-agent validation. Test tasks are therefore
first-class, not optional.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelisable: touches different files and depends on nothing incomplete.
- **[US#]** — the user story a task serves. Setup, Foundational and Polish carry no story label.

## Path Conventions

Single-file CLI at `bin/agent-container`; tests in `bin/tests/`; completions in `completions/`;
docs in `docs/`. Everything is repository-root-relative.

**A note on `[P]` in this repository**: `bin/agent-container` is ONE file, so two tasks that both
edit it are not parallel however unrelated they look. `[P]` here mostly marks test files, completions
and docs, which are genuinely separate.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Add named defaults as module constants in `bin/agent-container`: `STACK_IMAGE_DEFAULT`, `STACK_READY_TIMEOUT` (180), `STACK_RETENTION_DAYS`, `STACK_RETENTION_SIZE`, `STACK_UI_PORT_BASE`, `STACK_OTLP_HTTP_PORT_BASE`, `STACK_OTLP_GRPC_PORT_BASE`, each with a comment naming what it defaults and why (Constitution VIII)
- [ ] T002 Add `KIND_TELEMETRY_STACK` and the kind vocabulary alongside `ROLE_AGENT`/`ROLE_CONTROL_PLANE` in `bin/agent-container`, plus `STACK_CONTAINER_PREFIX` derived from the existing prefix so `panic` and inventory reach it by the same rule (FR-001, FR-003)
- [ ] T003 [P] Record the environment-variable overrides for every T001 default in `docs/telemetry-stack.md` (new file, stub sections for now)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Blocking**: every user story depends on these. The two riskiest behaviours in the feature —
endpoint resolution and exposure — are proved here as pure functions, before any container exists.

- [ ] T004 Implement `stack_exposure_binds(level, driver)` in `bin/agent-container` returning the concrete bind addresses for `loopback` | `host` | `network`, per runtime (research R1, FR-018a); `host` MUST include the container-facing address, because a container cannot reach a service bound only to the host loopback
- [ ] T005 Implement `stack_container_endpoint(stack, driver)` in `bin/agent-container` returning the address an AGENT CONTAINER exports to — bridge gateway under docker, `host.containers.internal` under podman — and `stack_operator_url(stack)` for the human-facing one (FR-013, research R1)
- [ ] T006 [P] Unit-test exposure and endpoint resolution in `bin/tests/test_pure_logic.py`: every level × every driver, asserting `host` is reachable-from-containers, `loopback` is not routable, and that the container endpoint is NEVER an operator loopback address (the silent failure this feature exists to prevent)
- [ ] T007 Implement `validate_stack_name(name, host)` in `bin/agent-container` refusing a name already held by an agent environment or control plane on that host, naming the kind that holds it (FR-009a)
- [ ] T008 [P] Unit-test the name namespace in `bin/tests/test_pure_logic.py`: stack-vs-agent, agent-vs-stack, stack-vs-stack, and same name on DIFFERENT hosts (which must be allowed)
- [ ] T009 Implement `stack_allocate_ports(name, host)` in `bin/agent-container` reusing the existing per-host port allocation so several stacks coexist (FR-009), and refusing with the conflict named when a port is unavailable (FR-010)
- [ ] T010 Implement `build_stack_compose_model(stack, driver)` in `bin/agent-container` — one service, published ports from T009 bound per T004, a named data volume, retention environment from T001; NO `configs: {file:}` (does not cross a remote context)
- [ ] T011 [P] Test the stack compose model in `bin/tests/test_compose.py`: port bindings match the exposure level, the data volume is named per stack, no `configs:` key, and the model differs by driver only where T004 says it should
- [ ] T012 Extend the inventory record with `kind` in `bin/agent-container` so a stack is distinguishable from an agent environment after the container is gone (FR-023)

**Checkpoint**: exposure, endpoints, naming, ports and the compose model are all proved without
deploying anything.

---

## Phase 3: User Story 1 — Stand up a place for telemetry to land (P1) 🎯 MVP

**Goal**: one command yields a running stack whose ingest accepts a record, and prints the endpoint
an agent container must use.

**Independent test**: run `telemetry stack up` on a host with no stack; assert a record is accepted
afterwards and that the PRINTED endpoint is the one that accepted it.

- [ ] T013 [US1] Add the `telemetry stack` command group and `up` to `bin/agent-container` with the flags from `contracts/cli.md` (`--host`, `--image`, `--exposure`, `--ui-port`, `--otlp-port`, `-y/--yes`, `--json`) — its own group, never a role on `up` (FR-002, FR-008)
- [ ] T014 [US1] Implement the image pull step in `bin/agent-container`, reporting that a pull is happening rather than leaving a blank prompt, and naming a pull failure as the cause (spec Edge Cases)
- [ ] T015 [US1] Implement `stack_ingest_ready(endpoint)` in `bin/agent-container` probing readiness by POSTing an EMPTY OTLP payload and requiring HTTP 200 (research R2) — NOT the runtime healthcheck, which never fires under a rootless podman socket
- [ ] T016 [US1] Wire the staged readiness wait into `up` in `bin/agent-container`: bounded by `STACK_READY_TIMEOUT`, and on expiry reporting WHICH stage — pull, start, or ingest — it was waiting on (FR-006a, FR-006b)
- [ ] T017 [US1] Implement restart-if-stopped in `up` in `bin/agent-container`: running ⇒ report it; stopped ⇒ start it, keep its data, and say "restarted" not "created" (FR-007)
- [ ] T017a [US1] DISCOVER the image's retention settings before applying them: read the variable/config names off `${STACK_IMAGE_DEFAULT}` and record them in `specs/023-telemetry-stack/research.md` under R3 — research R3 states these must be read rather than assumed, because a wrong name sets nothing and the stack then retains forever while looking configured
- [ ] T018 [US1] Apply retention on deploy in `bin/agent-container` (window and ceiling, T001) and ASSERT THE EFFECTIVE VALUE BACK rather than trusting the setting took (FR-025b, research R3)
- [ ] T018a [US1] Handle unconfirmable retention in `bin/agent-container` (FR-025c): warn naming asked-for versus read-back, KEEP the stack, and report retention as `unconfirmed` thereafter rather than echoing the requested value
- [ ] T019 [US1] Print the resolved bind addresses and the container-facing `otlp_endpoint` at the end of `up` in `bin/agent-container` (FR-018b, FR-011)
- [ ] T019b [US1] Implement `--set-endpoint` in `bin/agent-container` writing `otlp_endpoint` into settings.yaml inside a marker-delimited managed region, preserving content outside it byte-for-byte, and writing the CONTAINER-facing form (FR-011b, FR-013); off by default
- [ ] T019a [US1] Print the `egress.allow` entry needed to reach the collector alongside the endpoint in `bin/agent-container` (FR-011a) — an enforcing environment refuses the export and fails OPEN, leaving no error to detect afterwards
- [ ] T020 [P] [US1] Acceptance test in `bin/tests/test_acceptance.py`: `up` on a clean host, then POST a record to the PRINTED endpoint and assert 200 — the endpoint is tested verbatim, not merely "an endpoint" (SC-002, SC-003)
- [ ] T021 [P] [US1] Acceptance test in `bin/tests/test_acceptance.py`: `up` twice ⇒ second reports the existing stack and creates nothing; stop the container out of band, `up` again ⇒ restarted with data intact (FR-007)
- [ ] T021a [P] [US1] Acceptance test in `bin/tests/test_acceptance.py`: drive the stack past a retention bound (a tiny ceiling makes this fast) and assert the ingest STILL returns 200 afterwards — eviction is normal operation for a bounded store, not an error (FR-025a)
- [ ] T022 [P] [US1] Acceptance test in `bin/tests/test_acceptance.py`: readiness failure path — point at an image that starts but never opens an ingest, assert the message names the INGEST stage, not container start (FR-006b)

**Checkpoint**: MVP. A stack exists and receives telemetry.

---

## Phase 4: User Story 3 — Know how to reach it, and who else can (P1)

**Goal**: the exposure decision is explicit, stated, and never widened by accident.

**Independent test**: default exposure ⇒ unreachable from another machine; `network` ⇒ reachable and
the consequence was stated.

- [ ] T023 [US3] Implement `--exposure` handling in `up` in `bin/agent-container`: default `host`, and `network` refused without `-y` on a non-TTY (FR-018, FR-019)
- [ ] T024 [US3] Implement the `network` warning text in `bin/agent-container` stating that the UI is unauthenticated, displays VERBATIM AGENT TASK TEXT, and that the ingest accepts records from anyone who can reach it (FR-019) — the task-text clause is the one an operator will not otherwise expect
- [ ] T025 [US3] Add `telemetry stack url NAME` to `bin/agent-container` printing the UI address, the `otlp_endpoint` line, and — when the UI is not reachable from the operator's machine — the command that makes it reachable (FR-011, FR-012); not running ⇒ say so rather than print a dead address
- [ ] T026 [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: default exposure is reachable from a container on the host and NOT bound to a routable address; `--exposure network` binds routably and emitted the warning (SC-005)
- [ ] T026a [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: `--set-endpoint` writes only inside its markers — content outside is byte-identical afterwards — and re-running replaces the region rather than appending a second one (FR-011b)
- [ ] T026b [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: `--image` overrides the default and the stack still reaches readiness (FR-008) — the flag exists so an operator is never blocked by our choice of image, which is a promise rather than a property until something exercises it
- [ ] T026c [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: exposure is not widened as a SIDE EFFECT — vary `--ui-port`, `--otlp-port` and `--image` and assert the bind addresses are unchanged from the default level (FR-020)
- [ ] T027 [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: `url` output is machine-checkable — the `otlp_endpoint` it prints accepts a record, and the printed bind addresses match what the runtime reports

---

## Phase 5: User Story 2 — See what the agents did, without building dashboards (P1)

**Goal**: a fresh stack answers "what did this run do" with no import step.

**Independent test**: after `up`, query the UI API for the dashboards and assert their queries return
data for a run that exists.

- [ ] T028 [US2] Add the dashboard definitions to `bin/agent-container` as data (fleet, run-trace, runs-and-activity), with a stable `uid` each so re-provisioning overwrites rather than duplicates (FR-015)
- [ ] T029 [US2] Implement `stack_provision_dashboards(stack)` in `bin/agent-container` posting over the Grafana HTTP API with `overwrite` (research R4) — not a file mount, which does not cross a remote context
- [ ] T030 [US2] Build the run-trace dashboard with a FREE-TEXT run selector seeded from a recent-runs panel in `bin/agent-container` — a query variable over the correlation attribute renders empty, because it is structured metadata rather than an indexed label, and every panel then filters on the empty string (research R5)
- [ ] T031 [US2] Ensure metric panels filter only on DATA-POINT attributes in `bin/agent-container`; resource attributes other than `service.*` do not survive the OTLP→Prometheus conversion (research R6)
- [ ] T032 [US2] Make the dashboards agent-agnostic in `bin/agent-container` (FR-017a): lead with a records-by-agent panel covering all four agents, and label agent-specific panels so an empty value reads as "this agent does not report that" rather than as breakage
- [ ] T033 [US2] Wire provisioning into `up` in `bin/agent-container` such that a dashboard failure is REPORTED with the failing dashboard named but does NOT fail the deploy (FR-014, FR-016)
- [ ] T034 [US2] Add `telemetry stack dashboards NAME` to `bin/agent-container` re-provisioning without redeploying, restarting or discarding data (FR-015)
- [ ] T035 [P] [US2] Acceptance test in `bin/tests/test_acceptance.py`: after `up`, every dashboard is present via the UI API and each one's primary query returns data for a seeded run (SC-004)
- [ ] T036 [P] [US2] Acceptance test in `bin/tests/test_acceptance.py`: delete a dashboard, run `dashboards`, assert it is restored AND that data collected beforehand is still queryable (FR-015)

---

## Phase 6: User Story 4 — Run several, and get rid of them (P2)

- [ ] T037 [US4] Add `telemetry stack ls` to `bin/agent-container` showing name, host, state, whether the ingest is answering, and retention (or `unconfirmed`); state is `running` | `stopped` | `undetermined` and never `absent` (which is simply not listed), never a guess (FR-021, FR-025c)
- [ ] T038 [US4] Add `telemetry stack remove NAME` to `bin/agent-container` with `--purge` and `-y`, retaining collected data unless purged (FR-022), and STATING that environments still exporting to it will now fail open — silently, which is why it is said aloud
- [ ] T039 [P] [US4] Acceptance test in `bin/tests/test_acceptance.py`: two stacks on one host run concurrently with distinct ports; removing one leaves the other serving (SC-006)
- [ ] T040 [P] [US4] Acceptance test in `bin/tests/test_acceptance.py`: `remove` without `--purge` retains the data volume; with `--purge` it is gone
- [ ] T041 [P] [US4] Acceptance test in `bin/tests/test_acceptance.py`: `up` refuses a name held by an agent environment and vice versa, naming the kind (FR-009a)

---

## Phase 7: User Story 5 — It is a container this tool created (P2)

- [ ] T041a [P] [US4] Acceptance test in `bin/tests/test_acceptance.py`: a stack is given NO credentials (FR-004) — assert its compose model carries no `configs:`/secret mount, that no credential volume exists for it, and that the credential-delivery path refuses it by kind; a negative security property is the kind that quietly stops being true
- [ ] T042 [US5] Make `panic` stop telemetry stacks in `bin/agent-container`, reporting `undetermined` for a stack on an unreachable host rather than assuming stopped (FR-024)
- [ ] T043 [US5] Record stack creation and outcome in the inventory in `bin/agent-container`, with `kind` distinguishing it from an agent environment (FR-023)
- [ ] T044 [P] [US5] Acceptance test in `bin/tests/test_acceptance.py`: create a stack, run `panic`, assert it stopped and the inventory says so (SC-007)
- [ ] T045 [P] [US5] Acceptance test in `bin/tests/test_acceptance.py`: every created stack appears in `inventory ls` with its kind and outcome, including after removal (SC-008)

---

## Phase 8: Real-agent validation

**This is the end-to-end claim the feature makes**, and the one the goal names explicitly. It is a
phase rather than a task because it exercises every prior phase at once.

- [ ] T046 Real-agent acceptance test in `bin/tests/test_acceptance.py`: bring up a tool-created stack, configure an environment with the endpoint the tool PRINTED, run a real agent headless, and read that run's telemetry back through the stack's own API — correlated by `run_id` (SC-003)
- [ ] T047 Extend T046 in `bin/tests/test_acceptance.py` to assert the run's agent activity AND its container resource usage are both present for the same `run_id`, which is what makes the run-trace dashboard answerable (SC-004, FR-017)
- [ ] T048 Run the real-agent tier in `bin/tests/test_acceptance.py` against a locally deployed stack under podman (`AGENT_CONTAINER_RUNTIME=podman pytest -m acceptance -k "stack and REAL"`) and record the outcome; skip cleanly with a NAMED reason when no agent credential is present, as the existing real-agent tests do

---

## Phase 8b: Remote host (FR-005)

**Why its own phase**: FR-005 makes deployment to a REMOTE host a stated capability, and remote is
where three separate mechanisms behave differently from local — `configs: {file:}` does not cross a
daemon boundary, the operator-facing address is not reachable without a tunnel, and the
container-facing endpoint is resolved on the far side. Every acceptance task before this one is
implicitly local, so without this phase the capability ships unverified.

- [ ] T048a Acceptance test in `bin/tests/test_acceptance.py`: `telemetry stack up` against a REMOTE host reaches readiness, and the compose sent across carries no `configs: {file:}` (which is a daemon-side bind and would fail there) (FR-005)
- [ ] T048b Acceptance test in `bin/tests/test_acceptance.py`: on a remote stack, `url` reports the tunnel command derived from the host's `ssh://` context (`address_from_context`), and the `otlp_endpoint` it prints is resolved for the REMOTE runtime rather than the operator's (FR-012, FR-013)
- [ ] T048c Acceptance test in `bin/tests/test_acceptance.py`: `ls` and `remove` operate on a remote stack, and a stack on an UNREACHABLE host reports `undetermined` rather than `stopped` (FR-021, FR-024)

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T049 [P] Add the `telemetry stack` verbs and every flag to `completions/agent-container.bash`
- [ ] T050 [P] Mirror the same verbs and flags in `completions/agent-container.zsh`
- [ ] T051 [P] Extend `bin/tests/test_completions.sh` with parity checks for the new verbs
- [ ] T052 [P] Add CLI surface tests in `bin/tests/test_cli.py`: group exists, `ls` reads and `remove` is spelled out, every short flag has a long form, `-v` works on each subcommand
- [ ] T053 [P] Write `docs/telemetry-stack.md`: the third kind, the two endpoint forms, exposure levels and what each binds, retention, and the relationship to Feature 017
- [ ] T054 [P] Add a pointer from `docs/observability.md` to the stack — 017 says how to export, this says where to
- [ ] T055 Reconcile the 023 row in `docs/threat-model.md` from ⬜ to ✅, answering the three questions the expectation raised: what the default actually binds, whether the task-text consequence is stated at widening time, and whether an unauthenticated ingest as a WRITE surface is mitigated by anything other than exposure
- [ ] T056 Add one line to `CLAUDE.md` under Decisions naming the third kind and the two-endpoint rule; prune first — the file has a 2000-token budget
- [ ] T057 Run `scripts/quality-gate.sh` and the acceptance tier on BOTH runtimes, reading the exit code unpiped

---

## Dependencies & Execution Order

```
Phase 1 Setup
   └─> Phase 2 Foundational  (BLOCKS everything)
          ├─> Phase 3 US1  (P1) 🎯 MVP
          │      ├─> Phase 4 US3  (P1)  — needs up
          │      ├─> Phase 5 US2  (P1)  — needs a running stack
          │      └─> Phase 6 US4  (P2)  — needs up
          ├─> Phase 7 US5  (P2)  — needs the kind and inventory
          ├─> Phase 8 Real-agent  — needs US1 + US2
          └─> Phase 8b Remote host — needs US1 + US4; cuts across every command
                 └─> Phase 9 Polish
```

**Story independence**: US1 stands alone and is the MVP. US3, US2 and US4 each need only US1's `up`.
US5 needs the kind (Phase 2) plus a deployable stack. US2 is the only story that also depends on
telemetry existing, which Phase 8 supplies for the strongest form of its test.

## Parallel Opportunities

- **Phase 2**: T006, T008, T011 are separate test files — run together. T004/T005/T007/T009/T010/T012 all edit `bin/agent-container` and must be sequential.
- **Phase 3**: T020, T021, T022 in parallel once T013–T019 land.
- **Phase 5**: T035, T036 in parallel after T028–T034.
- **Phase 9**: T049–T054 are all different files — fully parallel. T055–T057 last.

## Implementation Strategy

**MVP is Phase 1 + 2 + 3.** That yields a stack that exists, receives telemetry, and tells you the
right endpoint — useful on its own, and the thing every other story builds on.

**Then P1 completion**: Phase 4 (exposure is a security property, not a nicety) and Phase 5
(dashboards are the reason to run this rather than any generic collector).

**Then P2 and validation**: Phases 6–8.

**Riskiest first, deliberately.** Endpoint and exposure resolution are Phase 2 rather than buried
inside `up`, because they are pure functions, they are the most likely thing to be silently wrong,
and being wrong there produces a stack that looks healthy and receives nothing.
