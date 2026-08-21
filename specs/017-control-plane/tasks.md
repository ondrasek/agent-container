# Tasks: Control-Plane Container

**Feature**: `017-control-plane` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/control-plane-contract.md,
quickstart.md — **all of each**, deliberately without counts or ranges. Four stale counts accumulated
here across two clarification sessions and a re-plan; a reference that has to be maintained in step
with another file is one that will be wrong, and wrong quietly.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelisable: different file or independent region, no incomplete dependency
- **[US1/US2/US3]** — the user story served (user-story phases only)

## Path Conventions

Single-file CLI (`bin/agent-container`), the shared entrypoint (`image/entrypoint.sh`), and a **new
second image** (`image-control-plane/`). Tests in `bin/tests/`.

## Tests

**Requested and load-bearing.** Two properties here are absences and one is a test that currently
cannot fail:

- **The passphrase must exist nowhere** (S4). An absence is what working output never demonstrates.
- **The second image must contain no agents** (S9) — and the existing census reads a hardcoded
  `image/Dockerfile`, so it would stay green while the new image went unchecked (R2).
- **Deploying must grant nothing** (S6). If it granted anything, nesting and revocation both stop
  meaning what the spec says.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create `image-control-plane/` with a `Dockerfile` installing **`agent-container` from PyPI
      at a pinned version**, plus ssh, tmux, git — and **no agent CLIs or runtimes** (FR-015a, C12,
      R1). The CLI is in **no** image today; this is a build, not configuration
- [ ] T002 [P] Add `image-control-plane/.dockerignore` and confirm the build context is that
      directory alone, matching Feature 011's narrow-by-construction rule (FR-015a)
- [ ] T003 [P] Stamp the control-plane image with Feature 013's
      `org.opencontainers.image.version` label from the same build arg, so `doctor` and FR-016 read
      **one** version source rather than two (R1)
- [ ] T004 Teach `build` to build **both** images, and to omit the version arg for each when
      unresolvable — the FR-012b rule already applies to the agent image
- [ ] T005 [P] Add `--role control-plane` to `up` in `bin/agent-container`, selecting the second
      image and recording the role on the environment (FR-001, C8, data-model §1)
- [ ] T006 [P] Add `doctor`, `revoke` and `telemetry` to the command list in
      `completions/agent-container.{bash,zsh}`; the sibling test pins completions to the CLI's list
      and fails until both are updated (FR-001)

**Checkpoint**: a control-plane image builds and deploys; it contains the CLI and no agents.

---

## Phase 2: Foundational (Blocking Prerequisites)

**T007 is the one that must land first. The census cannot currently fail.**

- [ ] T007 **Parameterise the agent census over EVERY Dockerfile** in
      `bin/tests/test_pure_logic.py`, with a declared expectation per image — the agent image installs
      exactly `AGENTS`, the control-plane image installs **none** — and **FAIL on any Dockerfile with
      no declared expectation** (R2, C12). The spec predicted this test would fail on a second image;
      it reads a hardcoded `image/Dockerfile`, so it would silently **not cover** it. The
      fail-on-unknown clause is what makes a third image impossible to add unnoticed
- [ ] T008 [P] Prove T007 can fail: add a throwaway third Dockerfile with no expectation and assert
      the test rejects it (C12, R2). A census that cannot fail is the defect it exists to prevent
- [ ] T009 [P] Acceptance S9 in `bin/tests/test_acceptance.py` — inspect the **built** control-plane
      image and assert no agent CLI is on `PATH` (SC-009). Source census and built-image check are
      different claims; keep both
- [ ] T010 Passphrase-protected key generation in `image/entrypoint.sh`: for a control-plane role,
      generate in-container with a passphrase (not `-N ''`), `0600`, encrypted at rest on the volume
      (FR-007, C3, R3)
- [ ] T011 One-shot passphrase read-out in `bin/agent-container`: read it through the runtime
      **once**, hold it **only within the printing call's scope**, and never assign it to anything
      that outlives the print (R3, C4). This is the feature's narrow Constitution III exception
- [ ] T012 **THE GATE: acceptance S4** — after a control-plane deploy, the passphrase appears in **no**
      file under state/config/data, **no** run record, **no** container log, and **no** `--json`
      payload (C4). Grep for the actual printed value; asserting the print statement's shape proves
      nothing about where the value went
- [ ] T013 [P] Hermetic test that the passphrase never enters a record or an export payload — the
      closed field set of data-model §6 has no slot for it, and this asserts the absence structurally
      rather than by grepping one run's output
- [ ] T014 Inject the host registry as **non-secret configuration** inline in the compose model
      (`configs: {content:}`), the channel every other non-secret injected artifact already uses
      (R4). It is a **snapshot**: a host registered later is invisible until redeploy
- [ ] T015 [P] Hermetic test that the injected registry carries **no** credential material — it is
      names, drivers, contexts and addresses; the capability is the authorised key, not the list
      (FR-004, R4)

**Checkpoint**: the census covers every image and can fail; the passphrase provably exists nowhere.

---

## Phase 3: User Story 1 — Manage from a device with nothing installed (P1) 🎯 MVP

**Goal**: SSH in from an unconfigured device and complete a management task.
**Independent test**: S1 — from a client with no tool and no config, list across hosts then stop one.

### Tests for User Story 1

- [ ] T016 [P] [US1] Acceptance S1 — from outside the container, SSH in and run `list` then `stop`,
      configuring nothing on arrival (C1, SC-001)
- [ ] T017 [P] [US1] Acceptance S2 — with one unreachable permitted host, it is **named as
      unreachable**, never omitted (C2, SC-002). A short list that looks complete is worse than an
      error, because the operator acts on absence
- [ ] T018 [P] [US1] Acceptance S11 — at 80 columns every management command is legible (C11, SC-007)

### Implementation for User Story 1

- [ ] T019 [US1] Live host enumeration on connect in `bin/agent-container` — query the permitted
      hosts, never sync the operator's durable inventory (FR-003a, C2)
- [ ] T020 [US1] Report which permitted hosts did not answer, in both the human and `--json` views
      (FR-003a, SC-002)
- [ ] T021 [P] [US1] Narrow rendering for management commands, selected by **measured width** rather
      than a flag (FR-011, C11, R7) — the operator is already on a phone; a flag puts the work on them
- [ ] T022 [P] [US1] Hermetic test for T021: at 80 columns the renderer emits the block form, and no
      line exceeds the width (FR-011, SC-007)
- [ ] T023 [US1] Verify the in-container CLI reads the injected registry and resolves hosts without
      any on-arrival configuration (FR-002, C1)

**Checkpoint**: US1 is independently usable — a configured CLI on arrival.

---

## Phase 4: User Story 2 — Bound what it can do (P1)

**Goal**: visible, constrainable reach, and revocation that does not touch N hosts by hand.
**Independent test**: a scoped control plane cannot reach the hosts it was not authorised on, and
that is visible before deploying.

### Tests for User Story 2

- [ ] T024 [P] [US2] Acceptance S6 — deploy a control plane and, **without authorising its key
      anywhere**, confirm it reaches nothing (C6, FR-007b). The quiet load-bearer: if deploying
      granted anything, nesting and revocation both stop meaning what the spec says
- [ ] T025 [P] [US2] Acceptance S3 — the private key is `0600`, **encrypted at rest**, and no
      `PRIVATE KEY` appears anywhere on the operator's disk (C3, SC-008)
- [ ] T026 [P] [US2] Acceptance S7 — `revoke` ends access with no per-host manual reconfiguration
      (C7, SC-005)
- [ ] T027 [P] [US2] Acceptance S5 — after stop/start the key is **locked** and the environment is
      usable once the passphrase is supplied, with no reconfiguration and without the operator's own
      machine (C5, FR-012)

### Implementation for User Story 2

- [ ] T028 [US2] Declared scope on the environment, **visible before deploy** (FR-004, SC-004) — a
      declaration of intent, not an enforcement point; reach is where the key is authorised
- [ ] T029 [US2] `revoke <name>` in `bin/agent-container`: withdraw the public key from every host and
      container that trusts it, in one command (FR-008, C7)
- [ ] T030 [P] [US2] Hermetic tests for T029's target set — which hosts and containers are visited,
      and that a failure on one is reported rather than silently skipped (FR-008, C7)
- [ ] T031 [US2] Interactive-only enforcement: the key stays **locked** whenever no operator is
      attached; the passphrase is supplied **on connect** (FR-007a, C5)
- [ ] T032 [US2] State the consequences **before** deployment — that a session holds whatever the
      container holds, the declared scope, and that a lost passphrase has **no recovery** (FR-006,
      FR-017, C19, SC-004)
- [ ] T033 [P] [US2] Hermetic test that the pre-deploy statement names all three, since omitting the
      no-recovery clause is the one an operator only discovers after the loss (FR-017, C19)
- [ ] T034 [P] [US2] Acceptance: an out-of-scope action fails **visibly** rather than partially
      succeeding (FR-005, SC-003)

**Checkpoint**: US2 makes US1 safe to have shipped. Do not ship US1 alone.

---

## Phase 5: User Story 3 — Survive being the thing that manages everything (P2)

**Goal**: it is an environment the tool knows about, and cannot destroy itself mid-operation.
**Independent test**: S8 — `panic` from inside reports its own container as excluded, and it survives.

### Tests for User Story 3

- [ ] T035 [P] [US3] Acceptance S8 — `panic --destroy` from inside reports the control plane as
      **excluded**, names how to stop it instead, and leaves it running (C9, SC-010, SC-006)
- [ ] T036 [P] [US3] Acceptance S10 — silent on a PATCH difference; **advisory** when the control
      plane is newer; **REFUSED** when the environment is newer, naming redeploy as the remedy
      (C10, SC-012)
- [ ] T037 [P] [US3] Hermetic test of the semver rule by precedence, including that
      `major_on_zero = false` makes **pre-1.0 MINOR** the breaking channel — not obvious from the
      numbers, which is why it is tested rather than assumed (FR-016, C10)

### Implementation for User Story 3

- [ ] T038 [US3] Self-exclusion inside Feature 015's existing `panic` path, by the control plane's own
      container name — an exclusion in machinery that already verifies by observation, not a new
      mechanism (FR-010, R6)
- [ ] T039 [US3] Report the exclusion as a **first-class outcome**, never a silent skip (SC-010) —
      only the report is checkable, and this is the one container whose stopping makes the report
      undeliverable
- [ ] T040 [P] [US3] Role and `provenance` on the inventory entry — `operator` vs
      `control-plane:<name>` (FR-009, FR-014a, C8, R8, data-model §1). Persisted, so a **stopped**
      control plane is still identifiable. **Visibility is the whole of the work** — nesting needs no
      enforcement code, because scope is where the key is authorised and a parent cannot constrain a
      child even in principle (R8); a gate here would be a control that cannot control
- [ ] T041 [P] [US3] Acceptance SC-011 — every control plane shows whether it came from the operator's
      machine or another control plane, and which. Nesting lets standing keys grow from inside the
      system, and a count nobody can see is a count nobody audits
- [ ] T042 [US3] The FR-016 semver rule in `bin/agent-container`: ignore patch, advise when newer,
      **refuse** when the environment is newer, `unknown` when either version is unreadable
- [ ] T043 [P] [US3] Multiple control planes are individually identifiable and do not conflict
      (FR-014); and an interrupted session leaves the outcome knowable (FR-013)

**Checkpoint**: coherent with itself, including the recursion.

---

## Phase 6: Dual-stack observability (FR-009a-i)

**Widest-reaching and least coupled to the control plane. The spec warns explicitly: do NOT build
this as control-plane plumbing** - an agent must export with no control plane deployed.

**Two legs, one payload.** The local trail is the durable baseline, written where the action lands
regardless of any endpoint; OTLP export is an additional active path. They are **independent, not
alternatives**, and carry **identical payloads from a single definition** - two lists would drift,
and the drift would be invisible because each leg still looks correct alone.

### The shared payload

- [ ] T044 **One field-set definition serving both legs** in `bin/agent-container` (FR-009f,
      data-model §6) - the attribution trail, Feature 016's run records and Feature 012's egress
      events. `collect` retrieves exactly what export would have sent (C13, R11)
- [ ] T045 [P] Hermetic test that there is **exactly one** definition and both legs read it - assert on
      the shared constant, not on two lists that happen to agree today (FR-009e, FR-009f)
- [ ] T046 [P] Hermetic test that attribution adds **no second operator-free-text field**:
      `RECORD_FIELD_PROVENANCE` keeps exactly one `operator` row, asserted on the table itself
      (FR-009c, C18e) - a second field falsifies the closure while every other test passes
- [ ] T047 Attribution on every management action, mutating and read-only, recording **which** control
      plane performed it, appended where the action lands (FR-009a, SC-013)
- [ ] T048 [P] A host that cannot be written to MUST NOT fail the action - report the gap and mark the
      action **unrecorded** rather than leaving it absent (FR-009b)

### The export state - what the client can actually observe

- [ ] T049 **The export state on every record**: `pending` · `accepted` · `rejected` · `failed`
      (FR-009h). Provenance is `tool`, so it does not touch FR-009c's single `operator` row
- [ ] T050 **`accepted` means the CONFIGURED ENDPOINT returned success for that record - nothing
      more** (FR-009h). It MUST NOT be read or named as arrival at a backend: establishing that would
      require querying the backend's own API, the vendor coupling FR-009d forbids (C14, R9)
- [ ] T051 **Honour OTLP `partial_success`**: subtract rejected records from the response before
      marking anything `accepted` (FR-009h). **A 2xx is not acceptance** - a receiver may return
      success while refusing records, and treating 2xx as success marks refused records as delivered
      (C14, R9)
- [ ] T052 [P] **Acceptance SC-021 - point at a collector configured to REFUSE a subset** and confirm
      those records read `rejected`, not `accepted`. Only a refusing receiver exposes the naive
      2xx-means-success implementation; a compliant collector would pass either way (S17)
- [ ] T053 Derive the state from the response, **never** from the fact that an export was attempted
      (FR-009i) - distinguishing attempt from outcome is the whole point of having the state
- [ ] T054 [P] Hermetic test that `rejected` and `failed` stay distinct, since they decide whether a
      retry is worth attempting: a refusal will be refused again unchanged, an unreachable endpoint may
      simply be back later (FR-009h, C15, R10, S20)

### Export mechanics

- [ ] T055 OTLP/HTTP+JSON export from `image/entrypoint.sh` using **`curl`**, which already ships -
      **zero** Python packages and zero image additions (FR-009d, FR-009g, C18b, R5)
- [ ] T056 **Export fires at WRITE TIME, per record** - not batched at exit, not on a timer (FR-009g).
      Anything held for later is lost exactly when a container is killed, which is the case an audit
      trail exists for; and it needs no resident exporter, which the project avoids on the same
      grounds Feature 012's boundary runs no refresher (C16)
- [ ] T057 [P] **Acceptance SC-022 - kill a running container with `SIGKILL`** and confirm every record
      written before the kill is at the collector. **Not a graceful stop**: a graceful stop would pass
      against an exit-time batch, which is the implementation this rejects (S18)
- [ ] T058 Endpoint declared at **either config level - user or project, project winning** (FR-009d),
      the tool's existing two-level contract (C18g). An environment outside any project still has an
      endpoint, which project-level-only declaration would deny it
- [ ] T059 [P] Hermetic test of the precedence: project overrides user, and a deployment outside any
      project resolves the user-level endpoint (FR-009d, C18g)
- [ ] T060 [P] Acceptance S12 - an agent container's record reaches a real collector with **no control
      plane deployed** (SC-018, C18d). The half that gets missed if export is built as control-plane
      plumbing
- [ ] T061 [P] Acceptance S14 - export is **fail-open**: an unreachable or undeclared collector degrades
      to the local record, reports the gap, and never blocks the work (C18c). Under enforced egress,
      silence yields an empty collector that reads like a quiet system

### The task text

- [ ] T062 Export the task text **by default**, because a task is **not a credential channel** -
      credentials arrive by injection, the SSH keys being container-generated (FR-009f0, FR-009f, C18a)
- [ ] T063 Exclusion of the task text **by name**, never by pattern (FR-009f). The tool cannot know
      whether the collector is the operator's own VPS or a shared backend; a redactor that misses once
      converts caution into false confidence
- [ ] T064 [P] Acceptance S13 - the planted marker is **present** by default and **absent** when
      excluded (SC-017). **Both positions**, at the receiver: a switch verified in one position may not
      be wired at all

- [ ] T065 [P] Acceptance S15 — **`run_id` exports regardless of the task setting**, so a collector
      record can always be matched to its local counterpart (SC-019, C18f). Correlation is what makes
      excluding the task text cheap rather than lossy: without it, the exclusion removes the reason to
      look at the record at all

### Retrieval, and the two legs agreeing

- [ ] T066 `telemetry collect`, available **whether or not** an endpoint is declared (FR-009e), landing
      records in the operator's durable store (`$XDG_DATA_HOME/agent-container/`, `0600`) where
      `runs`/`egress` can read them. Not the "no-endpoint path": the local record exists
      unconditionally (FR-009a), so its retrieval must too. `collect` is Feature 016's `drain`
      GENERALISED, not a second puller (C18, R13)
- [ ] T067 [P] `collect` reports **per-host ingest counts** and **names every host it could not reach**
      (FR-009e, SC-015) - so "collected nothing" is distinguishable from "collected nothing **from
      that host**", and a skipped host never reads as a complete trail
- [ ] T068 `collect` **retries `pending` and `failed`** records (FR-009h), which is what makes it the
      recovery path rather than only a downloader (R10)
- [ ] T069 [P] Acceptance S16 - `collect` works **with and without** an endpoint declared, in both
      configurations deliberately. One that only worked without an endpoint would leave an operator who
      configured OTLP holding logs with no way to download them
- [ ] T070 **THE RECONCILIATION: acceptance SC-020** - for a window, the set of records marked
      `accepted` locally equals the set the collector holds, **or the difference is explicitly
      reported**. Zero silent divergence. This is what makes the dual stack one system rather than two
      hopeful ones, and it is only expressible because both legs carry identical payloads (T044).
      The window is **since the last successful `collect`** or an operator-supplied range, and
      `pending` records are **outside** it — counting not-yet as divergence would fail this against a
      healthy system (C17, R12, S19)
- [ ] T071 [P] **Acceptance SC-014 - the exported trail is TAMPER-EVIDENT.** Destroy the host an action
      was performed on, and separately attempt to remove exported entries **from inside a session**;
      the collector's copy survives both - **zero** exported entries a control plane can remove.
      Measured by destroying and by attempting deletion, never by inspecting the export code: a trail
      the audited party can rewrite is not evidence, and only the negative case proves it
- [ ] T072 [P] Hermetic test that **no backend-specific dependency** is added, checked against the
      installed package set rather than the import list (SC-016)

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T073 [P] `docs/control-plane.md` - the surface, the passphrase contract and its **no-recovery**
      rule, scope, revocation (FR-006, FR-017; Constitution: docs track behaviour)
- [ ] T074 [P] `docs/observability.md` - **the dual stack**: the local trail as durable baseline, OTLP
      as the active path, that they are independent and carry identical payloads, the export state and
      what `accepted` does **not** mean, and the `task` include/exclude with its reasoning
      (FR-009d-i, FR-009f)
- [ ] T075 [P] `docs/agent-interface.md` - the control-plane fields on `list --json`, the telemetry
      payload shape, and the export state values (FR-009f, FR-009h, data-model §6)
- [ ] T076 [P] `README.md` - a short control-plane section, matching how 018/019/013 treat theirs
      (FR-001; Constitution: docs track behaviour)
- [ ] T077 **`docs/threat-model.md` - the 017 row. This feature INTRODUCES A NEW TRUST BOUNDARY**
      (Constitution MUST). Record: the standing key spanning a sandbox shell and daemon access; the
      **passphrase transiting the tool** for one print (R3) as a stated narrow exception to
      Constitution III; the export as a new outbound channel a Feature 012 declaration governs; that
      the exported payload carries the task text by default and what that means for a shared
      collector; and the residual that a compromised control plane acts until its key is withdrawn
- [ ] T078 One-line invariant in `CLAUDE.md` (Constitution: docs track behaviour). The file is at
      **~1993 tokens with ~7 to spare**, so this **DISPLACES** something - measure with a tokenizer,
      not `chars/4`, which understates by ~7%
- [ ] T079 Confirm the commit is `feat` - MINOR (Constitution VII). Additive: a command, a second
      image, an export path; nothing removed and no flag changes meaning
- [ ] T080 Run `scripts/quality-gate.sh` **unpiped**, then the full acceptance tier with **no `-k`**,
      then walk **every scenario in `quickstart.md`** by hand — named as a file rather than a range,
      because a range silently narrows the moment a scenario is added, and the scenarios added last
      are the ones each described as the only check that catches its failure.
      **Do not edit the tree while the tier runs** - it re-reads the CLI per invocation, so a mid-edit
      run measures nothing (this invalidated three runs earlier in this project)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** -> no dependencies
- **Phase 2 (Foundational)** -> blocks everything. **T007 before T009**; **T010/T011 before T012**
- **Phase 3 (US1)** -> needs Phase 2
- **Phase 4 (US2)** -> needs Phase 3's deploy path; **US1 must not ship without US2**
- **Phase 5 (US3)** -> needs Phase 3; independent of Phase 4
- **Phase 6 (observability)** -> needs Phase 2 only. Deliberately **not** downstream of US1-US3,
  because an agent must export with no control plane deployed (SC-018)
- **Phase 7** -> last

### Within Phase 6

**T044 first.** Both legs read one payload definition; every later task assumes it, and SC-020's
reconciliation is unexpressible without it - "do they agree?" has no answer if the legs carry
different things.

**T049-T051 before T052.** The state must exist and honour `partial_success` before a refusing
collector can be pointed at it.

**T056 before T057.** The `SIGKILL` test is meaningless until the write-time trigger is what is being
killed.

### User Story Dependencies

- **US1** - the MVP, but **not shippable alone**: it puts a standing key in a container before US2
  makes that bounded and revocable.
- **US2** - makes US1 safe. No new surface; it bounds the existing one.
- **US3** - coherence and recursion; independent of US2.

### Parallel Opportunities

- T002/T003/T005/T006 together
- T016/T017/T018 together - three independent acceptance scenarios
- T024/T025/T026/T027 together
- T035/T036/T037 together
- T045/T046/T048 together, after T044
- T052/T054/T057/T059/T060/T061/T064/T069/T071/T072 together - independent test files and regions
- T073/T074/T075/T076 together - four different documents

## Parallel Example: Phase 6 export state

```text
# After T049-T051 land the state and the partial_success handling:
T052  refusing collector -> records read `rejected`   <- catches 2xx-as-success
T054  `rejected` vs `failed` stay distinct
T057  SIGKILL -> everything written is at the collector
T061  unreachable collector -> fail-open, gap reported
```

## Implementation Strategy

### MVP scope

Phases 1-3 give a reachable, configured CLI. **But do not stop there.** US1 alone puts a standing key
in a long-lived container without US2's bounding and revocation - which the spec names as trading a
security property for convenience. **The shippable increment is Phases 1-4.**

### Incremental Delivery

1. **Phases 1-2** -> both images build, the census covers both and can fail, the passphrase provably
   exists nowhere
2. **Phase 3** -> US1: a configured CLI on arrival
3. **Phase 4** -> US2: bounded, revocable, consequences stated. **Ship here, not earlier**
4. **Phase 5** -> US3: identity, self-exclusion, the semver rule
5. **Phase 6** -> the dual stack, for every container
6. **Phase 7** -> docs, the threat-model row, the gates

### Ordering that is deliberate rather than conventional

**T007 before anything that adds an image.** The existing census reads a hardcoded
`image/Dockerfile`, so a second image is invisible to it - the suite would stay green while the
container holding keys to everything went unchecked. The spec predicted this test would *fail* on a
second image; it would silently *skip* it, which is the worse direction.

**T012 immediately after T010/T011.** The passphrase's absence is the property, and an absence is
never demonstrated by working output.

**T044 before the rest of Phase 6.** One payload definition is the precondition for the two legs
being comparable at all.

## Notes

- **80 tasks.** US1: 8 · US2: 11 · US3: 9 · observability: 29 · setup/foundational: 15 · polish: 8
- **`accepted` claims only what the client observes** (FR-009h). End-to-end ingestion is not
  observable without querying a backend's API - the coupling FR-009d forbids
- **A 2xx is not acceptance** (T051). OTLP's `partial_success` is the trap, and T052 is the only test
  that catches it
- **The passphrase is the only secret this tool ever touches** (R3). Every task near it keeps its
  durable copy nowhere but the operator's password manager
- **Scope is where the key is authorised**, so no task enforces scope inside the container - that
  would be a control that cannot control
