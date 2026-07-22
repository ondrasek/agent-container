# Implementation Plan: Agent Execution & Session Management

**Branch**: `004-agent-execution` | **Date**: 2026-07-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-agent-execution/spec.md`

## Summary

Own **what runs inside the container and how the operator interacts with it**:
choose **interactive** (agent in a persistent tmux session, driven over SSH) vs
**headless** (agent-as-workload, exits with its result, success not resurrected);
detach/reattach a running session from any machine with an explicit dead-session
report; select the **workspace mode** (persistent / bind / ephemeral); and
**clone-on-start** the working copy using Feature 003's credentials.

Technical approach (see [research.md](./research.md)): one image, one entrypoint,
**branched on `AGENT_CONTAINER_MODE`** — interactive keeps today's sshd+tmux and
launches the chosen agent in a window (optionally seeded with an initial task);
headless runs the agent as PID 1 and exits with its code. `build_compose_model`
gains a **per-mode `restart`** (`unless-stopped` vs `on-failure`) and a
**workspace-mode** mount (named volume / local bind / none→container-layer). The
entrypoint gains **clone-on-start** that picks the credential by URL scheme (SSH
push key for `git@…`, `GH_TOKEN` for `https://…`) and fails fast when an SSH URL
has no injected key. Detach/reattach is inherited; attach gains an explicit
`tmux has-session` probe so a dead session is reported, never silently empty.
Zero new Python dependencies.

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file CLI `bin/agent-container`, PEP
723); container-side flow in `entrypoint.sh` (bash) against the baked agents
(Claude Code / Codex / pi-coding-agent).

**Primary Dependencies**: none new. Typer + questionary + rich (existing CLI); the
container runtime's **Compose v2** (env, `restart:`, volume/bind mounts, `logs`,
attached `up`); `tmux` + `sshd` (baked); `git` (baked, for clone-on-start). Agent
invocation uses each agent's own CLI (baked) — no new tool installs (Constitution
II).

**Storage**: workspace by mode — persistent named volume (identity), a local bind
(local hosts only), or the container's ephemeral layer (nothing mounted). The
other six per-container volumes are unchanged. The initial-task file rides the
ephemeral `injected_configs` channel (003).

**Testing**: hermetic unit (`bin/tests/` — the compose model carries the mode env,
the per-mode `restart`, the workspace mount; bind-on-remote is refused; the agent/
task/repo thread through). `entrypoint.sh` shell suite (the mode branch, the
per-agent invocation map, clone-on-start credential selection, the dead-session
probe). Acceptance (real containers): interactive attach + detach/reattach + the
dead-session report; headless foreground/detached exit code + no-restart-on-
success; workspace persistent/bind/ephemeral; clone-on-start populate + fail-fast.
The **agent actually responding** (SC-001, a real model call) is an **opt-in
tokened** acceptance test — CI never runs it (no cost/secret in CI).

**Target Platform**: the host CLI runs on macOS/Linux; execution works local and
over a remote docker context, except **bind** workspaces (local hosts only,
FR-011).

**Project Type**: single-file CLI + container image (no web/mobile split).

**Performance Goals**: attach presents the session within seconds (SC-001); no
other hot path (execution is one-shot at deploy).

**Constraints**: a bind workspace is refused on a non-local host (FR-011); a
missing clone credential for an SSH-URL clone fails fast (FR-014); every failure
mode is a clear diagnostic, never silent/hung (FR-017). Zero new Python deps
(Constitution VI); the runtime stays immutable — the entrypoint branches, it does
not install (Constitution II).

**Scale/Scope**: single operator; one primary agent per deployment (the three
baked agents); N parallel deployments, each with its own mode/workspace.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after design. Constitution v2.1.0.*

| Principle | Assessment |
|-----------|------------|
| **I. Ephemerality** | ✅ Strengthened. Headless = a disposable one-task container that exits and is not resurrected; the ephemeral workspace forbids durable local state (forces commit-push); a crash-restart lands on a *fresh* session (FR-009), not a resumed one. |
| **II. Least Privilege, Immutable Runtime** | ✅ No runtime installs; the agents + tmux + git are baked. The entrypoint *branches* on a mode env, it does not reshape the runtime. |
| **III. Least Exposure** | ✅ Clone credentials are the scoped 003 channels (SSH `core.sshCommand` / github.com-scoped `GH_TOKEN`); the initial-task file rides the ephemeral inject channel. No new secret surface. |
| **IV. Deterministic Identity** | ⚠️→✅ The workspace **named volume is now conditional** (persistent mode only); name/port and the other six volumes are unchanged, and pre-004 deployments default to persistent — so no existing identity changes. Documented as a refinement, not a breaking change (Complexity Tracking). |
| **V. Durable Spec, Disposable Code** | ✅ Verification is acceptance-weighted (attach works, headless exits with a result, ephemeral is gone, bind refused remote) — checks that survive a re-implementation. |
| **VI. Least Dependencies** | ✅ Zero new Python deps; reuses compose env/restart/mounts + the baked agents. |
| **VII. Continuous Deployment** | ✅ Ships as a `feat` minor (→ 0.8.0) on merge; docs updated in-change (FR-018). |

**Result: PASS.** The one identity refinement (conditional workspace volume) is
recorded in Complexity Tracking; it is additive and preserves every existing
deployment's identity, so no migration is required.

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-execution/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R7 decisions
├── data-model.md        # Phase 1 — execution mode / session / workspace / clone entities
├── quickstart.md        # Phase 1 — validation scenarios A..H
├── contracts/
│   └── execution.md     # Phase 1 — CLI flags, env/inject surface, entrypoint mode contract
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
bin/agent-container          # single-file CLI — the only Python edited:
                             #   • up/redeploy: --mode / --agent / --task / --workspace / --repo / --foreground
                             #   • build_compose_model(): restart param, workspace-mode mount, mode/agent/repo env, task inject
                             #   • workspace-mode resolution (persistent volume / local bind / none) + bind-on-remote refusal
                             #   • conditional workspace volume in per_container_volumes (purge tolerant)
                             #   • attach: explicit `tmux has-session` probe -> clear dead-session report (FR-008)
                             #   • headless foreground launch (attached compose up) vs detached
entrypoint.sh                # container flow (bash):
                             #   • branch on AGENT_CONTAINER_MODE (interactive: sshd+tmux+agent window; headless: agent-as-PID1, exit code)
                             #   • per-agent invocation map (claude/codex/pi) × mode, seed the initial task
                             #   • clone-on-start: URL-scheme credential (git@ -> push key / https -> GH_TOKEN), fail-fast, idempotent
docs/…, README.md, CLAUDE.md # FR-018: execution modes, session behavior, workspace semantics, clone-on-start
bin/tests/
├── test_command_construction.py / test_execution.py  # compose model + flags (mode/restart/workspace/agent/repo; bind refusal)
├── test_entrypoint*.sh                                # mode branch, agent invocation, clone-on-start, dead-session
└── test_acceptance.py                                 # interactive/detach/reattach, headless fg/detached, workspace modes, clone
```

**Structure Decision**: unchanged from 001–003 — one CLI file plus the container
`entrypoint.sh`. No new module. The changes are additive flags + a mode-branched
entrypoint; `bin/agent-container` and `entrypoint.sh` edits are each single-file-
sequential (no `[P]` among same-file tasks).

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|-----------|-----------|--------------------------------------|
| Workspace named volume is **conditional** (persistent mode only) — a refinement of the "seven fixed volumes" identity contract (Constitution IV) | bind and ephemeral modes (FR-010/011/013) require that `/workspace` NOT be a named volume | Always creating the workspace volume would make "ephemeral" and "bind" impossible (or leave an orphan volume). The refinement is additive: pre-004 and default deployments are persistent, so their identity/volume set is unchanged; `--purge` simply tolerates the volume's absence. No value computed for an existing name changes → no migration. |

## Phase 0 — Outline & Research

Complete. See [research.md](./research.md): R1 (mode via entrypoint branch +
per-mode restart), R2 (agent selection + invocation map + task-as-file), R3
(workspace modes = what mounts at /workspace), R4 (clone-on-start, layered
credential by URL scheme — operator-confirmed), R5 (headless foreground/detached =
exit code + logs), R6 (detach/reattach + explicit dead-session probe), R7 (CLI
surface). No NEEDS CLARIFICATION remain (the clone-credential decision was
confirmed as layered-by-URL-scheme).

## Phase 1 — Design & Contracts

Complete. [data-model.md](./data-model.md) defines the execution-mode, agent-
session, headless-run, workspace, and clone-on-start entities + their state/
validation. [contracts/execution.md](./contracts/execution.md) pins the CLI flags,
the env/inject delivery, and the entrypoint mode contract. [quickstart.md](./quickstart.md)
gives runnable scenarios mapped to SC-001…SC-008.

## Phase 2 — Task planning approach (for /speckit-tasks, NOT executed here)

Tasks will be organized by user story: **US1 interactive (MVP)** → US2 detach/
reattach → US3 headless → US4 workspace modes + clone-on-start, on the foundational
mode-branch + compose-model plumbing. Each is an independently testable increment;
`bin/agent-container` and `entrypoint.sh` edits are sequential (single-file). The
real-agent-responds acceptance (SC-001) is opt-in/tokened, outside the CI cost
boundary.
