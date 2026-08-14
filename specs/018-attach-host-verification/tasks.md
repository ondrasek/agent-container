# Tasks: Verified Attach, Without a Private Host Key on Disk (Feature 018)

**Input**: [plan.md](./plan.md) · [research.md](./research.md) (R1–R7) · [data-model.md](./data-model.md) ·
[contracts/verification-contract.md](./contracts/verification-contract.md) (C1–C12) ·
[quickstart.md](./quickstart.md) (S1–S11)

**Format**: `- [ ] TNNN [P?] [Story?] description with file path`
`[P]` = parallelisable (different files, no dependency on incomplete work).

**The ordering rule for this feature**: T020 — **prove a substituted key is refused** — comes before
any polish. A pin that never refuses is decoration, and it passes every other test in this file.

**Two things the plan under-counted, found while reading the tree for these tasks:**

1. **Private host key injection is FIVE channels, not one.** `plan.md` names `--host-key`; the tree
   has `up --host-key`, `keys --host-key` (into a *running* container), `redeploy --host-key`, the
   `SSH_HOST_ED25519_KEY_B64` env-file channel (`image/entrypoint.sh`, documented in
   `docs/credentials.md`), and the declarative `host_key` target in `CRED_SSH_TARGETS`. FR-001 —
   *"MUST NOT … inject a private SSH host key"* — covers all five; FR-002 names only the flag. **T023
   is a census with a test, not a checklist**, because the failure mode is one channel surviving and
   nothing looking wrong.
2. **One `known_hosts` per host is a shared-file write, and `deployment_lock` is per `(host, name)`.**
   Two environments on one host can deploy concurrently, each rewriting the same file — a lost
   update, and the loser attaches unverified. T012 owns this.

---

## Phase 1: Setup

- [ ] T001 `container_known_hosts_path(host)` in `bin/agent-container` returning
      `host_state_dir(host) / "known_hosts"` — beside `<name>.port`, using the **existing**
      `host_state_dir` helper (FR-006, research R2, data-model §2). Derived host state, not
      `$XDG_DATA_HOME`: it is re-capturable, so "safe to delete" is true of it
- [ ] T002 [P] State in `docs/layout.md` that derived host state now also holds a tool-owned
      `known_hosts` — **no new location row**, since this is a new file in an existing category
      (research R2). Note *why* it is not beside `runs/`, `egress/` and 014's `inventory/`: those must
      outlive their host, this must die with it

---

## Phase 2: Foundational — blocking prerequisites for every story

- [ ] T003 `known_hosts_entry(address, port, pubkey)` in `bin/agent-container` formatting one
      `[<address>]:<port> <type> <key>` line (data-model §1, FR-005). **The bracket-port form is
      load-bearing and measured** (research R3) — the bare-host form cross-matches, which is exactly
      the defect FR-005 names
- [ ] T004 [P] Unit tests in `bin/tests/test_pure_logic.py` for T003: the bracket form is produced;
      and — asserting the *property*, not the string — that a file holding `[127.0.0.1]:2222` is found
      by `ssh-keygen -F '[127.0.0.1]:2222'` and **not** by `[127.0.0.1]:2223` or bare `127.0.0.1`.
      Test the behaviour `ssh` will rely on, not our formatter's opinion of it
- [ ] T005 `validate_host_pubkey(text)` — accept only a single well-formed OpenSSH public key line;
      **reject empty, whitespace-only, multi-line, and anything containing `PRIVATE KEY`** (C7, C9).
      The last is a tripwire, not paranoia: it is the one string that must never reach this file
- [ ] T006 [P] Unit tests for T005, including a proof-it-can-fail case that neuters the check and
      asserts the guard then rejects a valid-looking input
- [ ] T007 `capture_host_pubkey(rt, host_rec, name)` — read
      `~/.ssh/hostkeys/ssh_host_ed25519_key.pub` from the container **through the runtime**
      (`<runtime> exec … cat`), never `ssh-keyscan` (FR-003, C1, research R7's rejected list). The
      entrypoint already writes that file at 0644, so **nothing in `image/` changes** (research R1)
- [ ] T008 Give T007 a **bounded poll**, modelled on Feature 016's `RUNS_PROBE_TIMEOUT`: the file does
      not exist when the container reports `Up` (016 measured `Up` preceding the entrypoint's first
      write by 0.27–0.57 s; key generation is later still — research R5). A fixed sleep is a bet that
      loses under load
- [ ] T009 [P] Unit test that T008's timeout path returns "nothing captured" rather than an empty
      string, an exception, or a partial value — the three shapes that would each become a written
      blank line downstream
- [ ] T010 `read_pinned_entry(host, name)` / `write_pinned_entry(host, name, entry)` — one line per
      environment in the host's file, replacing that environment's line and **leaving every other
      line byte-identical** (data-model §3)
- [ ] T011 Write via the existing `atomic_write_*` primitive (temp + `os.replace`), not an in-place
      rewrite — a partial write here leaves the file `ssh` reads corrupt for **every** environment on
      the host, not just the one being deployed
- [ ] T012 **Serialise the shared-file write.** `deployment_lock` is per `(host, name)`, so two
      environments deploying concurrently on one host both read-modify-write this file and one update
      is lost — the loser then attaches unverified, silently. Add a **host-scoped** lock (or an
      equivalent compare-and-retry) around T010's read-modify-write
- [ ] T013 [P] Unit test for T012: two interleaved writes for different environments on one host, both
      entries present afterwards. Written as an interleaving, not two sequential calls — sequential
      calls pass with no locking at all
- [ ] T014 Thread `UserKnownHostsFile=<T001 path>` and `StrictHostKeyChecking=yes` into **`ssh_argv`**
      (FR-004, C2, research R6). One place: `attach --print`, the execute path (`os.execvp`) and
      `wizard_handover` all build from `ssh_argv`, so putting the options anywhere else creates a path
      that connects unverified. **Not `accept-new`** — that silently trusts an unpinned host, which is
      today's behaviour and the thing being replaced
- [ ] T015 Add the same two options to **`ssh_probe_argv`** (the dead-session probe). It is a second
      ssh invocation to the same endpoint; leaving it on the operator's default `known_hosts` gives two
      verifications that can disagree about the same container
- [ ] T016 Add `UserKnownHostsFile` and `StrictHostKeyChecking yes` to **`ssh_config_stanza`**.
      Without them `attach --ssh-config` emits a stanza whose `ssh <name>` is unverified — a documented
      path out of the feature, and the operator would have no way to know
- [ ] T017 [P] Tests in `bin/tests/test_command_construction.py` asserting **all three** builders
      carry both options, and that `attach --print` is still byte-for-byte the executed argv (the
      existing FR-010 parity property, which T014 must not break)

---

## Phase 3: User Story 1 — attach verifies what it connects to (P1)

**Goal**: `attach` verifies against a key captured over the runtime, and refuses a changed identity.
**Independent test**: S1 (verified attach, no prompt) then S2 (substituted key → refused).

**Three states, three answers, and they must not be merged** (research R8): **matches** → connect;
**differs** → refuse, unconditionally, no prompt; **absent** → warn, show the fingerprint, say what
accepting cannot detect, and ask. The temptation is one "handle the host key" helper with a mode
argument; T022b says no, because the unconditional refusal is one refactor away from becoming a
question.

- [ ] T018 [US1] Call T007/T010 from **`compose_up_exec`**, after `write_state(...)` and
      `driver_reachable_address(...)` and before the "attach with:" log — the one choke point every
      deploy path passes through. Feature 012's `resolve_egress_declaration` records why: `do_up`
      serves `up` and `apply`, but `do_redeploy` and the wizard call `compose_up_exec` directly
- [ ] T019 [US1] **Capture on every deploy, unconditionally** (research R4, C1). This is what makes
      FR-007 free: the pin is by construction whatever the tool last saw, so a mismatch means the key
      changed *without* a deploy. **Do not add change-attribution state** — the whole point is that
      there is nothing to attribute
- [ ] T020 [US1] **Acceptance test: a substituted host key is REFUSED** (C3, SC-003, S2) in
      `bin/tests/test_acceptance.py`. Replace the container's host key out of band, restart sshd,
      attach, assert failure and that the message names the mismatch. **This test is the feature.**
      Write it before the polish phase — everything else in this file passes with a pin that never
      refuses
- [ ] T021 [US1] Acceptance test: attach to an unmodified environment is verified with **no**
      trust-on-first-use prompt (C2, SC-002, S1), asserted through `attach --print` so no tty is
      needed and the options are checked directly rather than inferred from a connection that worked
- [ ] T022 [US1] Acceptance test: `down --purge` then `up` re-pins **silently** — the entry changed
      and no mismatch warning appears (C4, SC-004, S3). Paired deliberately with T020: the two
      directions must not collapse into each other, and a bug in either looks like the other working
- [ ] T022a [US1] **The unpinned prompt** (FR-013, FR-016, C13, S12): when the environment has no entry,
      `attach` warns, shows the key's **fingerprint**, states that accepting **cannot detect a container
      that was replaced**, and asks. Yes → capture, pin, connect. No → refuse. **Never silent, and never
      worded as verification** — research R8 explains why capture-at-attach is a trust decision and not
      a check, and the wording is the only place the operator learns that
- [ ] T022b [US1] **A mismatch never prompts** (FR-014, C14, SC-010) — refuse unconditionally, terminal
      or not. Implement as a separate branch from T022a, not a shared "ask the operator" helper with a
      flag: one code path that sometimes asks is one refactor away from asking here too
- [ ] T022c [US1] No terminal / non-interactive → **refuse, never an assumed yes** (FR-015, SC-011). An
      operator may pre-accept explicitly on the command line; that acceptance must be **as loud in the
      output as the prompt would have been**, and needs a long flag (the project's short/long rule)
- [ ] T022d [US1] `attach --print` / `--ssh-config` **never prompt** (FR-017) — they connect to nothing.
      With no entry they state that, and state that the emitted command will refuse. Otherwise
      `--print` hands over an argv that fails for a reason the output never mentioned
- [ ] T022e [US1] [P] Tests for T022a–T022d: declining refuses and writes nothing; accepting pins
      exactly one line; the prompt text contains the fingerprint **and** the cannot-detect-replacement
      sentence (assert on the *text* — an exit code cannot tell an honest prompt from a silent capture);
      a mismatch never prompts; stdin-closed refuses; `--print` with no entry says so
- [ ] T022f [US1] [P] Prove the honesty check can fail: soften the prompt wording to drop the
      cannot-detect clause and assert T022e then fails. Without this, the wording assertion is a
      guard nobody has seen refuse anything

---

## Phase 4: User Story 2 — no private host key on the operator's disk (P1)

**Goal**: the tool neither generates, stores, stages nor injects a private SSH host key.
**Independent test**: S5 — `grep -rl 'PRIVATE KEY'` over the state and config directories finds
nothing, after every deployment path that exists.

- [ ] T023 [US2] **THE INJECTION CENSUS — the highest-risk task in this feature.** Enumerate every
      path that can put a private host key anywhere, and express the census as a **test over the
      source**, not a comment. Known today: `up --host-key`; `keys --host-key` (`inject_keys`, into a
      running container over stdin); `redeploy --host-key`; `SSH_HOST_ED25519_KEY_B64`
      (`image/entrypoint.sh`); and the `host_key` target in `CRED_SSH_TARGETS` (declarative
      `.agent-container/`). The failure mode is **one channel surviving** — SC-001 says 100%, and a
      95% removal looks identical to a complete one from every other test here
- [ ] T024 [US2] [P] Prove T023's census guard can fail: reintroduce a fake private-host-key channel
      and assert the guard rejects it
- [ ] T025 [US2] Remove `--host-key` from `up`, `keys` and `redeploy` in `bin/agent-container`, and
      make each **fail with a message saying host identity is captured, not supplied** (FR-002, C10).
      A bare "unrecognized argument" fails this task: an operator who used the flag deserves to learn
      where it went and why
- [ ] T026 [US2] Delete the staging: the `host_key` arm of `stage_ssh_injection`, the `ssh_host_key`
      compose config, `INJECT_HOST_KEY_PATH`, and the `host_key` parameter threaded through
      `compose_up_exec` / `do_up` / `do_redeploy`
- [ ] T027 [US2] Delete `inject_keys`'s host-key arm (the `exec`-and-install-into-a-running-container
      path). `keys --authorized-key` stays — public keys are not the exposure
- [ ] T028 [US2] Remove `host_key` from `CRED_SSH_TARGETS` and from `stage_declared_credentials`, and
      **refuse a spec that declares it** with the FR-002 message. Silently ignoring a declared
      `host_key` would leave an operator believing their key is in use
- [ ] T029 [US2] Delete the injected-key branches from `image/entrypoint.sh` — **both** the
      bind-mounted file and `SSH_HOST_ED25519_KEY_B64` — leaving generate-or-keep. The `.pub`
      derivation and its `chmod 0644` stay exactly as they are; capture depends on them (research R1)
- [ ] T030 [US2] Delete any stale `<state>/<host>/<name>.host_key` on deploy and **say so** (FR-011,
      C11, S7). Not silent: an operator should learn that a plaintext private key left their disk.
      Note the mode was not fixable in place — measured, with a 0600 source and `mode: 0400` declared,
      the file still arrived as the source's mode (research R7)
- [ ] T031 [US2] Drop `.host_key` from `_FLAT_STATE_SUFFIXES` (the 011 flat-state migration) —
      migrating a file we now delete would relocate the exposure rather than remove it
- [ ] T032 [US2] [P] Acceptance test for SC-001: after `up` with **every** flag combination the CLI
      still offers, no file under the state or config directories contains `PRIVATE KEY` (S5)
- [ ] T033 [US2] [P] Unit tests: each removed flag fails with the FR-002 wording (not a generic
      argparse error); a spec declaring `host_key` is refused; a pre-existing `.host_key` is deleted
      and the deletion reported

---

## Phase 5: User Story 3 — the captured key is available for use elsewhere (P3)

**Goal**: the operator can obtain a `known_hosts` line for an environment and use it on another client.
**Independent test**: S11 — the line from the machine-readable interface verifies a second client.

- [ ] T034 [US3] Add the captured entry to `list --json` rows in `bin/agent-container` (FR-010, C12) —
      the **existing** per-environment machine-readable interface, read from local state with no
      daemon call. No new command, and no new column in the human table.
      **This is also the non-TOFU path for a second machine** (research R8): an entry copied from the
      machine that deployed predates what it checks, where a capture accepted at T022a's prompt does
      not. Say so where the operator will read it, or they will take the easier, weaker route
- [ ] T035 [US3] When no key was captured, emit an explicit "not captured" rather than an empty
      string or a missing key (C12, US3 scenario 2). A silent empty result is indistinguishable from a
      captured key that happens to be blank
- [ ] T036 [US3] [P] Test in `bin/tests/test_agent_interface.py`: a captured environment yields a
      parseable `known_hosts` line; an uncaptured one yields the explicit statement

---

## Phase 6: Polish & cross-cutting

- [ ] T037 Capture failure: **warn, state that attach will be unverified, and leave the deploy's exit
      status untouched** (FR-008, C7, SC-008, S9). Write **no** line at all — not a blank one
- [ ] T038 [P] Acceptance test for T037 (S9): deploy succeeds, the warning names the unverified
      attach, and the file gains no entry
- [ ] T039 Skip capture on the headless `--foreground` path, and say in the code why: that branch
      returns after the agent has exited, so there is no container to read and nothing to attach to.
      Recorded rather than left as an unexplained absence, which is how a gap becomes a bug
- [ ] T040 [P] Acceptance test: capture over a **remote** context (FR-009, C8, SC-006, S10). Run
      against a real remote context — SC-006 says verified, not inferred from a local run, because the
      operator's machine shares no filesystem with that daemon
- [ ] T041 [P] Acceptance test: two environments on one host, two entries, **neither key verifying the
      other's connection** (C5, SC-005, S4)
- [ ] T042 [P] Acceptance test: `~/.ssh/known_hosts` is byte-identical before and after `up` +
      `attach --print` (C6, SC-007, S8)
- [ ] T043 Reconcile `docs/threat-model.md`'s 018 row (Constitution, Development Workflow): an
      exposure **removed**, and a new trusted file introduced — the tool-managed `known_hosts` now
      decides whether an attach is trusted, so name what an attacker who can write it gains
- [ ] T044 [P] Update `docs/credentials.md`: remove `--host-key` and `SSH_HOST_ED25519_KEY_B64` from
      the credential channels table and the precedence sentence, and state that host identity is
      **captured, not supplied**
- [ ] T045 [P] Update `docs/shell-integration.md`: `attach` is verified; what a refusal means and what
      to do about it; and that the `--ssh-config` stanza carries the same verification (T016)
- [ ] T046 Confirm the commit is `feat!` — **BREAKING** (Constitution VII). Removing a documented flag
      is breaking, and python-semantic-release under-bumps if the message does not say so
- [ ] T047 Run `scripts/quality-gate.sh` and read its exit code **unpiped**, then
      `pytest -m acceptance bin/tests` (CI-authoritative, excluded from the gate)

---

## Dependencies

```text
Phase 1 (T001–T002)
   └─> Phase 2 (T003–T017)          formatting, capture, the shared-file write, the argv builders
          ├─> Phase 3 US1 (T018–T022f)  capture at deploy + verify + REFUSE + the absent-pin prompt
          │      └─> T020 gates Phase 6
          └─> Phase 4 US2 (T023–T033)   independent of US1; may run in parallel
                 └─> Phase 5 US3 (T034–T036)   needs a captured entry to expose
                        └─> Phase 6 (T037–T047)
```

**US1 and US2 are genuinely independent** — one adds verification, the other removes an exposure —
and both are P1. US2 can land first if that is convenient; nothing in US1 depends on the removal.

**T020 gates the polish phase.** Until a substituted key is provably refused, every other passing test
is consistent with a pin that does nothing.

## Parallel opportunities

- **Phase 1**: T002 alongside T001.
- **Phase 2**: T004, T006, T009, T013, T017 (tests, distinct files) alongside their subjects.
- **Phase 4**: T024, T032, T033 in parallel; T025–T029 all touch `bin/agent-container` (and T029
  `image/entrypoint.sh`) so they serialise.
- **Phase 6**: T038, T040, T041, T042, T044, T045 are independent of each other.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** That is the security property: attach verifies, and a
changed identity is refused. Phase 4 removes the exposure and is the other half of the same change —
ship both in the breaking release, since `--host-key` disappearing is what makes it breaking.

**What "done" looks like here is unusual, and worth restating**: the strongest evidence is an
**absence**. T032 finding no private key and T020 refusing a substituted one are worth more than every
other task passing — because a pin that never refuses and a private key that is merely unused both
look exactly like success.
