# Host-side orchestration

Thin wrapper around `docker run` / `podman run` that lets the operator run **N parallel devenv containers** on one host without juggling names, ports, or volumes by hand.

The canonical interface is **`bin/devenv`**. Compose and Quadlet are provided as deployment-shape templates, not as separate code paths.

## Two runtimes, one image

| Environment        | Runtime          | Primary path             | Alternative                       |
|--------------------|------------------|--------------------------|-----------------------------------|
| Operator laptop    | Lima + docker-cli| `bin/devenv`             | `orchestration/compose.yaml`      |
| VPS (production)   | Podman           | `bin/devenv`             | `orchestration/devenv.container`  |

`bin/devenv` auto-detects the runtime: it prefers **podman** if both are on PATH (the VPS target), falling back to **docker**. Override with `DEVENV_RUNTIME=docker|podman`.

The image (`localhost/remote-persistent-devenv:latest`) is OCI-portable, so the same build runs under either runtime.

## Quick start

```bash
# Build once.
bin/devenv build

# Start two parallel environments.
bin/devenv up alpha
bin/devenv up bravo

# See what's running.
bin/devenv list

# Attach (ssh + tmux). Optionally select a tmux window in session 'main'.
bin/devenv attach alpha
bin/devenv attach alpha --window edit

# Tail container logs.
bin/devenv logs alpha

# Tear down (all per-container volumes preserved).
bin/devenv down alpha

# Tear down AND delete ALL per-container volumes.
bin/devenv down alpha --purge
```

## Naming convention

| Resource           | Pattern                              | Example                       |
|--------------------|--------------------------------------|-------------------------------|
| Container          | `devenv-<name>`                      | `devenv-alpha`                |
| Workspace volume   | `devenv-<name>-workspace`            | `devenv-alpha-workspace`      |
| Per-container volumes | `devenv-<name>-{workspace,claude,codex,pi,shellenv,tmux}` | `devenv-alpha-tmux` |
| Image              | `localhost/remote-persistent-devenv:latest` | (shared across containers) |
| Quadlet unit       | `devenv-<name>.container`            | `devenv-alpha.container`      |

`<name>` must match `[a-z0-9][a-z0-9_-]*`. Short and ASCII; this is what shows up in `ps`, `journalctl`, and your shell prompt.

## Port allocation

Deterministic and stateless:

```
port = 2200 + (sum-of-ascii-of-name-chars mod 100)
```

So `alpha` always maps to **2218**, `bravo` to **2238**, etc. Window: **2200-2299**.

- **Why deterministic?** Re-running `bin/devenv up alpha` after a restart resolves the same port without consulting state.
- **Collision handling.** Two names that hash to the same offset *within* the 2200-2299 window cannot run simultaneously. `bin/devenv up` will fail at container-create time (the runtime refuses the port bind) with an actionable error. Pick a different `<name>`. Realistically: the operator is running 2-10 containers, not 100, so collisions are rare.
- **Where the resolved port lives.** `${XDG_STATE_HOME:-$HOME/.local/state}/devenv/<name>.port`. NOT in the repo. `bin/devenv attach` reads it to construct the `ssh -p` call.

If you need to override (e.g. you already have something on 2218), edit the state file before `attach`, or set `DEVENV_HOST` / use raw `ssh`. The pinning is a convention, not a contract.

## Volume layout

- **Six named volumes per container**: `devenv-<name>-workspace` (mounted at `/workspace`), plus the agent-login volumes `-claude` / `-codex` / `-pi` (`~/.claude`, `~/.codex`, `~/.pi`), the shell-env volume `-shellenv` (`~/.devenv`), and the tmux-config volume `-tmux` (`~/.config/tmux`).
- The volumes **survive `devenv down`** — only `down --purge` removes them (all six).
- Hard constraint: **the container is ephemeral**. The volume is for **scratch + uncommitted work in flight**, not durable state. Every agent commits and pushes; if you lose the volume, you lose only un-pushed work.

## `.env` file lookup

`bin/devenv up <name>` resolves the credentials file in this order; **first match wins**:

1. `./.env` in the current working directory.
2. `~/.config/devenv/<name>.env` (per-container override).
3. `~/.config/devenv/.env` (shared default).

The chosen path is printed at startup. If none exists, `up` fails fast with all three paths listed.

This composes cleanly with the credential contract: see [`credentials.md`](credentials.md).

## State on the host

| Path                                            | Purpose                              | In repo? |
|-------------------------------------------------|--------------------------------------|----------|
| `${XDG_STATE_HOME:-~/.local/state}/devenv/`     | Port mapping per container.          | No       |
| `~/.config/devenv/`                             | Per-container `.env` files.          | No       |
| `~/.config/containers/systemd/devenv-*.container` | Installed Quadlet units (VPS only). | No       |

No host state lives in the repo. The repo holds **templates and code**; the operator owns the runtime artifacts.

## VPS path: Podman Quadlet

`orchestration/devenv.container` is a **template** with `${NAME}`, `${PORT}`, `${ENV_FILE}` placeholders. To instantiate manually:

```bash
NAME=alpha PORT=2218 ENV_FILE=$HOME/.config/devenv/alpha.env \
  envsubst < orchestration/devenv.container \
  > ~/.config/containers/systemd/devenv-alpha.container

systemctl --user daemon-reload
systemctl --user start devenv-alpha.service
```

Quadlet translates each `.container` file into a `.service` unit at daemon-reload time. `bin/devenv` can be extended later to perform this install step automatically; today it calls `podman run` directly (same end result, simpler control flow).

Logs flow into `journald`:

```bash
journalctl --user -u devenv-alpha.service -f
```

## Local path: Docker Compose

`orchestration/compose.yaml` is parameterized via `DEVENV_NAME` and `DEVENV_PORT`. To use it directly:

```bash
cd orchestration
DEVENV_NAME=alpha DEVENV_PORT=2218 docker compose up -d
DEVENV_NAME=alpha docker compose down
```

The same env vars drive container name, port, and volume name, so two compose invocations with different `DEVENV_NAME` produce two non-colliding stacks.

`bin/devenv` does not use compose — it calls the runtime directly. Compose is offered for operators who prefer that interface.

## Constraints satisfied

- **Ephemeral containers** — only the workspace volume is persistent, and `--purge` removes even that.
- **No VSCode coupling** — no `.devcontainer/`, no editor assumptions. SSH + tmux is the contract.
- **Parallel-safe** — `devenv up alpha` and `devenv up bravo` run side by side with distinct names, ports, and volumes.
- **No baked secrets** — `.env` is read at run time, not at build time.
- **Rootless** — no `sudo` in `bin/devenv`. Podman runs rootless under the operator's user.
