# Tasks: Filesystem Layout

**Feature**: 011-filesystem-layout | **Branch**: `011-filesystem-layout` | **Date**: 2026-07-28

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [research.md](./research.md) ·
[data-model.md](./data-model.md) · [contracts/layout-contract.md](./contracts/layout-contract.md) ·
[quickstart.md](./quickstart.md)

**Tests are included** — Constitution V makes hermetic, contract-pinned testing mandatory here,
and this feature changes a pinned on-disk contract.

> **Read this before starting.** Identity is the binding constraint (FR-010, Constitution IV). If
> any container name, port or volume **name** differs by one byte, the feature is wrong no matter
> how tidy the layout became. T001 captures the baseline and T002 turns it into a gate; every
> later phase is verified against them.

---

## Phase 1: Setup & the identity guard

- [X] T001 Capture the identity baseline **before touching anything**: run `./bin/agent-container --self-test` and record the `per_container_volumes`, `all_volume_mounts` and port-corpus values for a name corpus into `specs/011-filesystem-layout/research.md` under a new "R7a — baseline". Everything after this is diffed against it.
- [X] T002 In `bin/tests/test_pure_logic.py`, add an explicit identity-lock test asserting `container_name`, `port_for_name` and **all nine** `per_container_volumes` values for the corpus from T001. It must fail if any **name** changes, while permitting the shell-env **mount string** in `all_volume_mounts` to change (that is US3's job). This is the gate the whole feature is measured against, so write it first.

---

## Phase 2: Foundational (blocking prerequisites)

**All three stories resolve files. They need one seam to resolve them *from*.**

- [X] T003 In `bin/agent-container`, make the project root available to the resolvers: `PROJECT_MARKER` (line ~4558) and `find_project_root` (line ~4592) are defined *after* the four resolvers that will need them (lines ~656–2010). Python resolves names at call time so no reordering is required — confirm that rather than assume it, and add a comment at `find_project_root` recording that the early resolvers depend on it. **If the confirmation fails**, move `PROJECT_MARKER` and `find_project_root` above `env_file_candidates` (line ~656) before starting T004 — a verification task must not be able to strand the design task that follows it.
- [X] T004 In `bin/agent-container`, add a single `project_config_dir(cwd) -> Path | None` helper returning `<project root>/.agent-container` (or `None` when no project root is found), with a doctest. Every resolver in Phase 3 uses it, so it exists once rather than four times.

---

## Phase 3: User Story 1 — One tool directory per project root (P1) 🎯 MVP

**Goal**: everything the tool owns for a project lives in `.agent-container/`; the two
configuration levels use the same filenames; a superseded file is refused, never ignored.

**Independent test**: a consolidated project deploys identically to the old scattered layout;
a project left in the old layout is refused with every offending file named.

### Tests for US1

- [X] T005 [P] [US1] In `bin/tests/test_pure_logic.py`, assert the four-step env chain in order: `.agent-container/<name>.env` → `.agent-container/.env` → `~/.config/agent-container/<name>.env` → `~/.config/agent-container/.env`, and that the bare `./.env` is **not** in it (contract C2, FR-001b).
- [X] T006 [P] [US1] In `bin/tests/test_credentialing.py`, assert canonical-config and sidecar resolution read from `.agent-container/<name>.*` with the user-level fallback and that **the same filename means the same thing at both levels** (FR-001a); and assert plaintext credentials resolve **only** from user level — a `.agent-container/<name>.<provider>.key` MUST NOT be discovered (contract C2b, FR-001f).
- [X] T007 [P] [US1] In `bin/tests/test_cli.py`, assert `-e/--env-file` is **repeatable**, that files stack **in order with later winning**, that explicit files **replace** the discovery chain, and that a missing path fails fast (contract C2a, FR-001d).
- [X] T008 [P] [US1] In `bin/tests/test_credentialing.py`, assert the refusal matrix (contract C3): each superseded `agent-container.<name>.*` name refuses and names its destination — for a `.key` the message names the **user-level** path and the locator sources, since there is no project-local destination (FR-001f); **all** offenders are listed in one message; and a `./.env` refuses **only** when no agent-container env file resolves, staying silent otherwise (FR-001c). The silent case is as load-bearing as the loud one — refusing on a Compose-owned `.env` is its own bug.
- [X] T009 [P] [US1] In `bin/tests/test_pure_logic.py`, assert project-root discovery walks **up** from a nested `cwd` and is location-independent (contract C1, FR-015).
- [X] T009a [P] [US1] In `bin/tests/test_pure_logic.py`, assert the **positive** property directly (FR-002, SC-001): for a consolidated fixture, **no** tool-owned entry remains in the project root — no `agent-container.*` file and no bare `.env` consumed by us. Today this is only implied by the refusal firing; a refusal test passes even if some other tool-owned name were left behind, because it only checks the names it knows to look for.

### Implementation for US1

- [X] T010 [US1] Rewrite `env_file_candidates` in `bin/agent-container` (line ~656) to the four-step chain from T005, dropping `cwd / ".env"`. Update its doctest — it currently asserts `/w/.env` as the first candidate.
- [X] T011 [US1] **Delete** the project-local branch of `discover_apikey_files` (`bin/agent-container` line ~681) — the `(cwd, f"agent-container.{name}.")` half of the two-element loop — leaving **only** the user-level `CONFIG_DIR` lookup. No project-local replacement (FR-001f): `.agent-container/` travels with the repository and Feature 008 settled that the repo holds a locator, never a value. Update the docstring, which documents the project-local path as WINNING.
- [X] T012 [US1] Repoint `canonical_config_dir` (line ~731) and `discover_canonical_config` (line ~744) at `.agent-container/<name>.config/`.
- [X] T013 [US1] Repoint `resolve_sidecar_override` (line ~2010) at `.agent-container/<name>.services.yaml`. Its doctest names both old paths and must be updated.
- [X] T014 [US1] Make `-e/--env-file` repeatable on `up` (line ~5492) and `redeploy` (line ~5676): `list[Path]`, each validated to exist, threaded into `build_compose_model`'s `env_file`. **The compose model already emits a list** (`service["env_file"] = [str(env_file)]`, line ~2263) and Compose applies it in order with later winning — so ordering needs no logic of ours (research R2b). Widen the parameter rather than adding a second one.
- [X] T015 [US1] Add the superseded-layout refusal to `bin/agent-container`: one check over the project root for `agent-container.<name>.*`, listing **every** offender with its destination, called from every command that resolves per-environment files. Include the conditional `./.env` case from FR-001c.
- [X] T016 [US1] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S2 (a consolidated project deploys), S3 (discovery from a subdirectory), S4 (refusal fires on a superseded credential; stays silent when an agent-container env resolves) and S4a (`-e` stacking, order, fail-fast, and **no value leaked into the generated artifact**).

- [X] T016a [US1] In `bin/tests/test_acceptance.py`, assert `-e` works when the host is **not** the default context, reusing the docker-context-as-remote pattern already used for `host env` (line ~1087): register a host on a non-default docker context and deploy with `-e <path outside the project>`. FR-001e's remote parity currently rests on a **docstring** claim — *"env_file is read client-side by compose"* (research R2b) — that nothing has run. That is the same shape as the `opencode run` exit-status assumption in Feature 010, which needed a real probe to get right; if compose ever resolved that path on the daemon instead, `-e` would silently break for every remote deployment.

**Checkpoint**: US1 alone is shippable — the project root is clean and the layering is legible.

---

## Phase 4: User Story 2 — The image sources have a home (P2)

**Goal**: `image/` is the build context, narrow by construction.

**Independent test**: build locally and on a remote host; the transferred context contains only
the image sources; a tree without them fails clearly.

**Depends on**: Phase 2 only. Independent of US1 and US3.

- [X] T017 [P] [US2] In `bin/tests/test_packaging.py`, update the fake-checkout fixture (line ~139) to create `image/Dockerfile`, and assert `_is_repo_checkout` accepts `image/Dockerfile` + `completions/agent-container.bash` and **rejects** a tree with only a root `Dockerfile`.
- [X] T018 [P] [US2] In `bin/tests/test_cli.py`, assert `build` against a tree with no `image/Dockerfile` fails naming what was expected and where (FR-008, contract C4) — not a traceback, and not a "no checkout" message while inside one.
- [X] T019 [US2] `git mv Dockerfile entrypoint.sh .dockerignore image/`.
- [X] T020 [US2] **The high-risk edit.** Update `_is_repo_checkout` in `bin/agent-container` (line ~80) to key on `image/Dockerfile`, update its docstring (which explains *why* the pair was chosen), and update the `AGENT_CONTAINER_REPO` `die` text (line ~2353) that names `"missing Dockerfile/completions/agent-container.bash"`. `REPO_ROOT` resolves **at import, before `die` exists** — a wrong marker cannot report itself and degrades to "no checkout reachable" (research R1).
- [X] T021 [US2] Point the build context at `image/`: `do_build` (line ~2342) and the `"build": {"context": …}` emission in `build_compose_model` (line ~2255).
- [X] T022 [P] [US2] Update `orchestration/compose.yaml` (`build.context`) and `orchestration/agent-container.container` to build from `image/`.
- [X] T023 [P] [US2] Update the shell suites that locate the entrypoint under test — `bin/tests/test_entrypoint.sh`, `test_entrypoint_execution.sh`, `test_entrypoint_tmux_layout.sh` — and the shellcheck targets in `scripts/quality-gate.sh`.
- [X] T024 [US2] Update the cross-file agreement test in `bin/tests/test_pure_logic.py`: it parses `entrypoint.sh` and `Dockerfile` **at the repo root** and will break on the move. That is the test working as intended — repoint it at `image/`.
- [X] T025 [US2] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S5: build local **and remote**, asserting the transferred context contains only `image/`. The remote case matters most — that context crosses the network to another daemon.

---

## Phase 5: User Story 3 — One name, one meaning (P3)

**Goal**: `~/.agent-container` → `~/.agent-env`. The volume **name** does not change.

**Independent test**: shell-env content survives a down/up cycle at the new path, and `dev` can
write it.

**Depends on**: Phase 2. Independent of US1 and US2.

- [X] T026 [P] [US3] In `bin/tests/test_compose.py`, assert the shell-env mount is `agent-container-<name>-shellenv:/home/dev/.agent-env` — **name unchanged, path changed** (contract C5). The identity lock from T002 must still pass.
- [X] T026a [P] [US3] In `bin/tests/test_agent_as_code.py`, pin the delivered-spec contract that FR-012 requires survive the rename: `INJECT_AAC_DIR == "/workspace/.agent-container"` and its **read-only** delivery. FR-012 has no other task — it is currently covered only incidentally, by pre-existing assertions reached through the full-suite run (T037). An FR with no test of its own is invisible the day someone decides the delivered spec should be renamed too.
- [X] T027 [US3] Update the shell-env mount in `all_volume_mounts` (`bin/agent-container` line ~382) and its doctest, which pins the full mount string.
- [X] T028 [US3] In `image/Dockerfile`, create `/home/dev/.agent-env` **dev-owned** in the `mkdir -p` / `chown` / `chmod 0755` lists (line ~184) and update the two comments naming the old path. **Feature 010 proved this is mandatory, not defensive**: a volume mounted at a path the image does not create comes up `root:root` and rootless cannot write it — even under a dev-owned parent.
- [X] T029 [US3] In `image/entrypoint.sh`, update `AGENT_CONTAINER_ENV_FILE` (line ~74), the `mkdir -p` (line ~77) and the block comment describing the persistent shell env.
- [X] T030 [P] [US3] Update the shell-env mount in `orchestration/compose.yaml` and `orchestration/agent-container.container`.
- [X] T031 [US3] Add acceptance coverage in `bin/tests/test_acceptance.py` for quickstart S7: write to `~/.agent-env/env`, down, up, confirm it survived **and that `dev` can write the mount point**.

---

## Phase 6: Polish & cross-cutting

- [X] T032 [P] Write the single authoritative layout map (FR-014) in `docs/` covering all five locations with the settled vocabulary — **project root**, **project config**, **user configuration**, **derived host state**, **image sources** — plus the two configuration levels and the three in-container paths.
- [X] T033 [P] Update `docs/credentials.md`, `docs/execution.md`, `docs/orchestration.md` and `docs/agent-as-code.md` for the new paths, and `README.md` for `image/` and repeatable `-e`.
- [X] T033a [P] Write **operator-facing migration notes** in `docs/` — the one thing a reader needs to act on, since the hard cut breaks every existing project: what moved where (a table), that plaintext project-local keys are **gone** rather than relocated (FR-001f) and what to use instead, that `./.env` is no longer read and `-e` is the replacement, and that the tool refuses rather than guessing. FR-005 makes the *tool* actionable; nothing so far makes the *docs* actionable, and the tool's message is seen only by someone already blocked.
- [X] T034 [P] Update `CLAUDE.md`: the layout statement and the `image/` location. It is at **1999/2000 tokens** — trim an equivalent amount, do not let it drift.
- [X] T035 Verify the vocabulary swept: `grep -rn "project directory" docs/ CLAUDE.md README.md` returns nothing, and superseded path names appear only in migration notes (SC-005, SC-006).
- [X] T036 Run `scripts/quality-gate.sh` and fix everything it reports.
- [X] T037 Run the **full** acceptance suite (`pytest -m acceptance bin/tests`), not just the new tests. This feature changes a shared contract, which is exactly when a pre-existing test still pins the old shape.
- [X] T038 Confirm the identity lock (T002) still passes and diff against the T001 baseline. **If any name differs, the feature is wrong** regardless of everything else.
- [X] T039 Commit with `!`/`BREAKING CHANGE` (research R8). Pre-1.0 this cuts a **minor**, so the version will understate the change — say so in the body, and state the migration in one line an operator can act on.

---

## Dependencies

```text
Phase 1 (T001-T002)   identity baseline + lock — before anything moves
        │
Phase 2 (T003-T004)   the resolution seam
        │
        ├── Phase 3 US1 (T005-T016a) 🎯 MVP — consolidation, env chain, -e, refusal
        ├── Phase 4 US2 (T017-T025)  image sources + the checkout marker
        └── Phase 5 US3 (T026-T031)  shell-env rename + delivered-spec guard
                 │
Phase 6 (T032-T039)   docs, gate, full acceptance, identity re-verify, breaking commit
```

**The three stories are mutually independent** once Phase 2 lands — they touch different
concerns and can be implemented, reviewed and shipped separately.

**File-based serialization**: all `bin/agent-container` tasks are sequential (one file). T016,
T025 and T031 all edit `test_acceptance.py` → sequential relative to each other.

## Parallel execution examples

**Phase 3 tests** — four different files:

```text
T005 (test_pure_logic) ‖ T006 (test_credentialing) ‖ T007 (test_cli) ‖ T009 (test_pure_logic*)
                                    * T005 and T009 share a file — sequential with each other
```

**Across stories** — after Phase 2, three streams run concurrently:

```text
US1 (consolidation)  ‖  US2 (image sources)  ‖  US3 (shell-env)
```

**Phase 6 docs** — T032 ‖ T033 ‖ T034, three different files.

## Implementation strategy

**MVP = Phases 1 + 2 + 3 (US1).** That delivers the change the operator asked about first: one
directory per project root, a legible two-level configuration, and an explicit `-e` escape hatch.

**Increment 2 = Phase 4 (US2)** — carries the build risk and the single highest-risk edit (T020).

**Increment 3 = Phase 5 (US3)** — smallest, most invasive-looking, and genuinely low risk because
the volume name never changes.

**Two tasks can fail the whole feature regardless of the others**: T038 (identity drift) and T020
(a botched checkout marker, which fails *silently*). Treat both as gates, not chores.

## Task summary

| Phase | Story | Tasks | Count |
|---|---|---|---|
| 1 Setup & identity guard | — | T001-T002 | 2 |
| 2 Foundational | — | T003-T004 | 2 |
| 3 User Story 1 | US1 (P1) | T005-T016a | **14** |
| 4 User Story 2 | US2 (P2) | T017-T025 | 9 |
| 5 User Story 3 | US3 (P3) | T026-T031 | 7 |
| 6 Polish | — | T032-T039 | 9 |
| **Total** | | | **43** |

Parallelizable: 17 tasks marked `[P]`.

## Analysis remediation (2026-07-28)

`/speckit-analyze` found 1 CRITICAL, 2 HIGH, 4 MEDIUM, 2 LOW. Outcomes:

| Finding | Severity | Outcome |
|---|---|---|
| N1 — plaintext keys consolidated into the committed directory | CRITICAL | **Dissolved by design change.** Project-local key files dropped entirely (FR-001f), so there is nothing left to guard. T011 became a deletion |
| C1 — pre-upgrade environments untested | HIGH | **Closed as a wording fix.** FR-011/SC-002 restated as derived from FR-010; no separate mechanism exists, so no separate test. Pre-1.0, no layout compatibility offered |
| C2 — `-e` remote parity rests on a docstring | HIGH | **T016a** |
| C3 — FR-012 has no task | MEDIUM | **T026a** |
| C4 — FR-002/SC-001 asserted only indirectly | MEDIUM | **T009a** |
| A1 — no operator-facing migration docs | MEDIUM | **T033a** |
| I1 — T003's verification could strand T004 | MEDIUM | T003 given an explicit fallback |
| D1, A2 | LOW | Not actioned — cosmetic |

Two of these exist because a **claim** stood in for a **check**: C2 (a docstring) and C4 (a
refusal test that would pass for the wrong reason). That is the recurring shape in this
codebase, and it is why both fixes are assertions rather than notes.
