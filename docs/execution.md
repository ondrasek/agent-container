# Execution modes, sessions & workspaces (Feature 004)

`agent-container up`/`redeploy` own **what runs inside the container and how you
interact with it**. Everything here is deploy-time configuration threaded into the
generated compose model and a mode-branched `entrypoint.sh` — no new image, no new
runtime dependency.

## Execution mode — `--mode interactive|headless` (default `interactive`)

| Mode | What runs | `restart:` | Result |
|------|-----------|-----------|--------|
| **interactive** | sshd + tmux `main`; the chosen agent is launched in a dedicated window (optionally seeded with a task); PID 1 stays alive | `unless-stopped` (kept alive / restarted across crashes) | a persistent attachable session |
| **headless** | the agent runs its non-interactive form as PID 1's workload; the container **exits with the agent's exit code** | `on-failure` (a success exits and is **not** resurrected; a failure follows the restart policy) | the container exit code + `logs` |

The two modes and the workspace mode are **independently selectable** — every
combination is permitted (guidance only notes the natural pairings: interactive ↔
persistent, headless ↔ ephemeral).

### Headless: foreground vs detached

Headless is **detached by default** (`up` returns; the container runs and exits;
retrieve the result later with `logs`/`list`). `up --mode headless --foreground`
runs the compose up **attached** with `--abort-on-container-exit --exit-code-from
agent`, so the run streams and **the CLI exit status is the agent container's exit
code** (`--foreground` is headless-only and is refused elsewhere).

> **Sidecar caveat.** With a [sidecar override](./orchestration.md), a
> headless-foreground run's `--abort-on-container-exit` stops *every* service when
> *any* one exits — so a one-shot sidecar that exits first would abort the agent
> and pin the reported code to that forced stop. Keep headless-foreground sidecars
> long-lived.

### Re-`up` of a finished headless run

`up` stays the idempotent no-op only for a **running** deployment. When a headless
deployment has already **exited**, a re-`up` reports the prior exit status/code
(retrievable via `list`/`logs`) rather than silently resurrecting the job — use
`redeploy` (deliberately non-idempotent) to run the task again.

## Agent — `--agent claude|codex|pi` (default `claude`) + `--task`

One primary agent per deployment. `--task <text|@file>` seeds it at launch
(interactive) or is the job to run (headless); it is delivered as an **injected
file** (Feature 003's ephemeral `/run` channel), never on argv or in the
environment, so it has no size cap and does not leak into the process table. You
can still start additional processes by hand inside an interactive session.

## Sessions — detach / reattach / dead-session

The tmux session `main` is decoupled from your SSH connection: detach (or drop the
connection) and it keeps running; reattach from **any** machine lands on the same
session. `attach` now issues an explicit `tmux has-session` probe first, so a
session that has ended is reported clearly — **"nothing running"**, redeploy to
start fresh — instead of dropping you into a silent empty shell. A crash-restart
rebuilds `main` fresh (the prior session is not resumed), consistent with the
ephemeral, commit-and-push discipline.

## Workspace — `--workspace persistent|bind|ephemeral` (default `persistent`)

Selects what is mounted at `/workspace`:

| Mode | `/workspace` is | Durability | Host |
|------|-----------------|------------|------|
| **persistent** | the named `agent-container-<name>-workspace` volume | survives recreation | any |
| **bind** | a local directory (`--workspace-dir`) | edits the operator's own filesystem | **local hosts only** (a remote host refuses it) |
| **ephemeral** | nothing (the container's writable layer) | **gone on teardown** | any |

The workspace named volume exists **only** in persistent mode; the other six
per-container volumes and the name/port identity are unchanged, and pre-004 /
default deployments are persistent — so no existing deployment's identity changes.
`--purge`/`wipe` tolerate the workspace volume's absence.

> **Ephemeral is not durable.** An ephemeral workspace loses anything not
> committed-and-pushed when the container is torn down. `up` prints a NOTE to that
> effect at deploy time. This is by design — it enforces the commit-and-push
> discipline the whole project is built around.

## Clone-on-start — `--repo <url>`

For a persistent/ephemeral workspace, `--repo` populates `/workspace` on first
start (a bind workspace is already present and is never cloned). The credential is
chosen by **URL scheme**, both wired by [Feature 003](./credentials.md):

- `git@github.com:…` / `ssh://…` → the injected **SSH push key** (`--push-key`).
  An SSH URL with **no** injected key **fails fast** — the deploy dies before
  starting an empty-workspace agent.
- `https://github.com/…` → **`GH_TOKEN`** (always present).

Clone-on-start is **idempotent**: it is skipped when `/workspace` already holds a
working copy, so a persistent recreate never clobbers local state.

## Where each setting travels

Non-secret settings (`mode`/`agent`/`repo`/`workspace`) ride as compose
**environment** (`AGENT_CONTAINER_MODE` / `AGENT_CONTAINER_AGENT` /
`AGENT_CONTAINER_CLONE_URL` — the clone URL var is deliberately distinct from
`AGENT_CONTAINER_REPO`, the CLI's host-side build-context override). The task rides
the ephemeral injected-file channel. See
[`specs/004-agent-execution/`](../specs/004-agent-execution/) for the full contract.
