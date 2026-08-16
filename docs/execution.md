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
>
> **The [egress sidecar](./egress.md) is such a service.** An enforced declaration adds
> a second, long-lived container to the project, so the same rule applies to it: if
> the sidecar exits first, the run aborts. That is **fail-closed and correct** — the
> agent shares that container's network namespace, so once it is gone the agent has
> no network at all, let alone a controlled one — but the reported exit code then
> reflects the forced stop rather than the agent's own result. Stated here so it
> reads as a behaviour, not as a mystery.

### Starting under an egress declaration

An enforced declaration changes *when* the agent starts and *where its port lives*,
and both are visible from here:

- the agent waits for the egress sidecar to be **healthy**, not merely started —
  netfilter is installed before either daemon serves, so an agent started in that
  window gets bare connection refusals for destinations it is entitled to reach.
  A headless run therefore begins a second or two after `up`, by design;
- the agent joins the sidecar's network namespace, so it **cannot publish ports**;
  the SSH binding moves to the sidecar. The port *number* is unchanged and `attach`
  is unaffected — see [orchestration](./orchestration.md#who-publishes-the-port).

### Re-`up` of a finished headless run

`up` stays the idempotent no-op only for a **running** deployment. When a headless
deployment has already **exited**, a re-`up` reports the prior exit status/code
(retrievable via `list`/`logs`) rather than silently resurrecting the job — use
`redeploy` (deliberately non-idempotent) to run the task again.

## Agent — `--agent claude|codex|pi|opencode` (default `claude`) + `--task`

One primary agent per deployment. `--task <text|@file>` seeds it at launch
(interactive) or is the job to run (headless); it is delivered as an **injected
file** (Feature 003's ephemeral `/run` channel), so it never rides the host-side
compose model (the CLI's argv/environment) and has no size cap. The entrypoint
reads that file and passes the task to the agent in-container (so it does appear
in the *container's* process table for the agent invocation, e.g. `claude -p
"<task>"`). You can still start additional processes by hand inside an
interactive session.

The supported agents are
<!-- agents:begin -->
`claude` (Claude Code), `codex` (OpenAI Codex), `pi` (pi-coding-agent), and
`opencode`.
<!-- agents:end -->
This is one list: the same four can also *drive* the CLI from outside (Feature
009). A hermetic test parses this block, `AGENTS` in `bin/agent-container`, the
dispatch in `entrypoint.sh`, the `Dockerfile`, and the shell completions, and
fails if any of them disagree.

| Agent | Headless form | Persistent state |
|---|---|---|
| `claude` | `claude -p "<task>"` | `~/.claude` |
| `codex` | `codex exec "<task>"` | `~/.codex` |
| `pi` | `pi -p "<task>"` | `~/.pi` |
| `opencode` | `opencode run "<task>"` | `~/.config/opencode` **and** `~/.local/share/opencode` |

**opencode is the one agent with two volumes.** It follows XDG and splits
configuration (`~/.config/opencode`) from credentials and session history
(`~/.local/share/opencode/auth.json`, `opencode.db`), and both must survive
recreation. Its runtime locks (`~/.local/state/opencode`) and cache are
deliberately *not* persisted — carrying a stale lock across a recreate would be a
self-inflicted failure.

**opencode interactive runs are not task-seeded.** Its TUI positional argument is
a *project path*, not a message (`opencode [project]`), so a `--task` passed
there would be misread as a path. The task is delivered for `--mode headless`; in
an interactive session the entrypoint logs a note and you paste it in.

Selecting an agent that is missing from the running image (an image built before
that agent was added) fails with a message naming `agent-container redeploy
<name>` as the remedy, rather than a bare `command not found`.

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

The workspace named volume exists **only** in persistent mode; the other eight
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

- `git@github.com:…` / `ssh://…` → the container's **own SSH key**
  ([Feature 019](./credentials.md)), found at the conventional identity path with
  nothing wired.
- `https://github.com/…` → **`GH_TOKEN`** (always present).

Clone-on-start is **idempotent**: it is skipped when `/workspace` already holds a
working copy, so a persistent recreate never clobbers local state.

### An SSH clone-on-start is TWO-PHASE

The key cannot exist before the container does, so a **first** boot with an SSH
`--repo` cannot clone: the forge has never seen the key. Feature 019 makes that
case explicit rather than fatal.

Phase 1 — the container **starts**, generates its key, does **not** clone, and
says so, printing the key and the exact next command. The invocation exits **3**,
*pending registration*.

Phase 2 — register the key, then `redeploy`. The clone runs.

```sh
agent-container up two-phase --repo git@github.com:you/test.git   # exits 3
agent-container ssh-key show two-phase                            # register this
agent-container redeploy two-phase                                # now it clones
```

> **Do not tear the environment down to retry.** `down --purge` destroys the key
> you were about to register, and the replacement is a *different* key — so a
> caller that reads only the exit status loops forever, invalidating each
> registration it just made. The recovery is **register, then `redeploy`**. The
> tool says this in the output for exactly that reason: the exit code is what
> *causes* the wrong reaction, so it cannot also be what prevents it.

This is the one case where the empty-workspace refusal is relaxed. Every other
one stands, and a test pins that: the container here is *pending and says so*,
not silently useless.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | failure |
| `2` | refused — a usage error, **or** a destructive action declined without `-y` on a non-TTY |
| `3` | pending registration: the environment exists but an SSH clone-on-start is waiting for the agent's key to be registered |

Two caveats, stated rather than left to be discovered:

- **`2` is shared** with the CLI framework's own usage-error code, so it does not
  *uniquely* identify a refusal.
- A headless `--foreground` run **propagates the agent's** exit code, so in that
  mode the status is not the tool's at all.

The same table is in `agent-container --help`, built from the same constants — a
number in prose drifting from the number in code is how an automated caller
branching on a stale value fails silently.

## Where each setting travels

Non-secret settings (`mode`/`agent`/`repo`/`workspace`) ride as compose
**environment** (`AGENT_CONTAINER_MODE` / `AGENT_CONTAINER_AGENT` /
`AGENT_CONTAINER_CLONE_URL` — the clone URL var is deliberately distinct from
`AGENT_CONTAINER_REPO`, the CLI's host-side build-context override). The task rides
the ephemeral injected-file channel. See
[`specs/004-agent-execution/`](../specs/004-agent-execution/) for the full contract.
