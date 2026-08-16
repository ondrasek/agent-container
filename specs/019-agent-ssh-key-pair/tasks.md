# Tasks: The Agent SSH Key Pair Is Generated In the Container (Feature 019)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R8) · [data-model.md](./data-model.md) ·
[contracts/agent-ssh-key-contract.md](./contracts/agent-ssh-key-contract.md) (C1–C16) ·
[quickstart.md](./quickstart.md) (S1–S17)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**Regenerated** after four clarifications, then extended to close every analyze finding. The previous
list assumed a custom key path and a rewired `core.sshCommand`; both are gone.

**The ordering rule**: **T020 — no private key anywhere — before anything is built on top.** This
feature's headline is an *absence*, and an absence is the one thing a passing `git push` does not
demonstrate.

**Read first. The 018 argument does NOT transfer**, and assuming it does builds the wrong thing:

| | Feature 018 (host key) | Feature 019 (agent SSH key) |
|---|---|---|
| Who proves what | the container proves itself **to us** | the container proves **us** to a remote |
| Verification needs | the **public** key only | **possession of the private** key |
| Therefore | the private key was **removed** | the private key is **relocated**, never removed |

**This is mostly a DELETION.** The conventional path means nothing needs wiring:

| What exists today | Why | Fate |
|---|---|---|
| `core.sshCommand` | the key arrived at an arbitrary `/run` path, so git had to be told | **deleted** — git shells out to `ssh`, which reads `~/.ssh/id_ed25519` |
| `PUSH_RUNTIME` (**11 refs**) | copying an injected 0644 key to a private 0600 location | **deleted** — a self-generated key is 0600 from birth |
| a persistence decision | — | **none needed** — `SSH_DIR` is already the `ssh` volume's mount point |

**Blast radius, grepped rather than recalled**: 4 supplying channels · **5 test files, 59 references**
(`test_credentialing.py` alone has **31**) · 5 docs · **no completions** (`--push-key` was never
completed).

---

## Phase 1: Setup

- [X] T001 `CONTAINER_AGENT_SSH_KEY = "/home/dev/.ssh/id_ed25519"` in `bin/agent-container` — the
      **conventional** identity path, which is already the persisted `ssh` volume (research R4). Not a
      tool-specific filename: being conventional is what makes git, `ssh`, `scp` and `rsync` all use it
      with no wiring
- [X] T002 [P] Amend the `/run` invariant in `CLAUDE.md`: tool-**injected** secrets stay ephemeral;
      **self-generated** material may live on the container's own volume. State the exception — an
      invariant quietly broken is worse than one deliberately changed

---

## Phase 2: Foundational — blocking prerequisites for every story

- [X] T003 Generate the key at `~/.ssh/id_ed25519` (FR-001, FR-003) in `image/entrypoint.sh`, **only when absent**,
      deriving the `.pub` at 0644 and keeping the private half 0600 (C1, C2)
- [X] T004 **Idempotence is load-bearing** (C2): regenerating each boot would silently invalidate the
      operator's registration while every other symptom looked healthy, surfacing days later as a push
      that stopped working
- [X] T005 [P] `bin/tests/test_entrypoint.sh`: a second boot keeps the first boot's key; modes are
      0600/0644
- [X] T006 **DELETE `core.sshCommand`** from `image/entrypoint.sh` — do not rewire it. Git reads the
      conventional identity by itself, and that line existed only to point at an injected `/run` path
- [X] T007 **DELETE all 11 `PUSH_RUNTIME` references** (`image/entrypoint.sh`), including the copy-to-
      0600 dance a self-generated key makes unnecessary
- [X] T008 [P] Test that neither `core.sshCommand` nor `PUSH_RUNTIME` survives — asserted over the
      **executable lines** of the entrypoint, not the whole file, so the comment explaining the removal
      does not fail its own check (the 018 lesson)
- [X] T009 Append the tool's block to `~/.ssh/config` **if the BLOCK is absent** — not merely if the
      file is (FR-014, C13). Content is **explicit**, not default-reliant: `IdentityFile`,
      `IdentitiesOnly yes`, `UserKnownHostsFile ~/.ssh/known_hosts`, `StrictHostKeyChecking accept-new`.
      Only the last is strictly load-bearing (ssh defaults to `ask`, which for a non-interactive agent
      means *fail*); the rest documents the identity, survives a change in ssh's search order, and
      stops ssh offering every key it finds once a second one exists
- [X] T009a Point `--known-hosts` injection at **`~/.ssh/known_hosts`** — the conventional path, already
      on this volume — instead of a private location. That is what lets the config name a default rather
      than a tool-specific path
- [X] T010 [P] Test T009 three ways: no file → block written; file with an agent's own `Host` block →
      block **appended, the agent's entry untouched**; block already present → **nothing changes**
      (idempotent). **The middle case is the one that matters**: "write the file only if absent" would
      leave a config the agent created first without `StrictHostKeyChecking`, so every SSH it attempts
      hangs on a prompt it cannot answer
- [X] T010a **Key generation failure is LOUD** (FR-008, C15, SC-010) — surfaced, and never yielding a
      container that starts, cannot authenticate anywhere, and says nothing. `ssh-keygen` can fail on a
      full or read-only volume, and the agent would otherwise meet it hours later as an inexplicable
      permission denied
- [X] T010b [P] Test T010a: with generation forced to fail, the failure is stated — asserted on the
      message, because a container that started is not by itself evidence of anything
- [X] T011 Capture the public key by **reusing 018's primitive** (research R6) — it already polls,
      validates and refuses an empty read, and a fresh copy would omit exactly those subtleties
- [X] T012 **THE REMOVAL CENSUS**, as a test over the source. Known today: `up --push-key`,
      `redeploy --push-key`, `SSH_PUSH_KEY_B64`, `target: push_key`, `stage_push_injection`'s push arm,
      `INJECT_PUSH_KEY_PATH`, `clone_credential_precheck`. The failure mode is **one channel
      surviving**, indistinguishable from a complete removal by every other test here
- [X] T013 [P] Prove T012's census can fail: reintroduce a fake channel and assert it is rejected

---

## Phase 3: User Story 1 — the container makes its own key (P1)

**Goal**: a key pair the container generated, whose public half the operator can register.
**Independent test**: S3 — register the emitted line on a real repository and push.

- [X] T014 [US1] Capture at deploy, reusing 018's hook site in `compose_up_exec` (C1)
- [X] T015 [US1] Expose it on `list --json` as `agent_ssh_public_key`, following 018's
      `row_known_hosts_entry` (C3, FR-004)
- [X] T015a [US1] `agent-container ssh-key show <name>` — a noun sub-command matching `runs` /
      `egress` / `inventory` (FR-004a). Deliberately **not** part of `keys`, which injects *authorized*
      keys: the agent's own identity and the principals allowed to reach it are different things, and
      one command doing both invites confusing them under pressure
- [X] T016 [US1] The answer must **not depend on the host being reachable** (C3, FR-005, SC-006) — it
      comes from what was captured, and a stopped or unreachable environment is when it is most needed
- [X] T017 [US1] [P] Unit tests for T015/T016: a captured key yields a pasteable line; an uncaptured
      one yields an explicit "not captured", never a silent empty string (SC-004)
- [X] T018 [US1] [P] Acceptance S4 — `down` then `up` keeps the key (C4, SC-003). **The test that
      catches a non-idempotent generator**, whose symptom otherwise arrives days later
- [X] T019 [US1] [P] Acceptance S3 — register the emitted line on a real repository and **push for
      real** (C3, SC-002), plus S2's check that `core.sshCommand` is **empty** — proving the key works
      through the conventional path with nothing wired

---

## Phase 4: User Story 2 — no private key on the operator's disk (P1)

**Goal**: the tool neither takes, stores, stages nor injects an outbound private key.
**Independent test**: S1 — `grep -rl 'PRIVATE KEY'` over state and config finds nothing.

- [X] T020 [US2] **THE GATE: acceptance S1** (FR-010) — after every deploy path the CLI still offers, no file
      under state or config contains `PRIVATE KEY` (SC-001 at 100%). **Land this before Phase 5.**
      With 018's equivalent, the tool then writes no private key anywhere at all
- [X] T021 [US2] Remove `--push-key` from `up` and `redeploy`; each **fails with an explanation**
      (FR-002, C6, SC-007). A bare "unrecognized argument" is a regression, not a removal
- [X] T022 [US2] Delete `stage_push_injection`'s push arm and `INJECT_PUSH_KEY_PATH`; **keep** the
      `known_hosts` arm — it verifies the *forge*, opposite direction, public data (C11)
- [X] T023 [US2] Delete the `SSH_PUSH_KEY_B64` branch from `image/entrypoint.sh`
- [X] T024 [US2] Remove `push_key` from `CRED_SSH_TARGETS` and **refuse** a spec declaring it (C6).
      Silently ignoring it leaves an operator believing their key is in use — the worst outcome
- [X] T025 [US2] Delete any stale `<state>/<host>/<name>.push_key` on deploy and **say so** (C7,
      FR-009), following 018's `remove_stale_staged_host_key`. `--purge` never removed this file, so
      merely ceasing to write it would leave the exposure on every machine that used it
- [X] T026 [US2] [P] Unit tests: each removed channel fails with the FR-002 wording; a declared
      `push_key` is refused; a pre-existing `.push_key` is deleted and the deletion reported
- [X] T027 [US2] **Re-point `test_credentialing.py` (31 refs)** — the staged-path, compose-config and
      `missing_push_key_dies_before_compose` assertions invert; `test_push_key_is_its_own_channel` keeps
      its `known_hosts` half
- [X] T028 [US2] [P] **Re-point `test_agent_as_code.py` (11)** — the declared-target routing
- [X] T029 [US2] [P] **Re-point `test_acceptance.py` (9)** — harness plumbing and the `up(push_key=…)`
      parameter
- [X] T030 [US2] [P] **Re-point `test_entrypoint.sh` (6)** — the injected-key branches become **inert**,
      as 018's did: offer the key, and the container's own identity is unchanged
- [X] T031 [US2] [P] **Re-point `test_execution.py` (2)** — `clone_credential_precheck`
- [X] T032 [US2] [P] `test_credentialing.py:549` is named
      `test_per_repo_deploy_key_is_just_a_narrower_push_key`. Its **intent survives and strengthens**:
      what an operator *could* do by hand is now what the tool does by construction. Re-point it rather
      than deleting a test whose name states this feature's thesis

---

## Phase 5: User Story 3 — told what to register, before the agent needs it (P2)

**Goal**: the operator learns the key and the consequence at deploy time, not from a failed push.

- [X] T033 [US3] A deploy that will use SSH states the public key and that authentication fails until
      it is registered (C8, FR-006, SC-005)
- [X] T034 [US3] The probe: `<runtime> exec … ssh -T <host>`, run **inside the container** (C9,
      research R3). The operator's machine holds no private key — this placement is forced, not chosen
- [X] T035 [US3] The probe targets **only `--repo`'s host**; with no `--repo` there is **no probe** and
      the key is reported *unverified* (research R8). Defaulting to `github.com` would invent a fact and
      send traffic to a host the agent never contacts
- [X] T035a [US3] The probe is **bounded at 10 seconds** (FR-011). A healthy forge answers `ssh -T` in
      under two, and unbounded, "fails soft" would be meaningless because it would never return
- [X] T036 [US3] **The probe FAILS SOFT** (C9, FR-011): denied egress (Feature 012), offline, or a
      forge outage yields `unknown` — never `not-registered` — and **never blocks the deploy**
- [X] T037 [US3] [P] Unit test T036: the deploy's exit status is untouched **and** the report says
      `unknown`. Asserting only the exit status would pass for a build that says nothing at all
- [X] T038 [US3] Registration is **never cached** (data-model §3) — it lives on the forge, and a stored
      "registered" goes stale the moment the operator revokes the key
- [X] T039 [US3] **`agent-container ssh-key rotate <name>`** (FR-015, FR-004a, C13): a new key **without destroying the workspace**,
      stating that the previous registration is dead. `--purge` already rotates by destroying the
      volume — the large hammer, not the intended one, and a suspected compromise is exactly when
      rotation must be cheap
- [X] T040 [US3] [P] Acceptance S14 — rotate, confirm a **different** key, the warning, and an **intact
      workspace**
- [X] T040a [US3] [P] Completions for `ssh-key show|rotate` in both shells, plus the assertion in
      `bin/tests/test_completions.sh` — the completions' command list is pinned to the CLI's by a test,
      so it fails until updated (the lesson 014's `inventory` taught)
- [X] T041 [US3] [P] Acceptance S10 — with egress enforced and the forge undeclared, the deploy
      succeeds and reports that registration could not be confirmed

---

## Phase 6: The honest edges

- [X] T042 **Two-phase SSH clone-on-start** (C10, FR-013): with an SSH `--repo` and no registered key,
      the container **starts without cloning**, says so, and prints the key and the next command.
      Replaces `clone_credential_precheck`, whose premise this feature inverts
- [X] T043 That invocation exits **3** — *pending registration* (FR-013). `1` is generic failure and
      `2` is already the non-TTY refusal, so `3` is the first free value. A test binds the documented
      code to the enforced one
- [X] T044 **The output must forbid the destructive reaction** (FR-013, SC-010): tearing the
      environment down destroys the key awaiting registration, and the retry generates a different one,
      so an agent that reads only the exit status loops forever while invalidating each registration.
      It must say the recovery is **register, then `redeploy`**
- [X] T045 [P] Test T044 on the **wording**, not the exit code alone — the exit code is the thing that
      *causes* the wrong reaction, so it cannot also be the thing that prevents it
- [X] T046 The entrypoint's `git clone … || die` must not fail the boot in that case
      (`image/entrypoint.sh`) — pending is not failure
- [X] T047 The FR-014 relaxation is **scoped to this case alone**; every other empty-workspace refusal
      stands, and a test pins that
- [X] T048 [P] Acceptance S11 — `up` starts without cloning and exits with the pending code; after
      registering, `redeploy` clones
- [X] T049 `--purge` warns that the key is **regenerated** and the previous registration is dead (C5,
      FR-007). Nothing else would say so
- [X] T050 [P] Acceptance S5 + S13 — purge rotates and warns; and an agent's own `~/.ssh/config` edit
      **survives** a `down`/`up`
- [X] T050a [P] **Acceptance S17 — the HTTPS path still works** (FR-012, C16, SC-011): clone and push
      over `GH_TOKEN` alone, no SSH key involved. **Three deletions in this feature sit beside that
      credential helper**, and nothing else would catch collateral damage to it
- [X] T051 [P] Acceptance S12 — the key reaches **only** the repository it was registered for (C12,
      SC-008). The least-privilege gain, invisible in a test that only checks the push works

---

## Phase 7: Polish & cross-cutting

- [X] T052 [P] `docs/credentials.md` — the agent's key is captured, not supplied; the four removed
      channels; the `/run` rule amended for self-generated material
- [X] T053 [P] `docs/execution.md` — SSH clone-on-start is two-phase, what its exit code means, and
      that recreating destroys the key
- [X] T054 [P] `docs/agent-as-code.md` — `target: push_key` is refused, not ignored
- [X] T054a **Document the exit codes** (FR-014a, C14, SC-012) — in `docs/` **and in the CLI's own
      `--help`**: `0` success, `1` failure, `2` refused, `3` pending registration. State both caveats
      rather than leaving them to be discovered: `2` is **shared** with the CLI framework's usage-error
      code so it does not uniquely identify a refusal, and a headless `--foreground` run **propagates
      the agent's** exit code, so there the status is not the tool's at all
- [X] T054b [P] Test that the documented codes ARE the enforced ones — this project has a documented
      habit of a number in prose drifting from the number in code, and an automated caller branching on
      a stale value fails silently
- [X] T055 [P] `docs/agent-interface.md` — the `agent_ssh_public_key` field
- [X] T056 [P] `README.md` — the agent SSH key section, matching 018's treatment of the host key
- [X] T057 [P] Reconcile `docs/threat-model.md`'s 019 row against what was built. Structural guards in
      `bin/tests/` parse that file
- [X] T058 [P] One-line invariant in `CLAUDE.md`; measure against the 2000-token budget and **prune
      before adding**. Report the before/after number
- [ ] T059 Confirm the commit is `feat!` — **BREAKING** (Constitution VII). Four channels removed and
      SSH clone-on-start changes shape **and exit status**
- [ ] T060 Run `scripts/quality-gate.sh` **unpiped**, then the full acceptance tier with **no `-k`
      selection**, and verify quickstart S1–S14 by hand. A selector matching nothing is
      indistinguishable from one whose tests all passed — that happened in this project

---

## Dependencies

```text
Setup (T001–T002)
  └─ Foundational (T003–T013)     ← generation, config, capture, the census
       ├─ US1 (T014–T019)  P1     ← the key exists and is registerable
       └─ US2 (T020–T032)  P1     ← T020 is the gate; independent of US1
            └─ US3 (T033–T041) P2 ← needs a key to tell the operator about
       └─ Edges (T042–T051) after US1+US2
Polish (T052–T060) last
```

**US1 and US2 are independent halves of one change** — one adds a key, the other removes an exposure.
Both P1; US2 can land first.

## Parallel opportunities

- **Phase 2**: T005, T008, T010, T013 alongside their subjects.
- **Phase 3**: T017–T019 independent.
- **Phase 4**: **T028–T032 are one file each and genuinely parallel** — that is why the 59 references
  are split per file rather than left as one task. T021–T025 all touch `bin/agent-container` and
  serialise.
- **Phase 5/6/7**: T037, T040, T041, T045, T048, T050, T051 and every doc task are independent.

## Implementation strategy

**MVP = Phases 1–4.** The container makes its own key, the operator can register it, and no private key
is on disk. US3's prompting, rotation and the two-phase clone are quality-of-life on a feature that is
already correct without them.

**What "done" looks like is mostly invisible.** T020 finding nothing and T051 being **denied** are worth
more than T019's successful push: a push working proves the key *functions*, while those two prove it is
the *right* key, in the right place, with no more reach than it needs. Two will break quietly if got
wrong — T018 (a non-idempotent generator passes every test that runs inside one boot) and T010 (a
config rewrite silently discards the agent's own edits).
