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
| Workspace volume   | `agent-container-<name>-workspace`            | `agent-container-alpha-workspace`      |
| Per-container volumes | `agent-container-<name>-{workspace,claude,codex,pi,shellenv,tmux}` | `agent-container-alpha-tmux` |
| Image              | `localhost/agent-container:latest` | (shared across containers) |
| Quadlet unit       | `agent-container-<name>.container`            | `agent-container-alpha.container`      |

`<name>` must match `[a-z0-9][a-z0-9_-]*`. Short and ASCII; this is what shows up in `ps`, `journalctl`, and your shell prompt.

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

## Volume layout

- **Six named volumes per container**: `agent-container-<name>-workspace` (mounted at `/workspace`), plus the agent-login volumes `-claude` / `-codex` / `-pi` (`~/.claude`, `~/.codex`, `~/.pi`), the shell-env volume `-shellenv` (`~/.agent-container`), and the tmux-config volume `-tmux` (`~/.config/tmux`).
- The volumes **survive `agent-container down`** — only `down --purge` removes them (all six).
- Hard constraint: **the container is ephemeral**. The volume is for **scratch + uncommitted work in flight**, not durable state. Every agent commits and pushes; if you lose the volume, you lose only un-pushed work.

## `.env` file lookup

`agent-container up <name>` resolves the credentials file in this order; **first match wins**:

1. `./.env` in the current working directory.
2. `~/.config/agent-container/<name>.env` (per-container override).
3. `~/.config/agent-container/.env` (shared default).

The chosen path is printed at startup. If none exists, `up` fails fast with all three paths listed.

This composes cleanly with the credential contract: see [`credentials.md`](credentials.md).

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

The same env vars drive container name, port, and volume name, so two compose invocations with different `AGENT_CONTAINER_NAME` produce two non-colliding stacks.

`agent-container` does not use compose — it calls the runtime directly. Compose is offered for operators who prefer that interface.

## Constraints satisfied

- **Ephemeral containers** — only the workspace volume is persistent, and `--purge` removes even that.
- **No VSCode coupling** — no `.devcontainer/`, no editor assumptions. SSH + tmux is the contract.
- **Parallel-safe** — `agent-container up alpha` and `agent-container up bravo` run side by side with distinct names, ports, and volumes.
- **No baked secrets** — `.env` is read at run time, not at build time.
- **Rootless** — no `sudo` in `agent-container`. Podman runs rootless under the operator's user.
