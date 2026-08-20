# Tasks: Control-Plane Container

**Feature**: `017-control-plane` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

**Input**: spec.md (30 FR, 19 SC), plan.md, research.md (R1–R8), data-model.md,
contracts/control-plane-contract.md (C1–C19), quickstart.md (S1–S16)

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
      `control-plane:<name>` (FR-009, FR-014a, data-model §1). Persisted, so a **stopped** control
      plane is still identifiable
- [ ] T041 [P] [US3] Acceptance SC-011 — every control plane shows whether it came from the operator's
      machine or another control plane, and which. Nesting lets standing keys grow from inside the
      system, and a count nobody can see is a count nobody audits
- [ ] T042 [US3] The FR-016 semver rule in `bin/agent-container`: ignore patch, advise when newer,
      **refuse** when the environment is newer, `unknown` when either version is unreadable
- [ ] T043 [P] [US3] Multiple control planes are individually identifiable and do not conflict
      (FR-014); and an interrupted session leaves the outcome knowable (FR-013)

**Checkpoint**: coherent with itself, including the recursion.

---

## Phase 6: Telemetry export (FR-009a–g)

**Widest-reaching and least coupled to the control plane. The spec warns explicitly: do NOT build
this as control-plane plumbing** — an agent must export with no control plane deployed.

- [ ] T044 Attribution on every management action, mutating and read-only, recording **which** control
      plane performed it, appended where the action lands (FR-009a, SC-013)
- [ ] T045 [P] A host that cannot be written to MUST NOT fail the action — report the gap, and mark the
      action **unrecorded** rather than leaving it absent (FR-009b)
- [ ] T046 [P] Hermetic test that attribution adds **no second operator-free-text field**:
      `RECORD_FIELD_PROVENANCE` keeps exactly one `operator` row across fourteen fields, asserted on
      the table itself (FR-009c, C18) — a second field falsifies the closure while every other test
      passes
- [ ] T047 OTLP/HTTP+JSON export from `image/entrypoint.sh` using **`curl`**, which already ships —
      **zero** Python packages and zero image additions (FR-009d, FR-009g, C14, R5)
- [ ] T048 [P] Hermetic test that **no** backend-specific dependency is added, checked against the
      installed package set rather than the import list (SC-016)
- [ ] T049 The exported field set per data-model §6, with **`task` included by default** because a task
      is not a credential channel (FR-009f0, FR-009f, C13)
- [ ] T050 Exclusion of the task text **by name**, never by pattern (FR-009f). The tool cannot know
      whether the collector is the operator's own VPS or a shared backend; a redactor that misses once
      converts caution into false confidence
- [ ] T051 [P] Acceptance S13 — the planted marker is **present** by default and **absent** when
      excluded (SC-017). **Both positions**, at the receiver: a switch verified in one position may not
      be wired at all
- [ ] T052 [P] Acceptance S12 — an agent container's record reaches a real collector with **no control
      plane deployed** (SC-018, C16)
- [ ] T053 [P] Acceptance S14 — export is **fail-open**: an unreachable or undeclared collector
      degrades to the local record, reports the gap, and never blocks the work (C15). Under enforced
      egress, silence yields an empty collector that reads like a quiet system
- [ ] T054 [P] Acceptance S15 — `run_id` exports regardless of the task setting, so a collector record
      always matches its local counterpart (SC-019, C17)
- [ ] T054a [P] **Acceptance SC-014 — the exported trail is TAMPER-EVIDENT.** Destroy the host an
      action was performed on, and separately attempt to remove exported entries **from inside a
      session**; the collector's copy must survive both — **zero** exported entries a control plane can
      remove. Measured by destroying and by attempting deletion, never by inspecting the export code:
      a trail the audited party can rewrite is not evidence, and only the negative case proves it.
      **This is the property that justified off-box export at all**, and it had no task
- [ ] T055 `telemetry collect` for the no-endpoint case: gather from every reachable host and **name
      every host it could not reach** (FR-009e, SC-015)
- [ ] T056 [P] Acceptance S16 for T055, asserting the naming — a collection that silently skipped a
      host reads as complete

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T057 [P] `docs/control-plane.md` — the surface, the passphrase contract and its **no-recovery**
      rule, scope, revocation, the export (FR-006, FR-017; Constitution: docs track behaviour)
- [ ] T058 [P] `docs/observability.md` — the export: what leaves, what never does, the declared
      endpoint, and the `task` include/exclude with its reasoning (FR-009d, FR-009f)
- [ ] T059 [P] `docs/agent-interface.md` — the control-plane fields on `list --json`, and the
      telemetry payload shape (FR-009f, data-model §6)
- [ ] T060 [P] `README.md` — a short control-plane section, matching how 018/019/013 treat theirs (FR-001; Constitution: docs track behaviour)
- [ ] T061 **`docs/threat-model.md` — the 017 row. This feature INTRODUCES A NEW TRUST BOUNDARY**
      (Constitution MUST). Record: the standing key spanning a sandbox shell and daemon access; the
      **passphrase transiting the tool** for one print (R3) as a stated narrow exception to
      Constitution III; the export as a new outbound channel a Feature 012 declaration governs; and
      the residual that a compromised control plane acts until its key is withdrawn
- [ ] T062 One-line invariant in `CLAUDE.md`. The file is at **~1993 tokens with ~7 to spare**, so this
      **DISPLACES** something — measure with a tokenizer, not `chars/4`, which understates by ~7% (Constitution: docs track behaviour)
- [ ] T063 Confirm the commit is `feat` — MINOR (Constitution VII). Additive: a command, a second
      image, an export path; nothing removed and no flag changes meaning
- [ ] T064 Run `scripts/quality-gate.sh` **unpiped**, then the full acceptance tier with **no `-k`**,
      then walk quickstart S1–S16 by hand. **Do not edit the tree while the tier runs** — it re-reads
      the CLI per invocation, so a mid-edit run measures nothing (this invalidated three runs earlier
      in this project)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)** → no dependencies
- **Phase 2 (Foundational)** → blocks everything. **T007 before T009**; **T010/T011 before T012**
- **Phase 3 (US1)** → needs Phase 2
- **Phase 4 (US2)** → needs Phase 3's deploy path; **US1 must not ship without US2**
- **Phase 5 (US3)** → needs Phase 3; independent of Phase 4
- **Phase 6 (telemetry)** → needs Phase 2 only. Deliberately **not** downstream of US1–US3, because
  an agent must export with no control plane deployed
- **Phase 7** → last

### User Story Dependencies

- **US1** — the MVP, but **not shippable alone**: it puts a standing key in a container before US2
  makes that bounded and revocable. The spec says shipping US1 without US2 trades a real security
  property for convenience.
- **US2** — makes US1 safe. No new surface; it bounds the existing one.
- **US3** — coherence and recursion; independent of US2.

### Parallel Opportunities

- T002/T003/T005/T006 together
- T008/T009 after T007; T013/T015 alongside
- T016/T017/T018 together — three independent acceptance scenarios
- T024/T025/T026/T027 together
- T035/T036/T037 together
- T045/T046/T048/T051/T052/T053/T054 together — independent test files and regions
- T057/T058/T059/T060 together — four different documents

## Parallel Example: User Story 2

```text
# The four acceptance scenarios first, together:
T024  deploying grants nothing        <- the quiet load-bearer
T025  key encrypted, none on disk
T026  revoke ends access in one command
T027  locked after reboot, usable with the passphrase
```

## Implementation Strategy

### MVP scope

Phases 1–3 give a reachable, configured CLI. **But do not stop there.** US1 alone puts a standing key
in a long-lived container without US2's bounding and revocation — which the spec names as trading a
security property for convenience. **The shippable increment is Phases 1–4.**

### Incremental Delivery

1. **Phases 1–2** → both images build, the census covers both and can fail, the passphrase provably
   exists nowhere
2. **Phase 3** → US1: a configured CLI on arrival
3. **Phase 4** → US2: bounded, revocable, consequences stated. **Ship here, not earlier**
4. **Phase 5** → US3: identity, self-exclusion, the semver rule
5. **Phase 6** → telemetry, for every container
6. **Phase 7** → docs, the threat-model row, the gates

### Ordering that is deliberate rather than conventional

**T007 before anything that adds an image.** The existing census reads a hardcoded
`image/Dockerfile`, so a second image is invisible to it — the suite would stay green while the
container holding keys to everything went unchecked. The spec predicted this test would *fail* on a
second image; it would silently *skip* it, which is the worse direction and the one this project has
hit repeatedly.

**T012 immediately after T010/T011.** The passphrase's absence is the property, and an absence is
never demonstrated by working output.

## Notes

- **64 tasks.** US1: 8 · US2: 11 · US3: 9 · telemetry: 13 · setup/foundational: 15 · polish: 8
- **The passphrase is the only secret this tool ever touches** (R3). Every task near it is written to
  keep its durable copy nowhere but the operator's password manager
- **Scope is where the key is authorised**, so no task enforces scope inside the container — that
  would be a control that cannot control
- **`task` IS exported** (FR-009f0): a task is not a credential channel, credentials arrive by
  injection, and the SSH keys are container-generated
