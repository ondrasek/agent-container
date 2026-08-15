# Host-side orchestration

Thin wrapper around `docker run` / `podman run` that lets the operator run **N parallel agent-container containers** on one host without juggling names, ports, or volumes by hand.

The canonical interface is **`agent-container`**. Compose and Quadlet are provided as deployment-shape templates, not as separate code paths.

## Two runtimes, one image

| Environment        | Runtime          | Primary path             | Alternative                       |
|--------------------|------------------|--------------------------|-----------------------------------|
| Operator laptop    | Lima + docker-cli| `agent-container`             | `orchestration/compose.yaml`      |
| VPS (production)   | Podman           | `agent-container`             | `orchestration/agent-container.container`  |

`agent-container` auto-detects the runtime with a platform-aware default: on **macOS** (Lima + docker-cli) it prefers **docker** then podman; on **Linux** (the VPS) it prefers **podman** then docker. Override with `AGENT_CONTAINER_RUNTIME=docker|podman`.

The image (`localhost/agent-container:latest`) is OCI-portable, so the same build runs under either runtime.

## Quick start

```bash
# Build once.
agent-container build

# Start two parallel environments.
agent-container up alpha
agent-container up bravo

# See what's running.
agent-container list

# Attach (ssh + tmux). Optionally select a tmux window in session 'main'.
agent-container attach alpha
agent-container attach alpha --window edit

# Tail container logs.
agent-container logs alpha

# Tear down (all per-container volumes preserved).
agent-container down alpha

# Tear down AND delete ALL per-container volumes.
agent-container down alpha --purge
```

## Naming convention

| Resource           | Pattern                              | Example                       |
|--------------------|--------------------------------------|-------------------------------|
| Container          | `agent-container-<name>`                      | `agent-container-alpha`                |
| Egress sidecar     | `agent-egress-<name>`                | `agent-egress-alpha`          |
| Workspace volume   | `agent-container-<name>-workspace`            | `agent-container-alpha-workspace`      |
| Per-container volumes | `agent-container-<name>-{workspace,claude,codex,pi,shellenv,tmux,ssh}` | `agent-container-alpha-ssh` |
| Image              | `localhost/agent-container:latest` | (shared across containers) |
| Quadlet unit       | `agent-container-<name>.container`            | `agent-container-alpha.container`      |

`<name>` must match `[a-z0-9][a-z0-9_-]*`. Short and ASCII; this is what shows up in `ps`, `journalctl`, and your shell prompt.

The egress sidecar (present only under an enforced [egress declaration](egress.md)) is deliberately
**outside** the `agent-container-*` namespace: six separate sites treat any `agent-container-*`
container as an environment to list, pick or tear down, and a sidecar named into that space would be
offered as one.

## Port allocation

Deterministic and stateless:

```
port = 2200 + (sum-of-ascii-of-name-chars mod 100)
```

So `alpha` always maps to **2218**, `bravo` to **2238**, etc. Window: **2200-2299**.

- **Why deterministic?** Re-running `agent-container up alpha` after a restart resolves the same port without consulting state.
- **Collision handling.** Two names that hash to the same offset *within* the 2200-2299 window cannot run simultaneously. `agent-container up` will fail at container-create time (the runtime refuses the port bind) with an actionable error. Pick a different `<name>`. Realistically: the operator is running 2-10 containers, not 100, so collisions are rare.
- **Where the resolved port lives.** `${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/<name>.port`. NOT in the repo. `agent-container attach` reads it to construct the `ssh -p` call.

If you need to override (e.g. you already have something on 2218), edit the state file before `attach`, or set `AGENT_CONTAINER_HOST` / use raw `ssh`. The pinning is a convention, not a contract.

### Who publishes the port

Normally the agent service does. Under an enforced [egress declaration](egress.md) it **cannot**:
the agent joins the egress sidecar's network namespace, a shared namespace has exactly one port
owner, and that is the container owning the namespace. So the `2200 + hash` binding is published by
the **egress** service, and the agent service declares no `ports:` at all.

The port **number** is unchanged, so `port_for_name`, the state file and `attach` all still agree —
nothing about connecting to the container changes. What changes is which service holds the binding,
and that is part of the deployed shape rather than a detail:

- **adding** a declaration to a running environment moves the binding from `agent` to `egress`;
- **removing** one moves it back.

Either way compose cannot hand a published port to a different service while the current owner still
holds it, so the tool detects the stale owner — **in both directions** — and recreates the
deployment rather than failing with `port is already allocated`. It says so when it does; a
recreation an operator did not ask for reads as a bug unless it is announced. Volumes are preserved.

## Volume layout

- **Nine named volumes per container**: `agent-container-<name>-workspace` (mounted at `/workspace`), plus the agent-login volumes `-claude` / `-codex` / `-pi` (`~/.claude`, `~/.codex`, `~/.pi`) and opencode's **two**, `-opencode` (`~/.config/opencode`) and `-opencode-data` (`~/.local/share/opencode`) — it is the one agent that splits configuration from credentials — the shell-env volume `-shellenv` (`~/.agent-env`), the tmux-config volume `-tmux` (`~/.config/tmux`), and the SSH volume `-ssh` (`~/.ssh` — `authorized_keys` and the host key under `hostkeys/`, so SSH identity is stable across recreation).
- The volumes **survive `agent-container down`** — only `down --purge` removes them (all nine).
- Hard constraint: **the container is ephemeral**. The volume is for **scratch + uncommitted work in flight**, not durable state. Every agent commits and pushes; if you lose the volume, you lose only un-pushed work.

## `.env` file lookup

`agent-container up <name>` resolves the credentials file in this order; **first match wins**:

1. `./.env` in the current working directory.
2. `~/.config/agent-container/<name>.env` (per-container override).
3. `~/.config/agent-container/.env` (shared default).

The chosen path is printed at startup. If none exists, `up` fails fast with all three paths listed.

This composes cleanly with the credential contract: see [`credentials.md`](credentials.md).

## Concurrency: one advisory lock per (host, container)

Every **mutating** verb (`up`, `down`, `stop`, `start`, `redeploy`, `wipe`, `purge`, `keys`) takes
an **fcntl advisory lock** on `<state>/<host>/<name>.lock` before touching anything. It is
**non-blocking**: a second invocation against the same container on the same host **fails fast**
rather than queueing, so two concurrent `up`s can never interleave a compose write.

Read-only verbs (`list`, `logs`, `plan`, `status`) **never** lock — they must stay usable while a
deploy is in flight.

If you add a mutating verb, take the lock. This is the invariant that keeps parallel containers
(hard constraint 3) from corrupting each other's generated compose file and port state.

## Sidecar services

An operator override file — `.agent-container/<name>.services.yaml`, falling back to
`~/.config/agent-container/<name>.services.yaml` — is merged as a **second `-f`** on every compose
call, so the agent container and its helpers share one project and one lifecycle (`down` tears
both down).

It is validated: **`services:` only**, and it **must not redefine the `agent` service**. On the
create path an invalid override is fatal; on teardown it is resolved leniently and ignored with a
warning, because a broken override must never block a teardown.

Under an enforced [egress declaration](egress.md) these services are **inside the enforcement
boundary by default** — a third `-f` places each one in the egress sidecar's network namespace, and
they wait for it to be healthy exactly as the agent does. A sidecar with free egress that the agent
can reach *is* a bypass, so being inside is the default and `egress.sidecars_outside` is the
explicit, named exception. The override is checked for **egress posture** as well as shape once a
declaration exists: a service inside the boundary may not hold `privileged`, `NET_ADMIN`/`NET_RAW`/
`SYS_ADMIN`/`ALL`, or `network_mode: host`.

## State on the host

| Path                                            | Purpose                              | In repo? |
|-------------------------------------------------|--------------------------------------|----------|
| `${XDG_STATE_HOME:-~/.local/state}/agent-container/`     | Port mapping per container.          | No       |
| `~/.config/agent-container/`                             | Per-container `.env` files.          | No       |
| `~/.config/containers/systemd/agent-container-*.container` | Installed Quadlet units (VPS only). | No       |

No host state lives in the repo. The repo holds **templates and code**; the operator owns the runtime artifacts.

## VPS path: Podman Quadlet

`orchestration/agent-container.container` is a **template** with `${NAME}`, `${PORT}`, `${ENV_FILE}` placeholders. To instantiate manually:

```bash
NAME=alpha PORT=2218 ENV_FILE=$HOME/.config/agent-container/alpha.env \
  envsubst < orchestration/agent-container.container \
  > ~/.config/containers/systemd/agent-container-alpha.container

systemctl --user daemon-reload
systemctl --user start agent-container-alpha.service
```

Quadlet translates each `.container` file into a `.service` unit at daemon-reload time. `agent-container` can be extended later to perform this install step automatically; today it calls `podman run` directly (same end result, simpler control flow).

Logs flow into `journald`:

```bash
journalctl --user -u agent-container-alpha.service -f
```

## Local path: Docker Compose

`orchestration/compose.yaml` is parameterized via `AGENT_CONTAINER_NAME` and `AGENT_CONTAINER_PORT`. To use it directly:

```bash
cd orchestration
AGENT_CONTAINER_NAME=alpha AGENT_CONTAINER_PORT=2218 docker compose up -d
AGENT_CONTAINER_NAME=alpha docker compose down
```

The same env vars drive container name, port, and volume names, so two compose invocations with different `AGENT_CONTAINER_NAME` produce two non-colliding stacks — each with the full set of nine per-container volumes (matching the CLI). Point `AGENT_CONTAINER_ENV_FILE` at a distinct `.env` (default `../.env`) to give parallel stacks different `GH_TOKEN` / git identities.

`orchestration/compose.yaml` is a **hand-editable template**, separate from the compose model
`agent-container` generates per deployment (which is where the egress service, the shared network
namespace and the port owner above are decided). Use it if you want to drive compose yourself.

## SSH identity is persisted per container

SSH **host key** and the operator's **`~/.ssh/authorized_keys`** live on the `-ssh` named volume (mounted at `~/.ssh`), so they **survive recreation** (`down`/`up`, Quadlet/compose recreate). A container keeps a **stable SSH identity** across its own recreations (no `known_hosts` churn), while different containers get distinct keys. Because the container is rootless, the host key is dev-owned under `~/.ssh/hostkeys/` rather than root-owned `/etc/ssh`. The host key is **generated in the container and never leaves** (Feature 018); the tool captures its PUBLIC half at every deploy and pins it, and `attach` verifies against that. See the credentials guide for the `authorized_keys` injection paths (`.env` vars, `up --authorized-key`, the `keys` subcommand) — all public material. Only `down --purge` drops the identity along with the other volumes.

## Constraints satisfied

- **Ephemeral containers** — all nine per-container volumes persist across `down`/`up`; `--purge` removes them. The container itself is disposable — durable state lives in git (commit + push), not the volumes.
- **No VSCode coupling** — no `.devcontainer/`, no editor assumptions. SSH + tmux is the contract.
- **Parallel-safe** — `agent-container up alpha` and `agent-container up bravo` run side by side with distinct names, ports, and volumes.
- **No baked secrets** — `.env` is read at run time, not at build time.
- **Rootless** — no `sudo` or root inside the container; sshd runs as the `dev` user on port 2222. Podman also runs rootless under the operator's user on the host. The one capability any deployment holds — `NET_ADMIN`, for programming the [egress boundary](egress.md) — sits on the sidecar, which runs no untrusted code; the agent container's capability set is empty with a declaration and without one alike.

## Three memories, three purposes, no overlap

The tool now keeps three separate answers, and confusing them is how both possible mistakes get made:

| Memory | Answers | Lives | Dies |
|---|---|---|---|
| the **live daemon** | *what is running right now* | on the host | with the container |
| **local port state** `<state>/<host>/*.port` | the **port number**, and per-host enumeration | derived host state | with its host |
| the **inventory** (Feature 014) | *what did we ever create* | durable data | never (count-capped only) |

**Port state is never consulted about history, and the inventory never about the present.** So a
disagreement between them is **information, not a conflict**: it means a host's state directory was
cleared while the record kept its entries — which is FR-003 working exactly as intended, not a bug to
reconcile away.

The live daemon is authoritative for *now* and nothing else. `inventory reconcile` is the only place
the three are compared, and it is deliberately **fail-closed**: a host that cannot be reached yields
`unknown`, never `missing`, because invisible is indistinguishable from gone.
