# Execution modes, sessions & workspaces (Feature 004)

`agent-container up`/`redeploy` own **what runs inside the container and how you
interact with it**. Everything here is deploy-time configuration threaded into the
generated compose model and a mode-branched `entrypoint.sh` — no new image, no new
runtime dependency.

## Execution mode — `--mode interactive|headless` (default `interactive`)

| Mode | What runs | `restart:` | Result |
|------|-----------|-----------|--------|
| **interactive** | sshd + tmux `main`; the chosen agent is launched in a dedicated window (optionally seeded with a task); PID 1 stays alive | `unless-stopped` (kept alive / restarted across crashes) | a persistent attachable session |
| **headless** | the agent runs its non-interactive form as PID 1's workload; the container **exits with the agent's exit code** | **`no`** by default — a one-shot job, so a failure stays failed (`headless_restart:` to change it) | the container exit code + `logs` |

The two modes and the workspace mode are **independently selectable** — every
combination is permitted (guidance only notes the natural pairings: interactive ↔
persistent, headless ↔ ephemeral).

### A failed headless run does NOT retry by default

```yaml
# ~/.config/agent-container/settings.yaml
headless_restart: on-failure:3      # default: no
```

The default is **`no`**, and the reason is worth stating: retrying an agent is not
*resuming* work, it is **starting over**. Nothing about an agent run is
idempotent — a task that commits and pushes pushes again on every attempt, which
is repetition rather than resilience. And every attempt is a fresh model call.

This used to be unbounded `on-failure`. The loop it created was already known and
measured here — run-record retention buckets by UTC day to survive it, and the
record-clearing argv budget is sized for it, both citing *"~9 records in ~40s"*.
Those absorb **record volume**. What was never costed is **money**: one transient
API error was measured turning into **13 billable model calls in 4 minutes**.

Accepted values are `no` and `on-failure[:N]`. **`always` and `unless-stopped`
are refused**, because both resurrect a container that exited 0 and FR-005
requires a headless *success* to terminate and stay terminated — a settings file
should be corrected by the execution model, not quietly contradict it.

`on-failure:N` is honoured by **both** runtimes (measured: `RestartCount` stops at
exactly N on docker and podman). Interactive sessions are unaffected — they stay
`unless-stopped`, because a session is a place you attach to.

Read the resolved policy without opening the generated compose file:

```bash
agent-container context
# runtime: docker (detected)
# headless restart: no (default)
```

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
| `claude` | `claude --permission-mode bypassPermissions -p "<task>"` | `~/.claude` |
| `codex` | `codex exec "<task>"` | `~/.codex` |
| `pi` | `pi -p "<task>"` | `~/.pi` |
| `opencode` | `opencode run "<task>"` | `~/.config/opencode` **and** `~/.local/share/opencode` |

**Claude Code runs headless with `--permission-mode bypassPermissions`, and that
is required rather than convenient.** Headless has no tty and nobody to approve
anything, so Claude's default asks for a permission it can never receive: it
answers *"the write needs your approval"*, does nothing, **and exits 0**. The run
record then reports success for an agent that performed no work — the worst
available outcome, because it is indistinguishable from a task that genuinely had
nothing to do. Measured with a real key; since `claude` is also the *default*
agent, headless mode was broken in its default configuration.

**What this does and does not widen.** It removes an in-container prompt, not a
boundary. The container **is** the boundary — rootless, egress limited to what was
declared (Feature 012), workspace on its own volume, home disposable. An agent
that can already open a shell gains nothing from being asked to confirm a file
write; the prompt has no audience. What it does mean is plain: **a headless task
runs with the agent's tools unrestricted inside that container**, so the boundary
doing the work is the container and the egress declaration, never the agent's own
consent dialog. Scope a task accordingly, and declare egress if the container
should not reach the whole internet.

**An injected agent must not open on a wizard**, and the gate differs per agent —
so this was settled by inspecting each one rather than seeding them all alike:

| Agent | First-run gate | What the entrypoint does |
|---|---|---|
| `claude` | `hasCompletedOnboarding`, `hasTrustDialogAccepted`, and approval of the injected key in `~/.claude.json` | pre-answers all three, **merged** into the operator's file |
| `codex` | workspace **trust** — `trust_level` under `[projects."<path>"]` in `~/.codex/config.toml` | appends the table for `/workspace` if, and only if, no answer is already there |
| `opencode` | **none** | nothing — verified by running it headless from a completely clean state with only an env credential |
| `pi` | **none observed** | nothing beyond seeding its config from `~/.pi/agent` |

The codex file is the operator's, and canonical config they may deliver, so it is
**parsed** with `tomllib` to decide and only **appended** to — never rewritten. A
declared `trust_level` is left alone in either direction: promoting a directory
the operator deliberately marked `untrusted` is the opposite of what the setting
is for. A `config.toml` that does not parse is left completely alone, because
codex reports that error better than this can.

**opencode was checked, not assumed.** Its binary contains ~3800 occurrences of
"onboarding" — all of them `wsl.onboarding.*`, bundled editor/WSL strings with no
bearing on the CLI. Seeding on that evidence would have been inventing a fix for
a problem it does not have.

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
| **bind** | a local directory (`--workspace-dir`), mounted **read-only** | an INPUT — the container cannot write it | **local hosts only** (a remote host refuses it) |
| **ephemeral** | nothing (the container's writable layer) | **gone on teardown** | any |

The workspace named volume exists **only** in persistent mode; the other eight
per-container volumes and the name/port identity are unchanged, and pre-004 /
default deployments are persistent — so no existing deployment's identity changes.
`--purge`/`wipe` tolerate the workspace volume's absence.

> **A host bind is read-only, and that is the design rather than a limitation.**
> Everything the container writes goes to a **volume** — the workspace volume, the
> agent-login volumes, the credential volumes — which is what makes those writes
> survive a recreate and be revocable by name. A host directory is an input.
>
> This used to request read-write, and the request could not be honoured on the
> common macOS + Lima setup where `~` is exposed read-only. The two runtimes
> disagreed only about *when* they said so: docker mounted it and failed at the
> first write (`Read-only file system`), podman refused at container create. Both
> measured. So `rw` never bought a capability here — it bought a deferred error
> under one runtime and a dead deploy under the other.

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

The bare `redeploy` is enough because **it inherits the clone URL** from the running
container, and says so. It did not always: an empty spec silently unset the URL, so
this exact instruction did nothing and left an empty workspace with no explanation.

> **Do not tear the environment down to retry.** `down --purge` destroys the key
> you were about to register, and the replacement is a *different* key — so a
> caller that reads only the exit status loops forever, invalidating each
> registration it just made. The recovery is **register, then `redeploy`**. The
> tool says this in the output for exactly that reason: the exit code is what
> *causes* the wrong reaction, so it cannot also be what prevents it.

This is the one case where the empty-workspace refusal is relaxed. Every other
one stands, and a test pins that: the container here is *pending and says so*,
not silently useless.

### `redeploy` keeps the deployment's settings

`redeploy` reads the execution spec off the running container before recreating it, so
the invocation that looks like "same thing, rebuilt" is exactly that:

```sh
agent-container redeploy acme                  # keeps mode, agent, workspace, repo
agent-container redeploy acme --agent codex    # changes one; the rest still carry over
agent-container redeploy acme --mode interactive   # explicit flag = reset that field
agent-container redeploy acme --no-repo        # drops the clone URL
```

**Any field you pass wins**; the rest are inherited. Since `--mode`, `--agent` and
`--workspace` all have defaults, passing the flag explicitly is how you reset one —
only the clone URL needs `--no-repo`, because "no repo" is not a value you can type.
The tool logs what it kept, listing only fields that differ from the defaults.

Where each value comes from: `mode` and `agent` from the container's environment;
`workspace` (and a bind's directory) from its **mounts**, because the mounts *are* the
workspace mode and every container that already exists predates any marker we could
have started writing. Nothing readable means the field falls back to its default,
which is the pre-inheritance behaviour rather than a wrong claim.

**Two fields are never inherited.** `--task` is a one-shot instruction, not deployment
state: re-executing a headless job on every rebuild rewrites files and opens pull
requests nobody asked for, and unlike a wrong setting, repeating it has *effects*.
`--foreground` describes the terminal you are typing into, not the environment.

`--repo` and `--no-repo` together are refused rather than resolved by precedence:
guessing gets it wrong half the time, and on the half where the operator wanted the
repo gone, keeping it re-clones into a workspace they were clearing.

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
