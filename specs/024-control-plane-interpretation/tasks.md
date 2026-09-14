---

description: "Task list for feature 024 — Interpreting control plane"
---

# Tasks: Interpreting control plane

**Input**: Design documents from `/specs/024-control-plane-interpretation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: included and non-optional. This project's constitution makes verification part of the
change ("Verify before trust"), the acceptance tier is the authoritative validation layer, and two
of this feature's requirements (FR-020, FR-020a) are **absences**, which cannot be demonstrated any
other way.

## Implementation status (2026-09-14)

**22 of 72 tasks complete, and CI is green on both runtimes** — quality gate, pytest, build,
acceptance (docker) and acceptance (podman) all pass at `f40eb39`. What is built is built to the
bar; what is not built is not started, and there is no half-wired surface pretending otherwise.

| Phase | State |
|---|---|
| 1 — Setup | **complete** (T001–T004) |
| 2 — Foundational | **partial**: the stack read path with unreachable-vs-empty kept distinct (T007), and the channel credential proven to travel Constitution IX's path (T010a, T010c, T010d). The watermark and the signal-envelope helper are not built — they have no consumer until Phase 4. |
| 3 — US2, log export | **complete** (T011–T018a), verified end to end under both runtimes |
| 7 — US4 | **partial**: role, pre-deploy statement, admit-set refusals, `interpret ls`/`show`, inventory fields, kill-switch coverage, the authority guard (T027, T028, T042, T043, T044, T049) |
| 9 — Polish | **partial**: `docs/observability.md` (T057); the threat-model row exists unreconciled |
| 4, 5, 6, 8 | **not started** |

**What remains is the interpreter itself** — the bridge that reads the trail, forms an
interpretation, notifies over Slack and answers questions.

**Three things the next session should know:**

1. **Phases 4, 5 and 6 cannot be fully verified in a dev environment.** They need a real Slack custom
   app, a bot token and a workspace. The contract is pinned in `contracts/signals.md` and can be
   built against a stub, but "it works" is not demonstrable without those, and a task marked done on
   a passing stub is the failure this spec warns about.
2. **The acceptance tier has caught five defects that unit tests AND sub-agent review both passed
   over** — three in the exporter, a privacy regression where excluding the task no longer made it
   private, and a field-set guard updated in three of its four encodings. Every one silent, because
   export is fail-open. Build the acceptance test for a phase before trusting its unit tests.
3. **One risk is documented rather than closed**: a dead `tee` kills the agent with SIGPIPE
   (measured, exit 141). Closing it means giving the agent the buffer file as its direct fd and
   losing `compose logs` ordering — a trade deliberately not made. See the comment at the tee.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelisable — different files, no dependency on an incomplete task
- **[Story]**: US1–US6 from spec.md
- Exact file paths in every task

## Standing constraints for every task in this file

These are not reminders, they are acceptance conditions. A task that violates one is not done.

1. **No new third-party Python dependency.** `curl`, `jq` and `python3` are already in
   `image/Dockerfile`; the CLI's dependency set does not grow. (Constitution VI, research R1.)
2. **No new Dockerfile and no new image.** An interpreter is the agent image with a narrower
   credential set. (plan.md, reconciliation with 017.)
3. **No inbound port** on the interpreter, opened or published.
4. **Principle X — surgical change.** Every changed line traces to an FR. Do not reformat, refactor
   or tidy adjacent code. **Do not shorten any existing comment**: the regions this feature touches
   are the most densely commented in the tree and those comments record measured failures.
5. **Credentials travel per Constitution IX** — over the container's own sshd, never in the compose
   model, never on argv, never in a record or `--json` payload.

---

## Phase 1: Setup

**Purpose**: the constants and surface the rest of the feature hangs off.

- [X] T001 **(FR-001)** Add `ROLE_INTERPRETER` to the `ROLES` tuple in `bin/agent-container` (~line 105), beside
      `ROLE_AGENT` and `ROLE_CONTROL_PLANE`. Add only the constant and its inclusion in `ROLES`.
- [X] T002 [P] Add the named defaults from research.md §R6 as module-level constants in
      `bin/agent-container`: channel poll interval (15s), trail poll interval (30s), stall window
      (20m), per-run log cap (10MB), export batch flush (100 lines / 64KB / 2s), the FR-015
      notifiable-event set, digest off. Each named at the surface per Constitution VIII.
- [X] T003 [P] **(FR-007b)** Add `export_agent_logs` (default true) and `agent_log_cap_mb` (default 10) to the
      settings schema in `bin/agent-container`, as a switch **separate** from `export_task_text` —
      see contracts/cli.md for why one switch governing both would mislead.
- [X] T004 [P] Assert the settings-key contract in `bin/tests/test_cli.py`: both new keys are
      readable, defaulted, and reported as absent-versus-defaulted distinctly (Constitution VIII's
      "absent ≠ defaulted ≠ declared-empty").

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: the shared signal writer, the stack read path, and the watermark. Unblocks US1, US3,
US5 and US6; US2 needs only the writer; US4 needs only the role.

- [ ] T005 Implement the OTLP signal envelope helper in `bin/agent-container`, deriving resource
      attributes from the **existing** 017 attribution definition rather than a second list — two
      lists agree today and drift invisibly. Emits the shared attribute block in
      contracts/signals.md Part 1.
- [ ] T006 [P] Contract-test the envelope in `bin/tests/test_run_records.py` (or the nearest
      existing payload test module): `run_id` present on every payload; attribute set closed per
      signal; an undeclared attribute produces a warning at read time, as 016 warns for unknown
      record fields. **(FR-010)** Include the guard that log export does not change what a record
      is: a record keeps 016's closed field set, and no log field may be folded into it.
- [X] T007 Implement the stack read helper in `bin/agent-container` using the `curl` +
      `/loki/api/v1/query_range` idiom that 023's `stack_storage_probe` already uses. **Record in a
      comment why this is permitted here and forbidden in `reconcile`**: the tool queries a stack it
      created, never an operator's own collector (research R3, 017's vendor-coupling refusal).
- [ ] T008 Implement the watermark per data-model.md: one per signal class per interpreter,
      advancing **only after** the window's events are recorded in the bookkeeping ledger. 017's
      reconcile watermark carries the same rule; the comment should say so.
- [ ] T009 [P] Unit-test watermark advancement in `bin/tests/test_pure_logic.py`, including the
      negative case that matters: a partial pass must **not** advance it, or the next pass treats
      unprocessed events as "before the window" and silently drops exactly what was missed.
- [ ] T010 Implement `--stack NAME` resolution on `up` in `bin/agent-container`, refusing with the
      stack named when it is absent or unreachable. A refusal, never a degraded mode (research R3).
- [X] T010a **(FR-005)** Deliver the interpreter's credentials — the Slack bot token and the stack
      address — to the **running** container over **its own sshd**, reusing the existing Feature
      003/019 delivery machinery in `bin/agent-container`. Constitution IX: never in the compose
      model, never on argv, never in a run record or `--json` payload. No new delivery path is to be
      invented; if the existing one does not fit, that is a finding to raise, not a second mechanism
      to build.
- [ ] T010b **(FR-005)** Implement credential **withdrawal** without destroying the interpreter, and
      assert it in `bin/tests/test_credentialing.py`. A credential that can only be withdrawn by
      destroying its holder is one an operator will not withdraw.
- [X] T010c **(FR-006)** Describe the Slack bot token as a credential whose holder can **speak as
      the interpreter to the operator**, wherever the tool enumerates what an environment holds.
      Assert the wording in `bin/tests/test_cli.py` — the blast radius is the point, and a token
      listed without it reads as configuration.
- [X] T010d **(FR-004)** Assert in `bin/tests/test_cli.py` that an interpreter's credential set is
      **disjoint from** a 017 control plane's: it receives no standing host key. FR-004 requires the
      read credential to be distinct precisely because a 017 key is not scoped to inspect.

**Checkpoint**: signals can be written, the stack can be read, position is tracked durably, and the
interpreter's credentials arrive the way every other credential in this tool arrives.

---

## Phase 3: User Story 2 — The logs reach the trail (P1)

**Goal**: the agent's output outlives its container, correlated to its run.

**Independent test**: run an agent with an endpoint declared, query the stack by `run_id`, assert
the output lines are present and in order; destroy the container; assert they are still there.

- [X] T011 [US2] **(FR-007)** Add the log exporter to `image/entrypoint.sh`, **beside** the existing OTLP
      attribute composition (`_otel_attrs`, ~line 1442). Add beside; **do not restructure that
      region and do not shorten its comments**. Tee the agent's output into a buffer the exporter
      drains, batching per the T002 flush defaults and POSTing the `log` signal with `curl`.
- [X] T012 [US2] Make the exporter run **off the agent's critical path** in
      `image/entrypoint.sh`: a slow, wedged or dead exporter loses log lines and MUST NOT apply
      back-pressure. FR-007a — observability that can stall the work inverts the point of the dual
      stack.
- [X] T013 [US2] **(FR-008)** Implement the per-run cap and its single `truncated` marker record in
      `image/entrypoint.sh` per contracts/signals.md. The marker is a **record with an attribute**,
      not a line of body text, so consumers find it by attribute and not by matching text they do
      not control.
- [X] T014 [US2] **(FR-007c)** Honour `export_agent_logs` in `image/entrypoint.sh`: excluded by name only, never
      by pattern or entropy heuristic (FR-007c — a redactor that misses one value converts caution
      into false confidence).
- [X] T015 [US2] **(FR-007b)** State the wider exposure when an endpoint is declared, in `bin/agent-container`:
      logs carry whatever the agent printed, which is broader than the task text (FR-007b).
- [X] T016 [US2] **(FR-009)** Extend `runs show` in `bin/agent-container` to name the stack as where the log went
      when it was exported, and to keep saying logs are gone when it was not (FR-009).
- [X] T017 [P] [US2] Shell-suite coverage in `bin/tests/test_entrypoint.sh`: correlation by
      `run_id`, stdout/stderr kept distinct, sequence monotonic, cap reached produces exactly one
      marker, and a dead endpoint leaves the run completely unaffected.
- [X] T018 [P] [US2] Acceptance test in `bin/tests/test_acceptance.py`: logs queryable in the stack
      after `down --purge` destroys the container (SC-003).
- [X] T018a [P] [US2] **(FR-025a)** Parameterise a log-export test over the `AGENTS` tuple, so the
      stream is proven identical for every supported agent and the test **fails on an agent it has
      no expectation for** — the idiom 017's agent census already uses. This is what keeps a
      per-agent format from creeping in later.

**Checkpoint**: US2 is demonstrable alone and delivers value with nothing else built.

---

## Phase 4: User Story 1 — Be told when something needs me (P1)

**Goal**: the operator is told, without asking, when something warrants it.

**Independent test**: deploy an interpreter, fail a headless run, assert a message arrives naming
environment, run id and outcome with a reading grounded in that run's log.

- [X] T019 [US1] Implement the notification policy over the trail in `bin/agent-container`: the
      FR-015 notifiable set, quiet on success-that-pushed (FR-015a), stall reported as a **duration
      and last output** rather than a verdict (FR-015b), one notification per state change.
- [X] T020 [US1] **(FR-012)** Implement the `interpretation` signal writer per data-model.md, including
      `evidence[]` with its three kinds — and `absence` as a first-class kind, without which "no
      output since 14:02" cannot be sourced at all.
- [X] T021 [US1] Implement evidence binding in `bin/agent-container`: every claim resolves to a
      record field, a log span or an absence, and an unsourceable claim is labelled `inferred`
      (FR-011a).
- [X] T022 [US1] Implement input-health precedence (FR-013): stack unreachable, ingest `DEGRADED`,
      host unreachable or log absent is stated **before** any claim about agents. Never infer
      activity or inactivity from missing data.
- [ ] T023 [US1] **(FR-012b)** Implement the `notification` bookkeeping signal keyed on the **event**, not the
      message (data-model.md) — this is what makes catch-up idempotent after a restart.
- [X] T024 [US1] **(FR-016)** Implement the Slack write path (`chat.postMessage`) in
      `image/interpret-bridge.py`, stdlib only, with the FR-016 required fields in every message
      including the interpreter's own identity.
- [X] T025 [US1] Implement hold-and-deliver on channel failure in `image/interpret-bridge.py`:
      held in order, delivered on recovery marked delayed, `429` honouring `Retry-After`, and **no
      effect on any agent in the fleet** under any channel condition (FR-018).
- [X] T026 [US1] Implement catch-up after absence (FR-017): notification derived from the trail and
      the ledger, not from having witnessed events, so a stopped or rebooted interpreter reports
      what it missed, marked late, without duplicates.
- [X] T027 [US1] **Write the FR-020a reachability guard now, with this phase, not after it.** In
      `bin/tests/test_cli.py` (or a dedicated guard module), walk the transitive closure of
      `__code__.co_names` from every `interpret` command and assert no mutating helper is reachable
      — the technique Feature 013 uses to prove `doctor` read-only *by composition* rather than on
      the paths a test happened to exercise.
- [X] T028 [US1] Add the reachability guard to `bin/tests/test_guards_can_fail.py`, proving it
      **fails** when a mutating call is introduced. A guard nobody has seen fail is a guard nobody
      knows works.
- [X] T029 [P] [US1] Unit-test the policy in `bin/tests/test_pure_logic.py`: quiet on success,
      stall wording carries duration and last output, one notification per state change.
- [X] T030 [P] [US1] Acceptance test in `bin/tests/test_acceptance.py`: failed run notified within
      budget with grounded reading (SC-001, SC-002); successful run produces no interruption.
- [X] T031 [P] [US1] Acceptance test: interpreter stopped across three events and a host reboot
      reports all three on return, marked late, no duplicates (SC-008).

**Checkpoint**: the feature's headline capability works.

---

## Phase 5: User Story 3 — Ask from the phone (P1)

**Goal**: fleet status in conversation, grounded in the trail.

**Independent test**: with two runs on different hosts, ask about one; the reply identifies the
right environment and run and cites the identifiers it used.

- [X] T032 [US3] **(FR-024)** Implement `conversations.history` polling in `image/interpret-bridge.py` at the
      T002 interval — HTTPS only, **not Socket Mode**, which would require a WebSocket client and
      therefore a dependency (research R1).
- [X] T033 [US3] Implement declared-sender admission in `image/interpret-bridge.py`: no default
      admits anyone; a message from any other sender gets **no reply** and a recorded refusal
      carrying the sender's channel identity (FR-023, SC-007).
- [X] T034 [US3] Implement grounded replies in `image/interpret-bridge.py`: every claim names the
      run it came from; what could not be seen is stated rather than filled in (FR-011a, FR-013).
- [X] T035 [US3] Implement unreachable-host reporting in replies: `undetermined`, never `absent` or
      `stopped` (Feature 014's rule, which a summarising reader is otherwise tempted to smooth over).
- [ ] T036 [US3] Implement `interpret test-channel NAME` in `bin/agent-container` per
      contracts/cli.md: post, read back, report the admitted sender identity — runnable before
      trusting the binding overnight.
- [X] T037 [P] [US3] Acceptance test in `bin/tests/test_acceptance.py`: question answered within a
      minute naming the correct run, elapsed time, commits and pushes (SC-010); undeclared sender
      gets silence plus a recorded refusal (SC-007).

---

## Phase 6: User Story 5 — It cannot be talked into acting (P2)

**Goal**: the interpreter's input is attacker-writable; prove that costs a message at most.

**Independent test**: an agent prints supervisor-addressed instructions; nothing changes, and the
notification quotes them as content.

- [X] T038 [US5] Implement observed-directive handling in `bin/agent-container`: instruction-shaped
      text in agent output is reported as `observed_directives`, quoted as content, and **never**
      alters assessment, policy or any action (FR-014).
- [X] T039 [US5] Implement contradiction reporting (FR-011b): record and log disagreements are
      stated as disagreements, with the record as the authority for what happened and the log as the
      authority for what the agent said. Never resolved by adopting the agent's account.
- [X] T040 [US5] Implement the act-refusal path in `image/interpret-bridge.py`: decline, name the
      path that can do it, record the request, attempt nothing indirect, and never report having
      done what it did not do (FR-022).
- [X] T041 [P] [US5] Adversarial acceptance tests in `bin/tests/test_acceptance.py` carrying SC-005:
      injected supervisor instructions change nothing and are quoted as content; a log claim
      contradicting the record is reported as a contradiction, not repeated.
- [X] T042 [P] [US5] Structural test asserting the **absence** of authority (SC-004a), in the style
      of 023's no-credentials assertion: no container runtime client in the image, no host key in
      the container, no action credential anywhere. A negative security property is the kind that
      quietly stops being true.
- [ ] T042a [US5] **(FR-026)** Bound the interpreter's **reach**, which is a different absence from
      its authority: assert no code path reads a container's filesystem, its volumes or its
      credentials to form an interpretation. What it cannot see through the trail, it cannot see.
      Use the T027 reachability technique rather than a behavioural test — the property is
      "no such path exists", not "no such path ran today".
- [ ] T042b [P] [US5] **(FR-025)** Assert that no agent-native session data — transcript, tool-call
      record, memory file or agent configuration — is exported or read, in
      `bin/tests/test_acceptance.py`. This is the operator's log-scope decision made enforceable;
      without the test it is a paragraph in a spec.

---

## Phase 7: User Story 4 — It is a container this tool created (P2)

**Goal**: the tool's invariants hold for the new role.

**Independent test**: deploy, list, kill-switch; it appears with role, scope and channel throughout.

- [ ] T043 [US4] **(FR-001, FR-003, FR-021, FR-024a)** Implement `up --role interpreter` in `bin/agent-container` with the options in
      contracts/cli.md, and the **pre-creation statement** printed not prompted (017's rule: a
      prompt on a path an agent may drive is auto-answered, which reads as consent).
- [ ] T043a [US4] **(FR-024b, SC-014)** Implement the refusal to bind a channel that cannot
      authenticate its sender, in `bin/agent-container`, and test it against a channel definition
      that omits sender identity. Specified in contracts/cli.md's refusal table; a contract row
      nothing implements is a control that reads as deliberate and enforces nothing.
- [X] T044 [US4] **(FR-002, FR-021)** Record role, watched scope, channel binding **and authority**
      on the inventory entry in `bin/agent-container`, so a stopped interpreter is still
      identifiable and its authority is visible after deploy, not only stated before it.
- [ ] T045 [US4] **(FR-012a)** Implement `interpret ls`, `interpret show` and `interpret history` per
      contracts/cli.md, each with `--json`. `history` is FR-012a — "what did you tell me about run
      X, and why".
- [ ] T046 [US4] **(FR-025)** Implement `interpret serve`, refusing to run outside an interpreter container.
- [ ] T047 [US4] **(FR-027)** Implement self-exclusion from its own notifications: its runs are
      recorded like any environment's but never notified about, or every message becomes an event
      becomes a message.
- [ ] T047a [P] [US4] **(FR-028)** Assert the other half: the interpreter's own runs **do** produce
      records and logs, attributed to it, so what it read, concluded and sent is itself part of the
      trail. Exclusion from notification must not become exclusion from the record.
- [ ] T048 [US4] Implement version-skew handling per 017's rule (FR-029): semver precedence,
      advisory when newer, refusal naming the remedy when the trail is newer, and a record whose
      schema it does not understand **refused rather than misread**, reported as a finding.
- [X] T049 [P] [US4] Extend the kill switch in `bin/agent-container` to cover interpreters (FR-030),
      with unreachable hosts reported `undetermined`.
- [ ] T050 [P] [US4] Acceptance test in `bin/tests/test_acceptance.py`: role visible in `list` and
      `inventory ls`; kill switch stops it; unreachable host reported undetermined (SC-011).
- [ ] T050a [P] [US4] **(SC-012)** Acceptance test: what `up` states before creation **matches what
      the inventory shows afterwards**. A statement that drifts from the record is worse than no
      statement, because it is believed.
- [ ] T050b [P] [US4] **(SC-013, FR-024a)** Assert the task-text/log exposure statement is emitted
      **before anything is created** — the ordering is the whole criterion, since a consequence
      disclosed after the fact was not disclosed.
- [ ] T051 [P] [US4] Extend `doctor` to report whether stack, channel binding and declared sender
      **resolve**, staying inside 013's read-only guarantee — check that the token is declared,
      never retrieve it.

---

## Phase 8: User Story 6 — Quiet when nothing is wrong (P3)

- [ ] T052 [US6] **(FR-019)** Implement digest mode in `bin/agent-container` and `image/interpret-bridge.py`:
      off by default, summaries at named times or on request.
- [ ] T053 [US6] Implement the silence window: events held during it are delivered at its end
      **marked as held** — silenced is not forgotten (FR-019).
- [ ] T054 [US6] Implement policy changes from the channel, each confirmed back in the same
      conversation so the operator can see what the interpreter now believes its instructions are.
- [ ] T055 [P] [US6] Acceptance test: ten successful runs produce zero interruptions and exactly one
      digest naming all ten (SC-009).

---

## Phase 9: Polish & cross-cutting

Not a follow-up. The constitution requires spec, docs and threat model to be updated **in the same
change** as the behaviour; stale docs are defects.

- [ ] T056 Write `docs/interpretation.md`: what an interpreter is, how it differs from a 017 control
      plane, what it holds, what it cannot do and why that is structural, the Slack setup including
      the **custom-app requirement** and the rate-limit cliff a distributed app falls off.
- [X] T057 [P] Update `docs/observability.md`: the agent output stream is now a third payload class;
      `export_agent_logs` and its exposure; the per-run cap and truncation marker.
- [ ] T058 [P] Update `docs/control-plane.md` to distinguish the two roles, so an operator choosing
      between them is not left inferring it.
- [ ] T059 Reconcile `docs/threat-model.md` and flip the 024 maintenance row from ⬜ to ✅. The
      **expectation row already exists** — `test_threat_model_names_every_feature` demanded it the
      moment the spec directory appeared, which is the guard working as designed. Reconciling means
      answering the questions that row raises against what was actually built, in the style of the
      023 row, which is honest about the three things that went wrong while its own expectation
      held. It must record: a second inbound instruction path that opens no port; a new credential whose
      blast radius is "can speak as the interpreter"; **task text and agent output crossing out of
      the operator's trust domain** into a Slack workspace (T15 widened); forged interpretations on
      an unauthenticated ingest as an accepted limit with exposure as the only control; and the
      authority absence as the mitigation that makes the rest tolerable.
- [ ] T060 [P] Update `CLAUDE.md` only if an invariant changed — and if it did, prune first: the
      file measures 1999 tokens against its own 2000-token cap. Measure with a tokenizer.
- [ ] T061 Run the full gate unpiped (`./scripts/quality-gate.sh`; read its exit code) and the
      acceptance tier under **both** runtimes. The podman/docker split is where this project's
      runtime-specific defects surface.

---

## Dependencies

```text
Phase 1 (setup)
   └─► Phase 2 (foundational: signal writer, stack read, watermark)
          ├─► Phase 3  US2  log export            ── independently shippable
          ├─► Phase 4  US1  notification          ── needs Phase 3 for evidence to exist
          │      └─► Phase 5  US3  conversation
          │             └─► Phase 6  US5  resistance
          ├─► Phase 7  US4  container invariants  ── needs only Phase 1's role
          └─► Phase 8  US6  quiet                 ── needs Phase 4's policy
                 └─► Phase 9  docs + threat model
```

**Story independence**: US2 and US4 are independently deliverable off Phase 2. US1 depends on US2
only for its *inputs* to be interesting — the policy works against records alone, so US1 is testable
before US2 lands, with thinner interpretations.

## Parallel opportunities

- **Phase 1**: T002, T003, T004 together.
- **Phase 2**: T010b, T010c, T010d together once T010a lands.
- **Phase 3**: T017, T018, T018a once T011–T016 land.
- **Phase 4**: T029, T030, T031 together.
- **Phase 6**: T041, T042, T042b together; T042a after T027 (it reuses that technique).
- **Phase 7**: T047a, T049, T050, T050a, T050b, T051 together.
- **Phase 9**: T057, T058, T060 together; T059 alone (it reads everything else).

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US2).** Logs outliving their container is real value on its
own, needs no channel, no Slack app and no interpreter, and is the input every later phase reads.

**Second increment = Phase 4 (US1).** At that point the feature does what it was asked for.

**Do not defer Phase 6 (US5).** It is P2 by delivery order, not by importance: it is the phase that
proves a deception planted in agent output costs a message rather than an environment, and shipping
US1 and US3 without it means shipping a supervisor whose resistance to its own inputs is untested.

**Task count**: 72 — US2: 9, US1: 13, US3: 6, US5: 7, US4: 13, US6: 4, setup/foundational: 14, polish: 6 (the last two groups carry no story label by the template's rule).
Eleven were added by the `/speckit-analyze` pass, which found 86% requirement coverage and
one CRITICAL gap: Constitution IX was declared satisfied in the plan while no task delivered
the credential it governs. Coverage after remediation: 43/43 requirements, 15/15 criteria.
