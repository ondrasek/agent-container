# Tasks: opencode as a Supported Agent

**Feature**: 010-opencode-agent | **Branch**: `010-opencode-agent` | **Date**: 2026-07-27

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [research.md](./research.md) ·
[data-model.md](./data-model.md) · [contracts/agent-contract.md](./contracts/agent-contract.md) ·
[quickstart.md](./quickstart.md)

**Tests are included** — Constitution V (Durable Spec, Disposable Code) makes hermetic,
contract-pinned testing mandatory for this project, and the plan pins two facts that are only
answerable at the acceptance tier.

---

## Phase 1: Setup & load-bearing verification

**These tasks resolve facts the design depends on. They come first because T001a can invalidate
a requirement. T001 is a separate step so a STOP at T001a does not orphan T002.**

- [X] T001 Build a throwaway probe image: copy `Dockerfile` to a scratch path, add `npm i -g opencode-ai`, and build it. This image is the substrate for T001a and T002 and is discarded afterwards. Keep it a standalone step — T001a carries a STOP gate.
- [X] T001a **Probe `opencode run`'s exit status — TWO probes, under a bounded timeout.** (a) **Unconfigured**: run with no credential; record whether it fails at *startup*. (b) **Authenticated, failing task**: configure a credential and run a task that genuinely fails; record the exit status. **FR-005 is about (b), not (a)** — a CLI can exit non-zero on "no provider configured" while still exiting 0 when the model ran and the task failed, so (a) alone would return a false PASS. Run both under a hard timeout: `opencode run` as PID 1 has **no TTY**, and if it waits on one the container hangs forever. **A timeout is a finding, not a retry.** Record all of it in `specs/010-opencode-agent/research.md` under R5. **DECISION GATE**: if probe (b) exits 0 on failure, STOP — amend FR-005 in `specs/010-opencode-agent/spec.md` to say the guarantee is unsatisfiable for opencode, and drop the exit-status assertion from T018. Do NOT weaken the assertion to match the behaviour.
- [X] T002 Probe rootless ownership **and enumerate what opencode actually writes**: mount named volumes at `/home/dev/.config/opencode` and `/home/dev/.local/share/opencode` in the T001 image, confirm `dev` can write to both, then run the agent once and diff `$HOME` to list every path it touched **outside those two mounts** (sessions, logs, caches). The two-location design rests entirely on documentation-derived paths — and this feature has already been burned once by trusting documentation (research R1). Record both results in `specs/010-opencode-agent/research.md` under R3, and if anything material lands outside the two mounts, raise it before Phase 2 rather than absorbing it.

---

## Phase 2: Foundational (blocking prerequisites for all user stories)

**Every user story below depends on this phase. All tasks in `bin/agent-container` are
sequential — it is a single file.**

- [X] T003 [P] Add `&& npm i -g opencode-ai \` to the Layer 3 agent-CLI install in `Dockerfile` (line ~54-57), keeping the existing `npm cache clean --force` last.
- [X] T004 In `Dockerfile` (line ~169-171), add `/home/dev/.config/opencode` and `/home/dev/.local/share/opencode` to the `mkdir -p` and `chmod 0700` lists, and add **`/home/dev/.local`** (the parent, recursively) to the `chown -R dev:dev` list. **Chowning only the leaf is a latent rootless bug**: `mkdir -p` also creates `/home/dev/.local` and `/home/dev/.local/share`, which would stay root-owned — the volume mount still works, so every planned test passes, and anything else writing under `~/.local/share` fails later and silently. The existing layer avoids exactly this by chowning the parent `/home/dev/.config` recursively; update the volume-listing comment at line ~140 from `{claude,codex,pi,shellenv,tmux}` to include both opencode volumes, and add a comment recording the verified paths (config vs. auth store) in the style of the existing `piConfig` note at line ~146.
- [X] T005 Add `"opencode"` to `AGENTS` in `bin/agent-container` (line ~347).
- [X] T006 Add `opencode_volume_name(name)` → `agent-container-<name>-opencode` and `opencode_data_volume_name(name)` → `agent-container-<name>-opencode-data` to `bin/agent-container` (beside the other `*_volume_name` functions, line ~186-210), each with a doctest matching the existing style.
- [X] T007 Extend `all_volume_mounts` and `per_container_volumes` in `bin/agent-container` (line ~246-280) to append `<...>-opencode:/home/dev/.config/opencode` and `<...>-opencode-data:/home/dev/.local/share/opencode`, and update BOTH doctests to the nine-volume lists. `other_container_volumes` derives from `per_container_volumes` and needs no edit — confirm this rather than assume it.
- [X] T008 Update the stale count in the `compose down` comment in `bin/agent-container` (line ~2839, "`--volumes` also drops the seven named volumes") and grep the file for any other numeric volume-count claim.

---

## Phase 3: User Story 1 — Run opencode inside a container (P1) 🎯 MVP

**Goal**: opencode launches interactively in its own window and headlessly as PID 1, is
selectable everywhere an agent is, and both kinds of its state survive recreation.

**Independent test**: create an environment with `--agent opencode` in both modes; confirm it
starts, `attach` lands on its window, the headless exit status propagates, and that **both**
`opencode.json` and the credential from `opencode auth login` survive a down/up cycle.

### Tests for US1

- [X] T009 [P] [US1] In `bin/tests/test_execution.py`, assert `--agent opencode` is accepted, an invalid value is rejected host-side naming all four, and the omitted-`--agent` default is still `claude` (contract C1, FR-001/FR-014).
- [X] T010 [P] [US1] In `bin/tests/test_pure_logic.py`, add the cross-file agreement test: parse `AGENTS` from `bin/agent-container`, the dispatch `case` arms from `entrypoint.sh`, and the `npm i -g` agent packages from `Dockerfile`, and assert the sets describe the same four agents (contract C8, FR-002). **Also assert `docs/execution.md` and the `--agent` help string name exactly the members of `AGENTS`** — FR-002 names four consumers (CLI, container, completions, documentation) and SC-003 claims zero discrepancies *verified*; docs are otherwise checked by nobody. The Dockerfile parse needs a package→agent mapping (`@anthropic-ai/claude-code`→claude, `@earendil-works/pi-coding-agent`→pi, …), which is itself a fourth encoding of the list: make it **explicit and fail loudly on an unmapped package**, or a rename silently drops an agent from the check. Name the failure message so drift says *which* file disagrees.
- [X] T011 [P] [US1] In `bin/tests/test_completions.sh`, assert completing a value for `--agent` offers exactly `claude codex pi opencode` in both bash and zsh (contract C2, FR-013 — net-new, see research R8).

### Implementation for US1

- [X] T012 [US1] In `entrypoint.sh` `run_headless_agent()`, add `opencode) exec opencode run "${t}" ;;` and update the fallback `die` text from `choose claude|codex|pi` to include opencode (line ~443).
- [X] T013 [US1] In `entrypoint.sh`, add a `require_agent_binary()` preflight used by both the headless and interactive paths, applied to the **selected agent only** — never all four at boot, which would make a partially-stale image refuse to start entirely. If `command -v "<agent>"` fails, `die` with a message naming `agent-container redeploy <name>` as the remedy (contract C4, FR-012). Write it once for all four agents — a stale image must never surface as `exec: opencode: not found` / exit 127. Note this **changes the failure mode for the existing three** (exit 127 → actionable `die`), which FR-014 covers as a declared non-regressive exception (see T031).
- [X] T014 [US1] In `entrypoint.sh`, include `opencode` in the interactive tmux agent-window creation and update the window-name comment (line ~513-524) so `attach` lands on it exactly as for the other three (FR-004).
- [X] T015 [US1] Update the `--agent` option help in `bin/agent-container` (line ~5342) to `claude | codex | pi | opencode`.
- [X] T016 [P] [US1] Add `--agent` value completion offering the four names to `completions/agent-container.bash` and `completions/agent-container.zsh` (FR-013; none exists today for any agent).
- [X] T017 [US1] Extend `bin/tests/test_entrypoint_execution.sh` (headless dispatch resolves to `opencode run`, preflight fires with an actionable message when the binary is absent) and `bin/tests/test_entrypoint_tmux_layout.sh` (an `opencode` window is created and named).
- [X] T018 [US1] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S1 (interactive window + `attach`), S2 (headless exit status — assertion shape set by T001's outcome), and S3 (**both** `~/.config/opencode/opencode.json` **and** `~/.local/share/opencode/auth.json` survive down/up). S3 MUST assert both paths — checking only the config file is exactly the failure the original single-volume design would have hidden (research R1). Two further assertions: run the headless case under a **bounded timeout so a hang fails the test rather than stalling CI** (spec edge case: must fail rather than hang), and confirm the **tmux volume is unaffected** — `~/.config` now hosts two sibling volume mounts (tmux + opencode), a first for this project, and the edge case requires opencode's persistence not disturb other agents' state.

**Checkpoint**: US1 alone is a shippable increment — opencode runs, persists, and is selectable.

---

## Phase 4: User Story 2 — Credentials reach opencode by the same rules (P2)

**Goal**: an injected opencode key arrives through Feature 003's existing channels and lands
nowhere new.

**Independent test**: supply a key through the supported channel, confirm the agent can use it,
and confirm the value appears in no project file, no command output, and no tool state.

**Depends on**: Phase 3 (the agent must run before a credential can reach it).

- [X] T019 [P] [US2] In `bin/tests/test_credentialing.py`, assert an injected opencode key is exported into the container environment only — never on argv, never written to either opencode volume, never in emitted output, and **never in the generated `<host>/<name>.compose.yaml` or in container inspect output** (contract C7, FR-010/FR-011). The compose descriptor is precisely where an env-delivered secret leaks; Constitution III is the project's load-bearing gate.
- [X] T020 [US2] In `entrypoint.sh`, beside the existing Codex/pi blocks (line ~297-345), export the provider key from `INJECT_APIKEY_DIR` into the process environment for opencode, with a log line stating the key is ephemeral and neither opencode volume is written. **No `$HOME`/config redirect is needed** — the redirect exists for codex/pi solely to keep an injected key out of their auth store, and an env-delivered key never reaches opencode's (research R6). Do not add one for symmetry.
- [X] T021 [US2] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S7: with a key injected, the value appears nowhere in the project directory or output, and the operator's local key file remains the sole durable copy.

---

## Phase 5: User Story 3 — The volume-set change is safe for existing environments (P2)

**Goal**: nine volumes are created and removed cleanly, and an environment created on the old
seven still tears down.

**Independent test**: tear down a pre-upgrade (seven-volume) environment with the new code and
confirm success with no error; tear down a freshly created one and confirm zero orphans.

**Depends on**: Phase 2. Independent of Phases 3 and 4.

- [X] T022 [P] [US3] In `bin/tests/test_compose.py`, assert the generated compose model declares all nine volumes under `--workspace persistent` and the eight non-workspace volumes under `bind`/`ephemeral` (contract C5, FR-007; the workspace volume stays conditional per Feature 004).
- [X] T023 [P] [US3] In `bin/tests/test_lifecycle.py`, assert teardown of an environment whose volume set is the **old seven** succeeds with the new code — the two absent volumes are tolerated, no error, no migration (contract C5, FR-009). This is the feature's headline risk; do not skip it because the label-based `compose down --volumes` is *expected* to already handle it.
- [X] T023a [US3] Add acceptance coverage for US3 **acceptance scenario 1**, which no other task covers: create an environment on the **old seven-volume** set, upgrade to the new code, then run `up` and `attach` and confirm it still starts and is usable without manual migration (FR-009, SC-005). State explicitly whether a recreate is expected when the compose model gains two volumes — **that answer is the requirement**, not an implementation detail. This is the likelier upgrade path; T023/T024 only cover *teardown*.
- [X] T024 [US3] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S4 (`wipe` leaves zero `agent-container-<name>-*` volumes) and S5 (pre-upgrade teardown succeeds).
- [X] T025 [P] [US3] Sweep every stale statement of the volume count or names and update it (FR-007): `CLAUDE.md` (the Feature 003/004 decision lines naming "Seven per-container volumes"), `docs/execution.md`, `docs/credentials.md`, and any remaining code comments. Finish with `grep -rniE "seven per-container|seven named|seven volumes" .` returning nothing.

---

## Phase 6: Polish & cross-cutting concerns

- [X] T026 [P] Update `docs/execution.md` for four agents: the `--agent` values, opencode's headless form, and its **two** persistent locations with the reason they differ from the other three.
- [X] T027 [P] Add a `docs/credentials.md` note that opencode's injected key is environment-delivered with no redirect, and that its on-volume `auth.json` is operator-interactive-login only.
- [X] T028 Run `scripts/quality-gate.sh` and fix everything it reports (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell suites). The `per_container_volumes` doctest is the self-test's nine-volume contract check.
- [X] T029 Run the full acceptance suite (`pytest -m acceptance bin/tests`) — **not just the new tests**. Changing a shared contract like the volume set is exactly the case where a pre-existing test parses the old shape.
- [X] T029a Record the image size before and after this feature in `specs/010-opencode-agent/research.md`. The spec accepts the growth but requires it be "a conscious cost rather than an accident" — one measured number honours that; an unmeasured assumption does not.
- [X] T030 Run quickstart Tier 3: create, attach, and wipe an environment for each of `claude`, `codex`, `pi` and confirm launch, persistence, and teardown are unchanged (SC-007, FR-014).

---

## Dependencies

```text
Phase 1 (T001, T001a, T002)  ── verification; T001a can amend FR-005
        │                        T001 is split out so a T001a STOP does not orphan T002
Phase 2 (T003-T008)  ── foundational; blocks everything
        │
        ├── Phase 3 US1 (T009-T018)  🎯 MVP
        │        │
        │        └── Phase 4 US2 (T019-T021)   needs a running agent
        │
        └── Phase 5 US3 (T022-T025, T023a)  independent of US1/US2
                 │
Phase 6 (T026-T031) ── after all stories
```

**Story independence**: US1 and US3 can proceed in parallel once Phase 2 lands. US2 requires US1.

**File-based serialization**: T005-T008 all edit `bin/agent-container` → strictly sequential.
T012-T014 all edit `entrypoint.sh` → strictly sequential. T018, T021, T024 all edit
`test_acceptance.py` → sequential relative to each other.

## Parallel execution examples

**Phase 2** — different files:

```text
T003 → T004                  (Dockerfile, sequential)
T005 → T006 → T007 → T008    (bin/agent-container, sequential)
```

The Dockerfile pair and the `bin/agent-container` chain run in parallel with each other.

**Phase 3 tests** — three different files, fully parallel:

```text
T009 (test_execution.py)  ‖  T010 (test_pure_logic.py)  ‖  T011 (test_completions.sh)
```

**Phase 5** — independent of Phase 3/4 entirely:

```text
T022 (test_compose.py)  ‖  T023 (test_lifecycle.py)  ‖  T025 (docs/comment sweep)
T023a (test_acceptance.py) runs after T024 — same file, sequential
```

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** That delivers a runnable, persistent, selectable
opencode — the whole point of the feature — with interactive login as the credential path.

**Increment 2 = Phase 4 (US2)**: declared-credential injection. The agent is useful without it.

**Increment 3 = Phase 5 (US3)**: the upgrade-safety guarantee. Independent of the others, but
**must not be deferred past the release** — it is the contract change this feature carries, and
FR-009 protects every existing environment.

**Three tasks change the spec rather than the code**: T001a (if `opencode run` never reports
failure), T002 (if opencode writes material state outside the two mounts), and T031 (the declared
FR-014 exception). Treat a surprising result in the first two as a finding to record, not an
obstacle to route around.

## Task summary

| Phase | Story | Tasks | Count |
|---|---|---|---|
| 1 Setup & verification | — | T001, T001a, T002 | 3 |
| 2 Foundational | — | T003-T008 | 6 |
| 3 User Story 1 | US1 (P1) | T009-T018 | 10 |
| 4 User Story 2 | US2 (P2) | T019-T021 | 3 |
| 5 User Story 3 | US3 (P2) | T022-T025, T023a | 5 |
| 6 Polish | — | T026-T031 | 7 |
| **Total** | | | **34** |

Parallelizable: 11 tasks marked `[P]`.
- [X] T031 Add a one-line note to FR-014 in `specs/010-opencode-agent/spec.md` recording the T013 preflight as a **deliberate, non-regressive exception**: the existing three agents' failure mode on a stale image improves from exit 127 to an actionable message. Without it, FR-014's "behaviour MUST be unchanged" is ambiguous at review.

---

## Analysis remediation (2026-07-27)

`/speckit-analyze` found 0 CRITICAL and 5 HIGH. Nominal requirement coverage was 100%; effective
coverage was ~76% — the shape of every HIGH was **the task exists, would pass, and the risk
survives**. All twelve findings are folded in above:

| Finding | Where it landed |
|---|---|
| U1 — FR-005 probe measured the wrong failure (false PASS) | T001a, split into two probes |
| U2 — `~/.local` left root-owned, a latent rootless bug | T004 |
| C1 — "upgrade and keep working" untested | **T023a** (new) |
| C2 — headless hang never asserted against | T001a, T018 |
| N1 — key not checked against the compose descriptor (Constitution III) | T019 |
| C3 — docs excluded from the agent-list agreement check | T010 |
| C4 — two-location design rested only on documentation | T002 |
| C5 — sibling mounts under `~/.config` untested | T018 |
| U3 — package→agent mapping is a fourth encoding | T010 |
| A1 — preflight scope ambiguous | T013 |
| I1 — preflight vs FR-014 "unchanged" | **T031** (new) |
| U4 — T002 orphaned by a T001 STOP | T001 split out |
| C6 — image growth unmeasured | **T029a** (new) |
