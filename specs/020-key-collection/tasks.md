---

description: "Task list for feature 020 — public-key collection, auto-injected"
---

# Tasks: Public-key collection, auto-injected

**Input**: `specs/020-key-collection/` — spec.md, plan.md, research.md, data-model.md, contracts/cli.md, quickstart.md

**Tests**: included, and not optional here. The spec's decisive requirements (FR-006, FR-014, FR-015)
are all cases where *a check can pass while the thing it names is broken*, which is the failure this
feature exists to remove. A contract without a test that can fail is not evidence.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelisable — different file, no dependency on an incomplete task
- **[Story]**: US1–US4 from spec.md

## Path Conventions

Single-file CLI at `bin/agent-container`; hermetic tests in `bin/tests/`; the CI-authoritative
acceptance tier is `pytest -m acceptance bin/tests`. Two images: `image/`, `image-control-plane/`.

**Never edit the tree while the acceptance tier runs** — it re-reads the CLI per invocation.

---

## Phase 1: Settle the unknown (blocks the injection channel)

**Purpose**: One measurement decides whether a later task is a refactor or a bug fix. Doing it first
costs one deploy; doing it last means the commit history describes the change wrongly.

- [X] T001 Deploy an environment over a genuinely remote context with `--authorized-key` using today's
  `configs: {file:}` path, and record in `specs/020-key-collection/research.md` (R4) whether
  `/run/agent-container/authorized_keys` arrives non-empty in the container. A local podman socket does
  NOT exercise this — the daemon must not share the filesystem.
- [X] T002 Based on T001, correct whichever docstring is wrong — `build_compose_model`'s "measured" claim
  or `stage_ssh_injection`'s "transfers over a remote context" claim — in `bin/agent-container` (C22).
  Both cannot stay; the next reader will trust the wrong one.
- [X] T003 If T001 shows `file:` never crossed, open the finding explicitly: `--authorized-key` has been
  silently admitting nobody on remote hosts, and 017's host registry chose `content:` on the strength of
  a claim that was right. Record it in research.md R4 as a **pre-existing defect**, to be committed as
  its own `fix` and not folded into this feature (plan.md Principle VII note).

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: The managed region and the injection channel. Nothing about the collection works, and
FR-006 cannot hold, until the container stops unioning keys onto its volume.

- [X] T004 Define the region sentinels and the replace-not-merge rule as named constants in
  `bin/agent-container` (e.g. `KEY_REGION_BEGIN`, `KEY_REGION_END`), with a comment stating that this
  region is **replaced every boot** and that `~/.ssh/config`'s identically-styled block is
  **write-once** — same idiom, opposite rule (C21).
- [X] T005 Replace the union in `image/entrypoint.sh` with a region rewrite: parse `~/.ssh/authorized_keys`
  into before-region / region / after-region, emit the injected admit set as the new region, preserve
  before and after byte-for-byte, write atomically. Delete the `cat` persisted + injected + env union and
  the `awk 'NF && !seen[$0]++'` write-back that made removal impossible. **Decide and state two things the
  union used to answer implicitly.** (a) A key present **both** inside the region and outside it: the
  outside copy is not the tool's to remove (FR-016), so the region MUST drop its own duplicate rather than
  the operator's line — otherwise a recreate leaves the key authorised anyway and FR-006 fails silently.
  (b) `SSH_AUTHORIZED_KEYS` is tool-supplied per boot, so its content belongs **inside** the region, not
  outside; say so where it is read, or the next reader will assume it persists.
- [X] T006 Refuse rather than repair a malformed region in `image/entrypoint.sh`: a `BEGIN` with no `END`
  (or the reverse) must fail the boot naming the file, never guess a boundary (C17). Guessing risks
  deleting an operator's keys, which is worse than not starting.
- [X] T007 Rewrite section **7e** of `bin/tests/test_entrypoint.sh` from union semantics to region
  semantics. It currently EXECUTES the entrypoint and asserts `"ssh: authorized_keys deduped union has 2
  keys"` — the exact behaviour T005 deletes — and it runs in the quality gate as `shell-entrypoint`, so
  Phase 2 turns the gate red here whether or not anyone planned for it. Worse, its fixture puts `PUB1` in
  **both** the persisted file and the env source, so under a region rewrite the count becomes 3 and the
  failure will look like T005 is broken when in fact the old contract is still pinned. Replace with: a
  pre-existing line outside the region is preserved, the injected set becomes the region, a key removed
  from the injected set is **gone** after the next boot, and the T005(a) duplicate rule holds. Do **not**
  delete the section — a removed assertion leaves nobody watching, which is the reason 7c/7d were inverted
  rather than dropped.

- [X] T008 [P] Apply T005 and T006 to `image-control-plane/entrypoint.sh` (FR-003). A control plane is the
  case this feature exists for, so it must not be the one that lags.
- [X] T009 Move the `ssh_authorized_keys` compose config from `{"file": ...}` to `{"content": ...}` in
  `build_compose_model` in `bin/agent-container`, and reduce `stage_ssh_injection` to producing the
  text rather than a staged path (C18, C19). Keep it on the **config** channel, never `secrets` — public
  keys are public, and labelling them secret misrepresents them (FR-010).
- [X] T010 [P] Add region assertions as a new section **7f** of `bin/tests/test_entrypoint.sh` — which
  **executes** the entrypoint against stubs and already owns `authorized_keys` assembly: exactly one marker
  pair after a rewrite, content outside preserved, malformed region refused, empty region legal (C13, C17,
  C27). **Deliberately not a Python test.** The region parser is shell, and this repo's Python-vs-entrypoint
  precedent is `read_text()` plus a textual assertion — which cannot fail when the shell logic is wrong.
  Grep-the-source coverage for the mechanism the whole feature rests on is the exact defect shape 020
  exists to remove. Extending an already-wired harness also means **no new gate entry is needed**.
- [ ] T011 [P] Add `bin/tests/test_key_collection.py` for the parts that genuinely are Python: collection
  resolution, entry validation, admit-set assembly, and compose-model shape. No assertion in this file may
  stand in for entrypoint behaviour — that belongs in T010's executing section.
- [X] T012 [P] ~~Add a parity test~~ **ALREADY EXISTS — no new test written.** The block carries
  `# SHARED-BLOCK BEGIN authorized_keys (drift-guarded; see test_pure_logic)`, and
  `test_pure_logic._shared_block` already compares it across both entrypoints, with two
  `test_guards_can_fail.py` tests proving the guard can fail. Writing a second parity test would have
  duplicated working infrastructure. What this DID require: `test_guards_can_fail` corrupted the union's
  dedup `awk` to prove the guard fails, and that line no longer exists — the fixture was retargeted onto
  `AK_END_ID`, deliberately staying on a line whose divergence changes who can log in.
- [X] T013 [P] Assert that the generated compose model has **no** `file:` key for `ssh_authorized_keys`
  (C19) and that the entry never appears under `secrets` (C18). **Landed in `bin/tests/test_compose.py`,
  not `test_key_collection.py`** — that file already owns every compose-model assertion, and splitting
  them would leave two places to look. Also inverted the pre-existing
  `test_authorized_keys_maps_to_config` (which required `["file"] == str(ak)`) and retargeted
  `test_no_secret_material_inline` onto Feature 003's `injected_configs`, since public keys can no
  longer carry a "no secrets inline" assertion.

**Checkpoint**: `--authorized-key` still works end to end, and a key removed from the *flags* and
redeployed is gone. FR-006 now holds for flags; the collection is not involved yet.

---

## Phase 3: US1 — Every new environment is reachable from every device (P1)

**Goal**: register keys once; every `up` admits them with no flags.

**Independent test**: three keys registered at user level, `up` naming none, all three private halves
connect (quickstart S1).

- [ ] T014 [US1] Add `authorized_keys_candidates(cwd)` to `bin/agent-container`, returning project-then-user
  paths (`<project>/.agent-container/authorized_keys`, `~/.config/agent-container/authorized_keys`),
  mirroring `settings_candidates` so "where does a project keep its files" keeps one answer. Read whatever
  is there; **require no registration command** (FR-011) — `cat key.pub >> …/authorized_keys` is the whole
  enrolment flow, and no part of this feature may depend on the tool having written the file.
- [ ] T015 [US1] Add `resolve_key_collection(cwd)` to `bin/agent-container` returning the **three distinct
  states** — `None` for undeclared, an empty list for declared-empty, entries otherwise (FR-009,
  Constitution VIII). A reader reports absence; it must not substitute a default.
- [ ] T016 [US1] Add `validate_public_key_line(line)` to `bin/agent-container` using `ssh-keygen -l`, returning
  type, comment and fingerprint. Treat the line as opaque otherwise, so `authorized_keys` options
  (`from=`, `command=`, `restrict`) pass through unharmed.
- [ ] T017 [US1] Refuse a malformed entry in `bin/agent-container` naming the **file and line number**, before
  any runtime call (FR-004, C6, C9). A key that silently fails to admit is a lockout found from the
  device that cannot fix it. Assert **no container exists** afterwards, not just a non-zero exit (SC-004).
- [ ] T018 [US1] Refuse a **private** key in `bin/agent-container` with a message saying explicitly that the
  entry is private, and ensure zero bytes of it reach a staged artifact or log (FR-005, C7, SC-005). This
  is the one mistake here whose cost is not recoverable by editing a file. The test must **grep the state
  directory** for private-key material rather than trusting the refusal (quickstart S5).
- [ ] T019 [US1] Refuse an unreadable or vanished collection file before any runtime call, naming the path
  (FR-012, C8).
- [ ] T020 [US1] Add `resolved_admit_set(cwd, flag_keys)` to `bin/agent-container`: the winning collection
  **plus** `--authorized-key`, order-preserving, de-duplicated, each entry **attributed to its source**
  (FR-008, C11).
- [ ] T021 [US1] Wire `resolved_admit_set` into the `up` and `redeploy` paths in `bin/agent-container` for
  **both roles** (FR-001, FR-003, C5), passing the text to the `content:` config from T009.
- [ ] T022 [US1] Warn once on a **declared-empty** collection, naming the file and saying the environment
  will admit nobody — and do **not** prompt or refuse (FR-017, C4). Leave the **undeclared** path silent:
  today an `up` with no keys is already silent and FR-009 requires that stay true.
- [ ] T023 [P] [US1] Hermetic tests in `bin/tests/test_key_collection.py` for C1 (user-level resolution), C3
  (undeclared ⇒ no config entry at all), C4 (declared-empty honoured and warned), C5 (both roles),
  C10/C11 (statement content and attribution). Include SC-007 — undeclared plus `--authorized-key` alone
  admits exactly that key — and FR-011: a collection hand-written with no tool involvement resolves.
- [ ] T024 [P] [US1] Hermetic tests in `bin/tests/test_key_collection.py` for C6–C9: malformed refused with
  line number, private refused, unreadable refused — each asserting the refusal path **reaches no runtime
  call**, not merely that the exit code is non-zero. The exit code alone would pass on the wrong reason.
- [ ] T025 [P] [US1] Distinguish C3 from C4 in a single test in `bin/tests/test_key_collection.py`: the two
  runs must differ in **output**, not only in behaviour (SC-011). Absent, defaulted and declared-empty
  collapsing into one is precisely what Constitution VIII forbids.
- [ ] T026 [US1] Acceptance test in `bin/tests/test_acceptance.py` for quickstart S1: three registered keys,
  `up` with zero key flags, all three connect (SC-001).

**Checkpoint**: US1 is deliverable. This is the MVP.

---

## Phase 4: US2 — A project can override the collection (P1)

**Goal**: a project narrows the admit set; a client repo does not inherit personal devices.

**Independent test**: user collection of three, project collection of one, deploy inside the project
admits exactly one (quickstart S2).

- [ ] T027 [US2] Make the winning file win **entirely** in `resolve_key_collection` in `bin/agent-container` —
  file-level, not per-key (FR-002). Merging would let a project widen and never narrow, and narrowing is
  the whole point of US2. Comment why this differs from `resolve_settings_key`'s per-key fallthrough:
  a collection is **one** value, a settings file is many.
- [ ] T028 [P] [US2] Hermetic test in `bin/tests/test_key_collection.py` for C2: with both levels declared,
  the project set is admitted and **no entry** of the user set appears.
- [ ] T029 [US2] Acceptance test in `bin/tests/test_acceptance.py` for quickstart S2 (SC-002): the two
  non-project keys are **refused**, asserted by attempted connection rather than by absent lines.

**Checkpoint**: US1 + US2 deliverable.

---

## Phase 5: US3 — Removing a device removes its access (P1)

**Goal**: the requirement the feature turns on. Removal must actually revoke, and nothing the tool
grants may outlive the collection.

**Independent test**: deploy with two keys, remove one, recreate, the removed key is refused
(quickstart S3).

- [ ] T030 [US3] Acceptance test in `bin/tests/test_acceptance.py` for C15/SC-003: remove a key, recreate,
  and assert the **SSH attempt is refused** — not merely that the line is absent. Verify the `ssh` volume
  **survived** the cycle; a pass obtained by destroying the volume proves nothing.
- [ ] T031 [P] [US3] Acceptance test in `bin/tests/test_acceptance.py` for C16/FR-016/SC-010: a line added by
  hand outside the region survives a down/up byte-for-byte, and a collection that becomes **absent**
  empties the region rather than leaving a stale set.
- [ ] T032 [US3] Change `inject_keys` in `bin/agent-container` to write **inside** the managed region rather
  than appending to the file (FR-015, C25). The tool must not create a grant it cannot revoke; today's
  append is removable only by `--purge`, which destroys the environment's own SSH identity.
- [ ] T033 [US3] State at injection time, in `bin/agent-container`, that a `keys add` grant lasts **until the
  next recreate** (FR-015). A changed guarantee that is not said out loud is a trap for whoever relied on
  the old one.
- [ ] T034 [P] [US3] Test in `bin/tests/test_key_collection.py` for C27: after an injection the region markers
  still form **exactly one pair**. An injection that appended past `END` would satisfy "admitted
  immediately" and silently fail "gone after recreate" — the two halves must be pinned separately.
- [ ] T035 [US3] Acceptance test in `bin/tests/test_acceptance.py` for C25/C26/SC-009: a `keys add` grant is
  admitted immediately, refused after a recreate, while a hand-added key survives. Both halves in one
  test — a change asserting only the first will cheerfully delete an operator's keys.
- [ ] T036 [US3] Add `start_collection_drift()` to `bin/agent-container`: on `start`, compare the resolved
  collection against the set the deployment was **created with**, read from the inline `content:` config in
  `host_state_dir(<host>)/<name>.compose.yaml` (data-model.md §5 — no new state; that file is already the
  deployment's existence record). Parse it with `yaml.safe_load`, never a regex. Warn naming the differing
  keys and `redeploy` (FR-013, C23). **Depends on T009**: under `file:` the compose file holds only a path
  to a staged file the next deploy overwrites, so the comparison would be against the current resolution
  rather than the historical one — a comparison with itself. Do **not** re-resolve or re-apply — `start` is a resume, and re-applying would
  silently turn it into a deploy.
- [ ] T037 [P] [US3] Acceptance test in `bin/tests/test_acceptance.py` for C23/SC-008: after removing a key,
  `stop` then `start` still admits the old set **and** the operator was told so. Assert the warning; its
  absence is the defect, since the container's own boot rewrites the region and makes the stale set look
  freshly authoritative.

**Checkpoint**: FR-006 holds against the collection, against `keys`, and against a resume. This is the
first point at which the feature is honest.

---

## Phase 6: US4 — See what will be admitted, before deploying (P2)

**Goal**: the admit set is visible before creation and afterwards, and the "afterwards" reading is
observed rather than assumed.

**Independent test**: a pre-deploy statement names each key; a query names the same set for a running
environment (quickstart S6, SC-006).

- [ ] T038 [US4] Add `report_admit_set()` to `bin/agent-container`: pre-deploy, print `fingerprint  comment`
  per entry plus the source file, never the full blob (FR-007, C10). A fingerprint identifies a device; a
  blob is noise.
- [ ] T039 [US4] Create the `keys` typer subgroup in `bin/agent-container` — `keys show <name>`, `keys ls` —
  following the noun-plus-verb idiom of `ssh-key show` / `host ls` / `runs list` (FR-018, C28). `keys ls`
  MUST report **every** row and survive an unreachable environment, marking that row `undetermined` rather
  than aborting the listing or exiting as if it had examined what it never reached (FR-020, C32).
- [ ] T040 [US4] Move the grant form to `keys add <name> --authorized-key` in `bin/agent-container` (FR-018).
  Required, not cosmetic: `show`, `ls` and `add` all satisfy `validate_name`, so a bare positional beside a
  subcommand would make an environment named `show` permanently unreachable through the group. Add a test
  that the **old bare form no longer grants** (C30) — a silently-still-working old form is how a breaking
  change goes unnoticed until someone depends on both.
- [ ] T041 [US4] Add `report_admit_set_observed()` to `bin/agent-container`: print **projected** (re-resolved)
  and **observed** side by side and state disagreement. Read the observed set with
  `driver_runtime_argv(host_rec) + ["exec", cname, "cat", "/home/dev/.ssh/authorized_keys"]` — the same shape
  Feature 018 uses to capture the public host key — gated on `container_running()`. Report
  observed as **`undetermined`** when the environment is unreachable, never backfilled from the projection
  (FR-014, C24). Share the created-with read with T036 rather than building it twice (data-model.md §5).
  **Three reads, three distinct absence answers**: collection absent ⇒ undeclared; compose file absent ⇒
  no such deployment; environment unreachable ⇒ `undetermined`. Collapsing any pair is the Constitution
  VIII failure. A **stopped** environment is `undetermined`, never empty (FR-019, C31): observation needs a
  running environment, and "nobody is authorised" is a different claim from "we did not look". An empty
  observed set therefore means a *running* environment whose region is genuinely empty.
- [ ] T042 [US4] Do **not** attach admit-set output to `ssh-key show` in `bin/agent-container` (FR-018). That
  command reports the environment's **outbound** identity; merging inbound authorisation into it is the
  direction confusion this spec avoids elsewhere.
- [ ] T043 [P] [US4] Hermetic tests in `bin/tests/test_key_collection.py` for C24: projected and observed both
  printed, disagreement stated, and an unreachable environment yielding `undetermined` — with an explicit
  assertion that the projection never silently fills the observed slot.
- [ ] T044 [P] [US4] Test in `bin/tests/test_key_collection.py` for C31/C32/SC-013/SC-014: a stopped
  environment renders `undetermined` and a running-but-empty region renders empty, distinguishably; and a
  listing with one unreachable environment among several still reports every row and does not exit claiming
  success for the row it never examined.
- [ ] T045 [P] [US4] Test in `bin/tests/test_key_collection.py` for C29 using an environment literally named
  `show`: its admit set is queryable and a key can be granted to it (SC-012). The collision is the reason
  for the layout, so it is the case that must be tested rather than reasoned about.
- [ ] T046 [US4] Acceptance test in `bin/tests/test_acceptance.py` for C12/SC-006: compare the printed
  fingerprints against `ssh-keygen -l` over the container's **actual region** — never against the input
  file, which would compare a projection with itself and report agreement it never checked.
- [ ] T047 [P] [US4] Test the completions and CLI surface in `bin/tests/` for the new `keys` verbs, and assert
  every new short flag has a long form (repo convention, with a test that can fail).

**Checkpoint**: all four stories deliverable.

---

## Phase 7: Polish & Cross-Cutting

- [ ] T048 [P] Acceptance test in `bin/tests/test_acceptance.py` for quickstart S7 / C20: the admit set arrives
  non-empty in a container deployed over a **remote** context. Skip locally, **fail in CI** — the pattern
  017 used for `podman_connection`, because a test that skips everywhere proves nothing.
- [ ] T049 [P] Document the collection in `docs/credentials.md`: the two levels, project-replaces-user, the
  three states, `keys show`/`ls`/`add`, and the recreate-scoped grant.
- [ ] T050 [P] Reconcile `docs/threat-model.md` with this feature (Constitution requirement): one file now
  determines access to every environment, and the mitigations are refuse-early, state-before-deploy and
  warn-on-empty. Name the residual risk rather than implying it was removed.
- [ ] T051 [P] Update `README.md` where it shows repeated `--authorized-key` flags on `up`.
- [ ] T052 Add a one-line pointer to `CLAUDE.md` for feature 020 under the decisions list, and **prune before
  adding** — the file is at ~1950 tokens against a 2000 limit. Measure with a tokenizer; `chars/4`
  understates by ~7%.
- [ ] T053 Note both breaking changes in the release commit body: a `keys` grant no longer survives a
  recreate (FR-015) and `keys <name>` becomes `keys add <name>` (FR-018, C30). Pre-1.0 these are MINOR bumps,
  which is exactly why the version number will not say it and the notes must.
- [ ] T054 If any **new** `bin/tests/test_*.sh` file was added after all (T010 deliberately avoids one),
  wire it into `scripts/quality-gate.sh` in **both** places — a `run_check` line near L178 **and** an entry
  in the failure-message map near L42. A shell test with only one of the two either never runs or fails
  with no guidance; either way the gate reports something other than what happened.
- [ ] T055 Run `scripts/quality-gate.sh` and read its exit code **unpiped**, then run the acceptance tier
  separately (`pytest -m acceptance bin/tests`; on macOS+Lima the work dir must be Lima-shared). Run the
  **full** suite, not just the new tests — a changed contract is exactly when a pre-existing test still
  pins the old shape, and this feature changes two shipped commands.

---

## Dependencies

```
Phase 1 (T001–T003)  ─┐
                      ├─> Phase 2 (T004–T013) ─> Phase 3 US1 ─> Phase 4 US2
                      │                                     └─> Phase 5 US3 ─> Phase 6 US4
                      └── T009 needs T001's answer            (T041 reuses T036)
                                                                             └─> Phase 7
```

- **T001 gates T009.** The channel choice is the same edit either way; only the commit's description
  and separateness depend on the measurement.
- **Phase 2 gates everything.** Until the union is gone, FR-006 cannot hold and a collection would add
  access it could never remove.
- **US2, US3 independent of each other**; both need US1's resolver.
- **US4's T041 reuses T036's comparison** — same projected-vs-created-with mechanism.
- **T030/T035 must not run while the tree is being edited** (acceptance tier re-reads the CLI).

## Parallel opportunities

- Phase 1: none — T001 is a single measurement whose answer the rest reads.
- Phase 2: T007 (rewrite 7e) ∥ T008 (control-plane entrypoint) ∥ T010 ∥ T011 ∥ T012 ∥ T013 after T004–T006.
- Phase 3: T023 ∥ T024 ∥ T025 once T014–T022 land.
- Phase 5: T031 ∥ T034 ∥ T037; T030 first, since it defines the harness the others reuse.
- Phase 6: T043 ∥ T045 ∥ T047.
- Phase 7: T048 ∥ T049 ∥ T050 ∥ T051.

## Implementation strategy

**MVP is Phase 1 + Phase 2 + Phase 3 (US1)** — register once, deploy with no flags. But note what the
MVP does *not* yet include: US3. Shipping US1 alone would mean the collection **adds** access and
does not yet demonstrably remove it, which is the exact asymmetry the spec's checklist flagged. Phase 2
makes removal work; Phase 5 proves it. **Do not release after Phase 3 without Phase 5's tests**, or the
feature will pass its own acceptance criteria while its hardest requirement is unverified.

**Highest-risk area**: the managed region now has **two writers** — deploy-time (T005) and `keys add`
(T032). C27/T034 exists for exactly that, and it is where this feature is most likely to go wrong.
