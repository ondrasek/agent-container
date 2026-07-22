# Implementation Plan: Shell Integration (emit eval-able env + commands; optional execute)

**Branch**: `005-shell-integration` | **Date**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-shell-integration/spec.md`

## Summary

Add a **print mode** to the tool's tool-invoking operations: instead of only
*executing* `ssh … tmux attach` / driving `docker` over a context, the tool can
**emit shell-evaluable configuration** — command lines and environment
assignments — to **stdout only**, so the operator can `eval $(agent-container …)`,
alias it, script it, or drop it into `~/.ssh/config`. Modeled on `limactl
show-ssh`, `eval $(minikube docker-env)`, and `docker context`.

Technical approach (see [research.md](./research.md)): introduce a small
**compute-action-then-realize seam** — every print-capable operation computes a
structured **`ShellAction`** (ordered env set/unset ops + command lines + comment
lines) from the existing **connection facts** (name → user/address/port/session
via 001/004; host → runtime context/connection via 001), then either **renders**
it for a shell dialect (POSIX default, fish, PowerShell/pwsh) or **executes** it. The *same*
`ShellAction` feeds both paths, so print and execute can never drift (FR-010). Two
surfaces expose it: **`attach --print`/`--ssh-config`/`--shell`** (US1/US3, execute
stays the default) and a new **`host env <name>`** emitter (US2, prints by default)
that emits the host's registered runtime reference (`DOCKER_CONTEXT` /
`CONTAINER_CONNECTION`) by default or the raw endpoint (`DOCKER_HOST` /
`CONTAINER_HOST=ssh://…`) under `--endpoint`, plus a plain `--unset`. Output is
**registry-only** (no reachability probe), **eval-safe** (POSIX via stdlib
`shlex.quote`, fish and PowerShell via small dedicated quoters), **stdout-is-config-only**
(humans to stderr), and **empty-stdout+non-zero on any error**. The emit seam is
deliberately backend-extensible (FR-012) so a future IaC emitter can slot in
without reshaping the action layer — but no IaC backend is built here. Zero new
Python dependencies; **host-side CLI only** (no container/`entrypoint.sh` change).

## Technical Context

**Language/Version**: Python ≥ 3.14 (single-file CLI `bin/agent-container`, PEP
723). No container-side code — this feature is entirely host-side (the print/emit
surface + renderers).

**Primary Dependencies**: none new. Typer + questionary + rich (existing CLI);
**stdlib `shlex`** for POSIX quoting (new import, stdlib — no third-party add);
fish and PowerShell quoting are small hand-rolled functions. No runtime/agent/tmux/ssh dependency
is *added* — the point is to emit their commands rather than drive them.

**Storage**: none new. Print reads the existing host **registry**
(`hosts.json`) and per-host **state** (`<host>/<name>.port`) and emits text; it
persists nothing and (per the clarification) does **not** connect.

**Testing**: hermetic unit (`bin/tests/`) — the `ShellAction` renders correct
POSIX, fish, and pwsh; `shlex`/fish/pwsh quoting is eval-safe against adversarial
names/paths; the attach print output is byte-for-byte the argv the execute path
runs (parity); `host env` emits the right var per driver (docker
`DOCKER_CONTEXT` / podman `CONTAINER_CONNECTION`; `--endpoint` →
`DOCKER_HOST`/`CONTAINER_HOST`); unknown host → empty stdout + non-zero; the
`--ssh-config` stanza is well-formed; **no secret-bearing field is ever
rendered**. Acceptance (real containers): the printed attach command, run
verbatim in a real shell, reaches the **same** tmux session the tool's own
`attach` reaches; `eval $(host env)` retargets a real `docker`; `eval` of the
`--unset` form reverts. The "eval-safety on error" invariant is unit-testable
(capture stdout on every error path → empty).

**Target Platform**: the host CLI (macOS/Linux). The emitted commands run in the
**operator's** shell, so their own ssh-agent/`known_hosts`/`~/.ssh/config` handle
the connection (the robustness benefit — no new mechanism).

**Project Type**: single-file CLI (no web/mobile split; no container change).

**Performance Goals**: none — print is string rendering over already-resolved
facts; no hot path, no probe, no I/O beyond reading local registry/state.

**Constraints**: **stdout carries only shell-evaluable text** (FR-001/002);
**empty stdout + non-zero exit on any error** so `eval` runs nothing (FR-003);
**eval-safe quoting** so a name/path/address can never word-split or inject
(FR-004); **no side effects / no connection** — registry-only, idempotent
(FR-005, clarified); **no secret ever on stdout** (Constitution III — only
connection coordinates); **print==execute from one definition** (FR-010). Zero new
Python deps (Constitution VI).

**Scale/Scope**: single operator; the print surface covers the **attach/SSH path**
and **host/runtime targeting** first (US1/US2/US3). Extending print to other
verbs (logs, up) and adding IaC backends are explicitly deferred (the seam admits
them; FR-012).

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after design. Constitution v2.1.0.*

| Principle | Assessment |
|-----------|------------|
| **I. Ephemerality** | ✅ Strengthened. Print stores nothing new and adds no in-container state; it externalizes *how to reach* a container into the operator's own shell/config/scripts — more durable-outside-the-container, not less. |
| **II. Least Privilege, Immutable Runtime** | ✅ Host-side only; the runtime/image is untouched. Strengthened: the operator's own shell runs `ssh`/`docker`, so the tool drives less privileged machinery on their behalf. |
| **III. Least Exposure** | ✅ **Load-bearing gate.** The `ShellAction`/connection descriptor carries **only non-secret connection coordinates** (user, public address, port, session, context name); no push key, token, `known_hosts` content, or API key is ever rendered to stdout. The raw-endpoint form is `ssh://user@address` — a public address already used for attach. Explicit invariant + test. |
| **IV. Deterministic Identity** | ✅ Reinforced. The printed command derives from the *same* deterministic identity (name → port/address/context) as execute, via one authoritative descriptor — no second source, no drift (FR-010). |
| **V. Durable Spec, Disposable Code** | ✅ The parity requirement (print == execute from one `ShellAction`) is exactly this principle; verification is acceptance-weighted (eval reaches the same session) and survives a re-implementation. |
| **VI. Least Dependencies** | ✅ Zero new third-party deps; POSIX quoting reuses stdlib `shlex`; the fish and pwsh quoters and the emit seam are a few small functions, not a framework. |
| **VII. Continuous Deployment** | ✅ Ships as a `feat` minor on merge; docs (README, CLAUDE.md, this spec) updated in-change (FR-013). |

**Result: PASS.** No violations; **Complexity Tracking is empty**. The
compute-action-then-realize seam is not gratuitous abstraction — it is the minimal
structure that makes print==execute provable (FR-010) and admits future backends
(FR-012); it is a small dataclass plus three dialect renderers, justified by two
functional requirements.

## Project Structure

### Documentation (this feature)

```text
specs/005-shell-integration/
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R7 decisions
├── data-model.md        # Phase 1 — ShellAction / dialect / connection descriptor
├── quickstart.md        # Phase 1 — validation scenarios A..G
├── contracts/
│   └── shell-integration.md  # Phase 1 — CLI surface, stdout/stderr/exit contract, emitted formats
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
bin/agent-container          # single-file CLI — the ONLY file edited:
                             #   • ShellAction (env set/unset ops + command lines + comments) — the
                             #     one definition print and execute both consume
                             #   • dialect renderers: render_posix() (shlex.quote) / render_fish() /
                             #     render_pwsh() (dedicated quoters); a --shell posix|fish|pwsh selector
                             #   • emit discipline: stdout-only config, humans->stderr, buffer-then-
                             #     write so any error yields EMPTY stdout + non-zero (eval-safe)
                             #   • connection descriptor: derive user/address/port/session +
                             #     context-ref/endpoint from resolve_attach_target + the host record
                             #   • attach: --print (emit the ssh+tmux ShellAction) / --ssh-config
                             #     (emit a Host stanza) / --shell; execute stays the default
                             #   • `host env <name>`: emit DOCKER_CONTEXT|CONTAINER_CONNECTION
                             #     (default) or DOCKER_HOST|CONTAINER_HOST (--endpoint); --unset
                             #     (plain unset); --shell; registry-only, unknown->empty+nonzero
docs/…, README.md, CLAUDE.md # FR-013: the print/eval contract + which operations expose it
bin/tests/
├── test_shell_integration.py (new)  # renderers, quoting, parity, host-env vars, stdout/exit discipline
├── test_command_construction.py     # attach --print argv parity with the execute path
└── test_acceptance.py               # eval printed attach -> same session; eval host env -> docker retargets
```

**Structure Decision**: unchanged from 001–004 — one CLI file. **No
`entrypoint.sh` change** (this feature is host-side only, the first such feature).
All edits are single-file-sequential in `bin/agent-container`.

## Complexity Tracking

> No Constitution Check violations — this section is intentionally empty.

## Phase 0 — Outline & Research

Complete. See [research.md](./research.md): R1 (compute-action-then-realize seam),
R2 (eval-safe quoting: stdlib shlex + fish/pwsh quoters), R3 (host-env target form by
driver + endpoint fallback, registry-only), R4 (stdout/stderr discipline +
empty-on-error), R5 (attach print/execute toggle), R6 (SSH-config stanza), R7
(dialects: POSIX + fish + PowerShell/pwsh). All clarifications (host-env dual form,
no-probe, plain unset, POSIX+fish, plus pwsh by later direction) are folded in; no
NEEDS CLARIFICATION remain.

## Phase 1 — Design & Contracts

Complete. [data-model.md](./data-model.md) defines the `ShellAction`, the dialect
renderers, the connection descriptor, and the emit-result/exit discipline.
[contracts/shell-integration.md](./contracts/shell-integration.md) pins the CLI
surface, the stdout/stderr/exit contract, the emitted POSIX/fish/pwsh formats, the
eval-safety and no-secret invariants, and the print==execute parity requirement.
[quickstart.md](./quickstart.md) gives runnable scenarios A–G mapped to
SC-001…SC-006. (No `update-agent-context` script exists in this repo — skipped, as
in 001–004.)

## Phase 2 — Task planning approach (for /speckit-tasks, NOT executed here)

Tasks will be organized by user story: **US1 attach print (MVP)** — the
`ShellAction` + POSIX renderer + `attach --print`/`--ssh-config` → **US3 execute
toggle** (the same action, execute vs print; parity test) → **US2 host env**
(the emitter subcommand + endpoint/unset) → **fish + pwsh dialects** + Polish (docs). All
edits are sequential in the single CLI file; test modules and docs are `[P]`. The
real-shell eval acceptance (eval reaches the same session; eval retargets docker)
is the authoritative acceptance tier.
