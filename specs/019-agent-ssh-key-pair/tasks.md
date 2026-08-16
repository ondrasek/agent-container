# Tasks: The Agent SSH Key Pair Is Generated In the Container (Feature 019)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R6) · [data-model.md](./data-model.md) ·
[contracts/agent-ssh-key-contract.md](./contracts/agent-ssh-key-contract.md) (C1–C12) ·
[quickstart.md](./quickstart.md) (S1–S12)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: **T018 — no private key anywhere — before anything is built on
top.** This feature's headline is an *absence*, and an absence is the one thing a passing push does not
demonstrate. If a private key is still being written, everything else working is beside the point.

**Read before starting.** The 018 argument does **not** transfer, and assuming it does is the single
most likely way to build the wrong thing:

| | Feature 018 (host key) | Feature 019 (agent SSH key) |
|---|---|---|
| Who proves what | the container proves itself **to us** | the container proves **us** to a forge |
| So verification needs | the **public** key only | **possession of the private** key |
| Therefore | the private key was **removed** | the private key is **relocated**, never removed |

**Blast radius, grepped rather than recalled** (the lesson 018 paid for, where recall found one channel
and grep found five):

| Surface | Reality |
|---|---|
| Supplying channels | **4**: `up`/`redeploy --push-key`, `SSH_PUSH_KEY_B64`, declarative `target: push_key` |
| Plus | `stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH`, `clone_credential_precheck` |
| Existing tests | **5 files, 59 references** — `test_credentialing.py` alone has **31** |
| Docs | 5: `credentials`, `execution`, `agent-as-code`, `threat-model`, `README` |
| Completions | **none** — `--push-key` was never completed, so unlike 018 there is no completion work |

---

## Phase 1: Setup

- [ ] T001 `CONTAINER_AGENT_SSH_KEY = "/home/dev/.ssh/agent_ssh_ed25519_key"` and its `.pub` in
      `bin/agent-container` — on the persisted `ssh` volume, beside the host key (FR-003, research R4)
- [ ] T002 [P] Amend the `/run` invariant in `CLAUDE.md`: tool-**injected** secrets stay ephemeral;
      **self-generated** material may live on the container's own volume. State the exception rather
      than leaving a contradiction — an invariant quietly broken is worse than one deliberately changed

---

## Phase 2: Foundational — blocking prerequisites for every story

- [ ] T003 Generate the agent SSH key pair in `image/entrypoint.sh` on the `ssh` volume **only when absent**,
      and derive its `.pub` at 0644 (C1, C2). Mirror the host-key block that 018 left in place
- [ ] T004 **Idempotence is load-bearing** (C2, data-model §2): regenerating on every boot would
      silently invalidate the operator's registration while every other symptom looked healthy, and
      the failure would surface days later as a push that stopped working
- [ ] T005 [P] `bin/tests/test_entrypoint.sh`: a second boot keeps the first boot's key; the private
      half is 0600 and the public half 0644
- [ ] T006 Point git at the generated key via `core.sshCommand`, replacing the injected-key path
      (`image/entrypoint.sh`). `IdentitiesOnly=yes` stays — only this key is offered
- [ ] T007 Capture the agent's **public** key through the runtime by **reusing 018's primitive** (research
      R6) — it already polls, validates and refuses an empty read, and a fresh copy would omit exactly
      those subtleties
- [ ] T008 **THE REMOVAL CENSUS**, as a test over the source (T023's shape in 018). Known today:
      `up --push-key`, `redeploy --push-key`, `SSH_PUSH_KEY_B64`, `target: push_key`,
      `stage_push_injection`'s push arm, `INJECT_PUSH_KEY_PATH`, `clone_credential_precheck`. The
      failure mode is **one channel surviving**, which is indistinguishable from a complete removal by
      every other test here
- [ ] T009 [P] Prove T008's census can fail: reintroduce a fake channel and assert the guard rejects it

---

## Phase 3: User Story 1 — the container makes its own key (P1)

**Goal**: a keypair the container generated, whose public half the operator can register.
**Independent test**: S3 — register the emitted line on a real repository and push.

- [ ] T010 [US1] Capture at deploy, reusing 018's hook site in `compose_up_exec` (C1)
- [ ] T011 [US1] Expose the public key on `list --json` as `agent_ssh_public_key`, following 018's
      `row_known_hosts_entry` (C3, FR-004)
- [ ] T012 [US1] The answer must **not depend on the host being reachable** (C3, FR-005, SC-006) — it
      comes from what was captured, and a stopped or unreachable environment is exactly when an
      operator needs it
- [ ] T013 [US1] [P] Unit tests for T011/T012: a captured key yields a pasteable line; an uncaptured one
      yields an explicit "not captured", never a silent empty string
- [ ] T014 [US1] [P] Acceptance S4 — `down` then `up` keeps the key (C4, SC-003). **The test that
      catches a non-idempotent generator**, whose symptom otherwise arrives days later
- [ ] T015 [US1] [P] Acceptance S3 — register the emitted line on a real repository and **push for
      real** (C3, SC-002). Verified, not inferred from configuration
- [ ] T016 [US1] [P] Acceptance S2 — the private half exists **only** in the container, at 0600

---

## Phase 4: User Story 2 — no agent SSH private key on the operator's disk (P1)

**Goal**: the tool neither takes, stores, stages nor injects an outbound private key.
**Independent test**: S1 — `grep -rl 'PRIVATE KEY'` over state and config finds nothing.

- [ ] T017 [US2] Remove `--push-key` from `up` and `redeploy`; each must **fail with an explanation**
      (FR-002, C6, SC-007). A bare "unrecognized argument" is a regression, not a removal — the
      operator who used it had a reason, now served without a key on their disk
- [ ] T018 [US2] **THE GATE: acceptance S1** — after every deploy path the CLI still offers, no file
      under state or config contains `PRIVATE KEY` (SC-001 at 100%). **Land this before Phase 5.**
      Combined with 018's equivalent, the tool then writes no private key anywhere
- [ ] T019 [US2] Delete `stage_push_injection`'s push arm and `INJECT_PUSH_KEY_PATH`; keep the
      `known_hosts` arm — it verifies the **forge**, opposite direction, public data (C11)
- [ ] T020 [US2] Delete the `SSH_PUSH_KEY_B64` branch from `image/entrypoint.sh`
- [ ] T021 [US2] Remove `push_key` from `CRED_SSH_TARGETS` and **refuse** a spec that declares it
      (C6). Silently ignoring it leaves an operator believing their key is in use — the worst of the
      three outcomes
- [ ] T022 [US2] Delete any stale `<state>/<host>/<name>.push_key` on deploy and **say so** (C7,
      FR-009), following 018's `remove_stale_staged_host_key`. `--purge` never removed this file, so an
      upgrade that merely stopped writing it would leave the exposure on every machine that used it
- [ ] T023 [US2] [P] Unit tests: each removed channel fails with the FR-002 wording; a declared
      `push_key` is refused; a pre-existing `.push_key` is deleted and the deletion reported
- [ ] T024 [US2] **Re-point the 59 existing references across 5 files.** Each must be updated, never
      deleted — a changed contract is exactly when a pre-existing test still pins the old shape:
      · `test_credentialing.py` (**31**) — the staged-path, compose-config and
      `missing_push_key_dies_before_compose` assertions invert; `test_push_key_is_its_own_channel`
      keeps the `known_hosts` half
      · `test_agent_as_code.py` (11) — the declared-target routing
      · `test_acceptance.py` (9) — harness plumbing plus the `up(push_key=…)` parameter
      · `test_entrypoint.sh` (6) — the injected-key branches become **inert**, as 018's did
      · `test_execution.py` (2) — `clone_credential_precheck`
- [ ] T025 [US2] [P] `test_credentialing.py:549` is named
      `test_per_repo_deploy_key_is_just_a_narrower_push_key`. Its **intent survives and strengthens**:
      what was a thing an operator *could* do by hand is now what the tool does by construction.
      Re-point it to assert that, rather than deleting a test whose name states this feature's thesis

---

## Phase 5: User Story 3 — told what to register, before the agent needs it (P2)

**Goal**: the operator learns the key and the consequence at deploy time, not from a failed push.

- [ ] T026 [US3] A deploy that will push over SSH states the public key and that pushes fail until it
      is registered (C8, FR-006, SC-005)
- [ ] T027 [US3] The registration probe: `<runtime> exec … ssh -T <forge>`, run **inside the
      container** (C9, research R3). The operator's machine holds no private key and so cannot answer —
      this placement is forced, not chosen
- [ ] T028 [US3] **The probe FAILS SOFT** (C9, FR-011): a forge that cannot be reached yields
      `unknown`, never `not-registered`, and **never blocks or fails the deploy**. Denied egress
      (Feature 012), offline, or a forge outage are all this case
- [ ] T029 [US3] [P] Unit test T028 with an unreachable forge: the deploy's exit status is untouched
      **and** the report says `unknown`. Asserting only the exit status would pass for a build that
      says nothing at all
- [ ] T030 [US3] Registration is **never cached** (data-model §3) — it lives on the forge, and a stored
      "registered" goes stale the moment the operator revokes the key, at which point the tool would be
      assuring them of something false
- [ ] T031 [US3] [P] Acceptance S10 — with egress enforced and the forge undeclared, the deploy
      succeeds and reports that registration could not be confirmed

---

## Phase 6: The honest edges

- [ ] T032 **Two-phase SSH clone-on-start** (C10, FR-013): with an SSH `--repo` and no registered key,
      the container **starts without cloning**, says so, and prints the key and the next command.
      Replaces `clone_credential_precheck`, whose premise this feature inverts
- [ ] T033 The entrypoint's `git clone … || die` must not fail the boot in that case
      (`image/entrypoint.sh`) — pending is not failure
- [ ] T034 The relaxation of FR-014 is **scoped to this case alone**. Every other empty-workspace
      refusal stands, and a test pins that: the point of FR-014 is that nobody receives a *silently*
      useless container, and here the container announces itself
- [ ] T035 [P] Acceptance S11 — `up` starts and does not clone; after registering, `redeploy` clones
- [ ] T036 `--purge` warns that the key is **regenerated** and the previous registration is dead (C5,
      FR-007). Nothing else in the system would say so
- [ ] T037 [P] Acceptance S5 — purge, redeploy, and confirm both the new key and the warning
- [ ] T038 [P] Acceptance S12 — the key reaches **only** the repository it was registered for (C12,
      SC-008). The least-privilege gain, and invisible in a test that only checks the push works

---

## Phase 7: Polish & cross-cutting

- [ ] T039 [P] `docs/credentials.md` — the outbound key is captured, not supplied; the four removed
      channels and why; the `/run` rule amended for self-generated material
- [ ] T040 [P] `docs/execution.md` — SSH clone-on-start is two-phase, and why it cannot be otherwise
- [ ] T041 [P] `docs/agent-as-code.md` — `target: push_key` is refused, not ignored
- [ ] T042 [P] `README.md` — the agent SSH key section, matching 018's treatment of the host key
- [ ] T043 [P] `docs/agent-interface.md` — the new `agent_ssh_public_key` field on `list --json`
- [ ] T044 [P] Reconcile `docs/threat-model.md`'s 019 row against what was built — the last
      private-key write site removed, a grant narrowed, and a signing key now on a volume that
      outlives its container. Structural guards in `bin/tests/` parse that file
- [ ] T045 [P] One-line invariant in `CLAUDE.md`; measure against the 2000-token budget and **prune
      before adding**. Report the before/after number
- [ ] T046 Confirm the commit is `feat!` — **BREAKING** (Constitution VII). Four channels removed and
      SSH clone-on-start changes shape; semantic-release under-bumps if the message does not say so
- [ ] T047 Run `scripts/quality-gate.sh` **unpiped**, then the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S12 by hand. A selector matching nothing is
      indistinguishable from one whose tests all passed — that happened in this project

---

## Dependencies

```text
Setup (T001–T002)
  └─ Foundational (T003–T009)      ← generation, capture, the removal census
       ├─ US1 (T010–T016)  P1      ← the key exists and is registerable
       └─ US2 (T017–T025)  P1      ← T018 is the gate; independent of US1
            └─ US3 (T026–T031) P2  ← needs a key to tell the operator about
       └─ Edges (T032–T038) after US1+US2
Polish (T039–T047) last
```

**US1 and US2 are independent halves of one change** — one adds a key, the other removes an exposure —
and both are P1. US2 can land first.

## Parallel opportunities

- **Phase 2**: T005, T009 alongside their subjects.
- **Phase 3**: T013–T016 are independent.
- **Phase 4**: T023, T025 in parallel; T017/T019/T020/T021/T022 all touch `bin/agent-container` (T020
  the entrypoint) and serialise. **T024 is large and should be split per file.**
- **Phase 6/7**: T035, T037, T038 and every doc task are independent.

## Implementation strategy

**MVP = Phases 1–4.** The container makes its own key, the operator can register it, and no private key
is on disk. US3's prompting and the two-phase clone are quality-of-life on top of a feature that is
already correct without them.

**What "done" looks like is mostly invisible.** T018 finding nothing and T038 being *denied* are worth
more than T015's successful push — because a push working proves the key functions, while those two
prove it is the *right* key, held in the right place, with no more reach than it needs. T014 is the
one that will break quietly: a non-idempotent generator passes every test that runs inside one boot.
