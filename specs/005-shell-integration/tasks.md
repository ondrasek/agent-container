---
description: "Task list for Shell Integration (specs/005)"
---

# Tasks: Shell Integration (emit eval-able env + commands; optional execute)

**Input**: Design documents from `specs/005-shell-integration/` (plan.md, spec.md, research.md, data-model.md, contracts/shell-integration.md, quickstart.md).

**Scope**: a **print mode** for the tool's tool-invoking operations — emit shell-evaluable configuration (command lines + env assignments) to stdout for `eval $(agent-container …)`, with executing kept as the default where it exists. **Host-side CLI only** — no `entrypoint.sh`/container change. **Inherited** (not rebuilt): identity/addressing + host registry/runtime targeting (001), attach/session semantics (004).

**Tests**: INCLUDED (Constitution V; the existing `bin/tests/` suite — Python unit + acceptance).

## ⚠️ Single-file constraint (read before using [P])

Almost all implementation is in the one PEP 723 file **`bin/agent-container`**; there is **no `entrypoint.sh` change** this feature. Tasks that edit `bin/agent-container` are mutually **SEQUENTIAL** — never `[P]` with each other. `[P]` is used ONLY for genuinely separate files: distinct test modules (`test_acceptance.py`, `test_command_construction.py`) and docs. **Note:** the new `bin/tests/test_shell_integration.py` is a single shared file — the per-phase "write failing tests" tasks that target it are `[P]` relative to other files in their phase, but are themselves ordered by their phases (each precedes its story's implementation).

## Format: `[ID] [P?] [Story] Description with file path`

---

## Phase 1: Setup

- [X] T001 [P] Add `bin/tests/test_shell_integration.py` (new module) with hermetic fixtures for the emit/render assertions (reuse the `wiz`/`make_registry` fixtures from `bin/tests/conftest.py`; no live runtime, no ssh/docker).

**Checkpoint**: a place for the shell-integration unit tests exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared **compute-action-then-realize seam** every story consumes — the `ShellAction`, the POSIX renderer + eval-safe quoting, the stdout/stderr/exit discipline, and the non-secret connection descriptor. **No user story can begin until this phase is complete.** All `bin/agent-container` tasks here are sequential (same file); test tasks are `[P]`.

- [X] T002 [P] Write failing tests in `bin/tests/test_shell_integration.py`: a `ShellAction` (env set/unset ops + command lines + comments) renders to POSIX (`export NAME=<q>` / `unset NAME` / space-joined quoted argv / `# …`); quoting is **eval-safe** — feed adversarial tokens (`a b`, `a;rm -rf ~`, `$(touch x)`, `a'b"c`) and assert the re-parsed token is the original with no extra words; the emit helper puts **only** config on stdout and, on any error, leaves stdout **empty** with a **non-zero** exit; the connection descriptor exposes user/address/port/session/context_ref/endpoint and carries **no secret** field; **rendering the same action twice is byte-identical and touches nothing** (SC-005 idempotency / no side effect).
- [X] T003 Add `import shlex` and the `ShellAction` structure (ordered env set/unset ops, command lines as argv lists, comment lines) in `bin/agent-container`. This structure **is** the FR-012 backend-extensible seam — computing the action is separated from realizing it (render vs execute), so a future emit backend (e.g. IaC) can be added without changing the compute layer; no IaC backend is built here.
- [X] T004 Add the **POSIX renderer** (`render_posix`) using `shlex.quote` for every value/token — render `export`/`unset`/command-lines/comments; leave the **fish and pwsh renderers/quoters unwired** (they land in Phase 6, T016); in `bin/agent-container`.
- [X] T005 Add the **emit discipline** helper: buffer the full rendered block and write it to **stdout only on complete success**; route all human messages to **stderr**; on any `die`/failure write nothing to stdout and exit non-zero (eval-safe, FR-003/SC-004); in `bin/agent-container`.
- [X] T006 Add the **connection descriptor** — realized as the resolved arguments the two builders consume (`attach_shell_action(user, host, port, window)` derived from `resolve_attach_target`; `host_env_action(host_rec, endpoint)` from the host record's `context`/`driver`/`address`, endpoint `ssh://[user@]address` with any password **stripped**) — **registry/state only, no probe, no connection** (FR-005); no secret-bearing field is included (Constitution III); in `bin/agent-container`. (Realized as builder args, not a standalone type — the single source that makes print==execute provable and is the FR-012 seam.)

**Checkpoint**: an action can be computed and rendered to eval-safe POSIX with correct stream/exit discipline. User stories can begin.

---

## Phase 3: User Story 1 — Print the attach command instead of running it (Priority: P1) 🎯 MVP

**Goal**: emit the ready-to-run `ssh … -t tmux attach` command (and an SSH-config stanza) to stdout so the operator can run/alias/script it — the `limactl show-ssh` analog. Execute stays the default.

**Independent Test**: `attach <name> --print` on a running container emits a single runnable `ssh … tmux attach` line to stdout (only); running it verbatim attaches to the same session; `--ssh-config` emits a valid `Host` stanza (quickstart A/C).

- [X] T007 [P] [US1] Write failing tests in `bin/tests/test_shell_integration.py` / `bin/tests/test_command_construction.py`: `attach --print` renders exactly the `ssh_argv(...)` command (byte-for-byte parity, from the shared descriptor); stdout carries only that line; `--ssh-config` emits a well-formed single `Host <name>` block (HostName/User/Port/RequestTTY/RemoteCommand); an unknown name / absent container → **empty stdout + non-zero** (never a partial emit).
- [X] T008 [US1] Add `--print` / `--ssh-config` / `--shell posix|fish|pwsh` to `attach`: build the attach `ShellAction` from the connection descriptor and render it (posix) to stdout via the emit helper; `--ssh-config` renders the `Host` stanza; **execute stays the default** (no `--print`); in `bin/agent-container`.
- [X] T009 [P] [US1] Acceptance in `bin/tests/test_acceptance.py`: the printed `attach --print` command, run verbatim in a real shell, reaches the **same** tmux session `attach` reaches (SC-001); the `--ssh-config` stanza appended to a temp SSH config lets `ssh -F <cfg> <name>` attach.

**Checkpoint**: the attach command is printable and eval/alias-able — the shippable MVP.

---

## Phase 4: User Story 2 — Configure the shell to target a host directly (Priority: P2)

**Goal**: `eval $(agent-container host env <name>)` makes the operator's own `docker`/`podman` target a host (no tool wrapper), with a matching plain `--unset`.

**Independent Test**: `eval $(agent-container host env <name>)` sets the env so `docker ps` lists that host's containers; `eval $(agent-container host env --unset)` reverts (quickstart D/F).

- [X] T010 [P] [US2] Write failing tests in `bin/tests/test_shell_integration.py`: `host env <name>` emits `DOCKER_CONTEXT=<ctx>` for a docker host and `CONTAINER_CONNECTION=<ctx>` for a podman host (default); `--endpoint` emits `DOCKER_HOST=ssh://<user>@<addr>` / `CONTAINER_HOST=…`; `--unset` (name-free) emits a **plain** unset of **all four** candidate vars (`DOCKER_CONTEXT`/`DOCKER_HOST`/`CONTAINER_CONNECTION`/`CONTAINER_HOST`) regardless of driver/form (no snapshot/restore); resolution is **registry-only** (no socket/network call issued); an **unknown/unregistered** host → empty stdout + non-zero, while a registered host emits regardless of reachability (clarify Q2).
- [X] T011 [US2] Add the `host env` subcommand (`<name>`, `--endpoint`, `--unset`, `--shell posix|fish|pwsh`): build the env-op `ShellAction` from the host record — default the driver's context reference (`DOCKER_CONTEXT`/`CONTAINER_CONNECTION`, mirroring `driver_runtime_argv`), `--endpoint` the raw endpoint (`DOCKER_HOST`/`CONTAINER_HOST`), `--unset` (name optional/ignored) a plain unset of **all four** candidate vars; registry-only; render via the emit helper; **`host env` is print-only (no execute mode — FR-009 exempts emit-only subcommands)**; in `bin/agent-container` (add under the existing `host` command group).
- [X] T012 [P] [US2] Acceptance in `bin/tests/test_acceptance.py`: `eval $(agent-container host env <name>)` makes the operator's own `docker` list that host's containers (SC-002); `eval $(agent-container host env --unset)` reverts to the default target.

**Checkpoint**: the operator can point their native container tooling at a host by eval, and revert.

---

## Phase 5: User Story 3 — Toggle between print and execute (Priority: P3)

**Goal**: the same operation can print the commands or execute them; execute (the pre-existing behavior) stays default, print is opt-in, and the two are provably identical.

**Independent Test**: for `attach`, execute (no flag) performs the handover while `--print` only emits; the printed command is byte-for-byte what execute runs (quickstart B).

- [X] T013 [P] [US3] Write failing tests in `bin/tests/test_command_construction.py`: the argv `attach` executes and the command `attach --print` emits are derived from the **same** `ShellAction`/descriptor and are byte-for-byte equal; execute (no `--print`) still performs the full ssh handover (and preserves the 004 dead-session probe); the print/execute selection is explicit and predictable.
- [X] T014 [US3] Refactor `attach`'s **execute** path (`cli_attach`) so its ssh argv is built from the **same** connection descriptor / `ShellAction` the print path uses (single source, FR-010) — preserving the exec handover and the 004 `probe_session` dead-session check; in `bin/agent-container`.

**Checkpoint**: print and execute are one definition — no divergence possible.

---

## Phase 6: Cross-Cutting — fish + PowerShell (pwsh) dialects (FR-011)

**Purpose**: ship the fish and pwsh dialects alongside POSIX (both `attach --print` and `host env` honor `--shell fish|pwsh`). POSIX (Foundational) is enough for the MVP; fish and pwsh are additive and shared by US1/US2.

- [X] T015 [P] Write failing tests in `bin/tests/test_shell_integration.py`: `render_fish` emits `set -x NAME <q>` / `set -e NAME` with fish-correct quoting (single-quote escaping only `\` and `'`); `render_pwsh` emits `$env:NAME = <q>` / `Remove-Item Env:NAME` with pwsh-correct quoting (single-quote, doubling a literal `'`) — both eval-safe for adversarial tokens (incl. `$env:x`, `a'b`) in their shell; `--shell fish|pwsh` on `attach --print` and `host env` renders the right form; `--shell <unknown>` → empty stdout + non-zero.
- [X] T016 Wire the **fish renderer** (`render_fish`) and the **pwsh renderer** (`render_pwsh`), completing the T004 seam, and honor `--shell fish|pwsh` across `attach --print` and `host env`; an unrecognized `--shell` value dies with empty stdout + non-zero; in `bin/agent-container`.

**Checkpoint**: POSIX + fish + pwsh all emit eval-correct output from the same action (`eval $(…)` for POSIX/fish, `Invoke-Expression` for pwsh).

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] Update `README.md`: the print/eval surface (`attach --print`/`--ssh-config`, `host env <name>`/`--endpoint`/`--unset`, `--shell`), the `eval $(…)` idiom, and the eval-safety / stdout-only / no-secret invariants (FR-013).
- [X] T018 [P] Update `CLAUDE.md` Decisions (the shell-integration print/emit seam: ShellAction → render posix|fish or execute; attach --print + host env; registry-only; no secret on stdout) within the 2000-token budget — prune before adding (FR-013).
- [X] T019 [P] Add/expand `docs/` (e.g. `docs/shell-integration.md`) with the emit contract, the stream/exit rules, the eval-safety and no-secret invariants, and the host-env dual form (FR-013).
- [X] T020 Run `scripts/quality-gate.sh` (ruff · ty · bandit · vulture · xenon · refurb · self-test · pytest · shell suites) and fix all findings.
- [X] T021 Run quickstart.md Scenarios A–G (local; the real-shell eval + docker-retarget ones on a running container) and record the results in quickstart.md.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → depends on Setup; **blocks all user stories** (the ShellAction + POSIX renderer + emit discipline + descriptor).
- **US1 (P3)** → depends on Foundational. **The MVP** (attach print + ssh-config).
- **US2 (P4)** → depends on Foundational; independent of US1 (a separate emit subcommand).
- **US3 (P5)** → depends on US1 (the attach print path it makes single-source with execute).
- **Fish + pwsh (P6)** → depends on Foundational (the renderer seam); consumed by US1/US2's `--shell`.
- **Polish (P7)** → after the desired stories.

### Within a story

- Write the failing test task first (distinct file → `[P]`), then the sequential `bin/agent-container` implementation task(s) (single-file-sequential).

### Parallel opportunities (distinct files only)

- Setup: T001 alone.
- Foundational: T002 (tests) authored alongside; impl T003→T004→T005→T006 sequential (same file).
- US1: T007 ∥ T009 (distinct test files); impl T008.
- US2: T010 ∥ T012; impl T011.
- US3: T013; impl T014.
- Fish + pwsh: T015 (tests); impl T016.
- Polish: T017 ∥ T018 ∥ T019.

## Implementation Strategy

### MVP first (US1 — print the attach command)

1. Phase 1 Setup → 2. Phase 2 Foundational (ShellAction + POSIX renderer + emit discipline + descriptor) → 3. Phase 3 US1 (`attach --print`/`--ssh-config`) → **STOP & VALIDATE** the printed attach command reaches the same session (quickstart A) → ship. This alone delivers the clearest `limactl show-ssh` analog.

### Incremental delivery

- US1 (attach print, MVP) → US2 (host env) → US3 (print/execute single-source) → fish + pwsh dialects → Polish. Each merges independently; `feat:` commits drive semver (Constitution VII).

## Notes

- `[P]` = distinct files only; every `bin/agent-container` edit is sequential. **No `entrypoint.sh` change** in this feature (host-side only).
- **Zero new Python dependencies** — POSIX quoting uses stdlib `shlex`; the fish and pwsh quoters and the emit seam are small functions (verify no import creep in T020).
- **Load-bearing invariants** (assert across the tiers, not a standalone task): stdout-is-config-only + empty-stdout-and-non-zero-on-error (FR-002/003, T002/T005/T007/T010), eval-safe quoting per dialect (FR-004, T002/T015), **no secret on stdout** (Constitution III, T006), print==execute parity (FR-010, T007/T013).
- **Registry-only, no probe** (clarify Q2): resolution never connects; a registered-but-unreachable host still emits (asserted in T010).
- The **real-shell eval** acceptance (printed attach reaches the same session; `eval $(host env)` retargets `docker`) is the authoritative tier; unit tiers cover rendering/quoting/discipline hermetically.
- Commit after each task or logical group; keep `main` green (Constitution VII).
