# Data Model: Agent Execution & Session Management (Feature 004)

Entities are the **execution mode**, the **agent session**, the **headless run**,
the **workspace** (three modes), and **clone-on-start**. No persistent schema is
added — the model is deploy-time config threaded into the compose model + a mode-
branched entrypoint. Inherited unchanged: host/compose (001/002), the six non-
workspace per-container volumes and the name/port identity (Constitution IV), and
the 003 credentials.

## Execution mode

How the agent runs. Selected at deploy (`--mode`, default `interactive`), carried
as `AGENT_CONTAINER_MODE`, and it also sets the compose `restart:` policy.

| Mode | Container workload | `restart:` | Session |
|------|--------------------|-----------|---------|
| **interactive** (default) | sshd + tmux `main`; the chosen agent launched in a window (US1), PID 1 stays alive | `unless-stopped` (kept alive / restarted, FR-001/005) | a persistent attachable session (US1/US2) |
| **headless** | the chosen agent runs as PID 1's workload; the container **exits with the agent's code** (FR-002) | `on-failure` (success exits and is **not** resurrected; a failure follows policy — FR-002/005) | none (a run, not a session) |

Modes are **independently selectable** from workspace mode; any combination is
permitted and never silently altered (FR-016 — guidance may note headless↔ephemeral
and interactive↔persistent as natural pairings).

## Agent (per-deployment primary)

| Field | Value |
|-------|-------|
| `agent` | `claude` (default) \| `codex` \| `pi` — one primary agent per deployment (`--agent`) |
| interactive invocation | launch the agent in its tmux window, optionally seeded with the initial task |
| headless invocation | the agent's non-interactive form + the task (e.g. `claude -p "<task>"`, `codex exec "<task>"`, pi's non-interactive form) |
| `task` | optional initial/headless task (`--task <text\|@file>`), delivered as an **injected file** (003's channel; never on argv/env) — read by the entrypoint (FR-003) |

The operator may still launch additional processes manually inside an interactive
session; the `agent` names only the *primary* workload.

## Agent session (interactive)

The persistent terminal session the interactive agent runs in.

| Property | Value |
|----------|-------|
| identity | the canonical tmux session `main` (per-deployment; reached via the deployment's address + published port) |
| decoupling | survives operator disconnect (FR-006/SC-002) — tmux, not tied to the SSH connection |
| reattach | SSH back to `main` from **any** machine (FR-007/SC-003) — inherited from 001/002 attach |
| dead-session | attach probes `tmux has-session -t main`; if absent → present a fresh session OR clearly report "nothing running" — never a silent empty attach (FR-008) |
| crash-restart | lands on a **fresh** session (the prior is not resumed, FR-009) — consistent with the entrypoint's existing `has-session` guard |

## Headless run

| Property | Value |
|----------|-------|
| launch | **detached** (default: `up` returns; the container runs and exits) or **foreground** (`up --foreground`: streams the run, returns control on completion) — FR-004 |
| result | the **container exit code** (success/failure distinguishable, FR-002/SC-004) + `logs` output — both retrievable afterward; `list` surfaces the exited status/code |
| restart | `on-failure` — a **success** is never auto-restarted (SC-004); a **failure** follows the deployment's restart policy (FR-005) |

## Workspace (three modes)

Selected at deploy (`--workspace`, default `persistent`) — determines what is
mounted at `/workspace`.

| Mode | Mounted at `/workspace` | Durability | Clone-on-start | Host constraint |
|------|-------------------------|------------|----------------|-----------------|
| **persistent** (default) | the named `agent-container-<name>-workspace` volume | survives recreation (FR-012/SC-006) | yes, if `--repo` set & empty | any host |
| **bind** | `<local-abs-dir>:/workspace` (operator's filesystem) | edits appear on the local FS (FR-010) | no (already present) | **local hosts only** — refused with a clear message on a non-local host (FR-011/SC-007) |
| **ephemeral** | **nothing** (the container's writable layer) | does **not** survive teardown (FR-013/SC-006) | yes, if `--repo` set | any host |

**Identity nuance (Constitution IV)**: the workspace named volume exists **only**
in persistent mode; the other six volumes and the name/port are unchanged.
`--purge`/`wipe` tolerate its absence. Pre-004 / default deployments are
persistent → identity unchanged, no migration.

**Durability is made explicit (FR-015)**: persistent and bind tolerate uncommitted
local state; ephemeral loses anything not committed-and-pushed on teardown — the
operator is never misled that ephemeral work is durable (documented + surfaced at
deploy).

## Clone-on-start

Start-time population of a persistent/ephemeral `/workspace` from a source repo.

| Field | Value |
|-------|-------|
| `repo` | source repo URL (`--repo`); applies to persistent/ephemeral only (bind is already present) |
| credential | **by URL scheme** (operator-confirmed): `git@github.com:…` → injected SSH push key (`core.sshCommand`, 003); `https://github.com/…` → `GH_TOKEN` (always present, 003) |
| fail-fast | an SSH-URL `--repo` with **no** injected push key → the deploy **dies before** starting an empty-workspace agent (FR-014/SC-008) |
| idempotency | skip the clone if `/workspace` already holds a working copy (a persistent recreate never clobbers local state) |

## Deploy-time validation states

| State | Trigger | Behavior |
|-------|---------|----------|
| **bind on remote** | `--workspace bind` on a non-local host | `die` with a clear message before deploy (FR-011/SC-007) |
| **missing clone credential** | `--repo git@…` with no injected push key | `die` before container creation (FR-014/SC-008) |
| **dead-session reattach** | attach when `main` is gone | fresh session OR clear "nothing running" report — never silent (FR-008) |
| **ephemeral durability** | `--workspace ephemeral` | surfaced/documented as non-durable (FR-015) |
