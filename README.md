# remote-persistent-devenv

Always-on, containerized development environment for a single operator. Hosts AI coding agents (Claude Code, Codex, pi-coding-agent), `nvim`, `tmux`, and `git` behind OpenSSH. Designed to run on a personal Linux VPS and be attached to over `ssh`.

Design contract: [`CLAUDE.md`](CLAUDE.md).
Runtime + base-image decision: [`docs/decisions/0001-runtime-and-base-image.md`](docs/decisions/0001-runtime-and-base-image.md).
Credential contract: [`docs/credentials.md`](docs/credentials.md).

## How it fits together

```
laptop                                        VPS (Hetzner / Debian 12)
------                                        ------------------------
~/.config/devenv/hosts.conf                   user systemd (linger enabled)
  ACME_HOST=vps1.example                        |
  ACME_PORT=2218                                +-- Quadlet: devenv-acme.container
                                                    |
$ devenv-attach acme                                +-- container: devenv-acme
   |                                                       +-- sshd  (port 22 -> host 2218)
   |  ssh -p 2218 dev@vps1.example -t tmux              +-- tmux session "main"
   |     attach -t main                                       +-- nvim
   v                                                          +-- claude
[ you are now inside tmux on the VPS ]                        +-- codex
                                                              +-- /workspace (named volume)
detach (Ctrl-B d)
  -> back on laptop; agents keep running on the VPS
```

Key property: **detach is non-destructive at every layer.** Closing the SSH connection leaves tmux running. tmux retains every pane's state. The container stays up because it was launched detached and is either supervised by user systemd (Quadlet) or kept alive by Docker's restart policy. Lingering keeps your user-level systemd alive across SSH logouts. The only way work is lost is if you (or an agent) fail to `git push` — which is why the design contract forbids that.

## Deploy to a Hetzner VPS

This section walks through standing up a fresh always-on environment on a Hetzner Cloud server. Any Debian 12 / Ubuntu 24.04 host works the same way; nothing here is Hetzner-specific beyond Step 1.

### Step 1 — provision the VPS

Hetzner Cloud Console → **Create Server**. The smallest shared-CPU instance is more than enough (the image is ~1.8 GB on disk; idle dev containers cost ~50 MB RAM each). Use **Debian 12** or **Ubuntu 24.04**. Add your laptop's SSH public key during provisioning. You should now be able to `ssh root@<vps-ip>`.

### Step 2 — create an operator user

Don't run dev environments as root. From `root@vps`:

```bash
adduser --gecos "" --disabled-password ondra        # use your own username
usermod -aG sudo ondra
install -d -m 0700 -o ondra -g ondra /home/ondra/.ssh
cp /root/.ssh/authorized_keys /home/ondra/.ssh/
chown ondra:ondra /home/ondra/.ssh/authorized_keys
chmod 0600 /home/ondra/.ssh/authorized_keys
```

From now on you `ssh ondra@<vps-ip>`. (Disabling root SSH login by editing `/etc/ssh/sshd_config` is a worthwhile next step; out of scope here.)

### Step 3 — install Podman and enable lingering

```bash
sudo apt-get update
sudo apt-get install -y podman git netcat-openbsd
loginctl enable-linger "$USER"
```

`enable-linger` is **load-bearing** for the always-on model: it keeps your user-level systemd alive even after you SSH out. Without it, any container managed under user systemd (via Quadlet) gets killed when your SSH session ends. Run it once per user, ever.

### Step 4 — clone, configure, build

```bash
git clone https://github.com/ondrasek/remote-persistent-devenv.git
cd remote-persistent-devenv
cp .env.example .env
chmod 0600 .env
$EDITOR .env       # fill in GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL, agent API keys
./bin/devenv build
```

First build takes ~5-10 minutes (NodeSource, npm globals, neovim tarball). Subsequent builds reuse cached layers.

### Step 5 — start your first container

Two paths. Pick one per container.

**Quick path** — `bin/devenv up`. Runs `podman run -d`. Survives SSH disconnects (because of `enable-linger`) but **not** a VPS reboot. Fine for experimentation and for environments you intentionally want to recreate often:

```bash
./bin/devenv up acme
# prints something like:
# [devenv] name=acme port=2218 env-file=/home/ondra/remote-persistent-devenv/.env
```

Note the port. You'll need it on the laptop side.

**Quadlet path** — recommended for "always-on" production use. systemd supervises the container, restarts it on failure, brings it back on reboot, captures its logs in `journald`:

```bash
mkdir -p ~/.config/containers/systemd ~/.config/devenv
cp .env ~/.config/devenv/devenv-acme.env
chmod 0600 ~/.config/devenv/devenv-acme.env

sed -e 's/${NAME}/acme/g' \
    -e "s|\${ENV_FILE}|$HOME/.config/devenv/devenv-acme.env|g" \
    -e 's/${PORT}/2218/g' \
    orchestration/devenv.container \
    > ~/.config/containers/systemd/devenv-acme.container

systemctl --user daemon-reload
systemctl --user start devenv-acme.service        # Quadlet generates the .service from .container
systemctl --user status devenv-acme.service
```

To stop / restart / log:

```bash
systemctl --user stop    devenv-acme.service
systemctl --user restart devenv-acme.service
journalctl --user -u devenv-acme.service -f
```

### Step 6 — grant SSH access from your laptop

The container starts with **no** keys in `dev`'s `authorized_keys` (per the hard constraint that nothing operator-specific lives in the image). One-time setup, on the VPS, after first launch:

```bash
# inside the container, set up .ssh
podman exec -u dev devenv-acme install -d -m 0700 /home/dev/.ssh

# copy your laptop's pubkey into the container
podman exec -u dev -i devenv-acme \
    tee -a /home/dev/.ssh/authorized_keys < ~/.ssh/authorized_keys >/dev/null

# tighten perms
podman exec -u dev devenv-acme chmod 0600 /home/dev/.ssh/authorized_keys
```

(This step is a known wart of the MVP — a future iteration will accept an `AUTHORIZED_KEYS` env var or a mounted file so it happens automatically at container start. Tracked separately.)

### Step 7 — set up `devenv-attach` on the laptop

On your **laptop**, not the VPS:

```bash
git clone https://github.com/ondrasek/remote-persistent-devenv.git
sudo ln -s "$PWD/remote-persistent-devenv/bin/devenv-attach" /usr/local/bin/devenv-attach

mkdir -p ~/.config/devenv
chmod 0700 ~/.config/devenv
cat >> ~/.config/devenv/hosts.conf <<EOF
ACME_HOST=<vps-ip-or-dns>
ACME_PORT=2218
EOF
chmod 0600 ~/.config/devenv/hosts.conf
```

### Step 8 — verify

```bash
devenv-attach acme
```

You should land inside a tmux session named `main`, prompt is `dev@<container-id>:/workspace$`. `tmux ls` shows one session. Detach with `Ctrl-B d`. Re-attach to confirm everything's still there.

## Daily use

### Attach to a container

```bash
devenv-attach acme            # remote, by name from hosts.conf
devenv-attach -l acme         # local (Lima on macOS); reads port from local state file
```

Behind the scenes: `ssh dev@<host> -p <port> -t tmux attach -t main`. The `-t` allocates a TTY (required for tmux); `tmux attach -t main` joins the existing session rather than creating a new one (which would mask bugs).

### Interactive wizard (devenv-wiz)

`bin/devenv-wiz` is a Python sibling of `bin/devenv` + `devenv-attach` that shares all their on-disk state (container names, port hash, `<name>.port` state files, env-file resolution, `hosts.conf`). It needs nothing but [uv](https://docs.astral.sh/uv/) installed — it is a PEP 723 single-file script.

```bash
bin/devenv-wiz                # interactive menu: build, start, attach, logs, stop, purge
bin/devenv-wiz up acme        # every wizard action has a scriptable CLI twin
bin/devenv-wiz list --json    # machine-readable state (merges runtime ps + state files)
bin/devenv-wiz attach acme    # hosts.conf -> remote, else local state file; execs ssh
bin/devenv-wiz --self-test    # doctests + interop corpus (port hash, key derivation)
```

The two toolchains are interchangeable mid-flight: `bin/devenv up acme` then `bin/devenv-wiz attach acme --local` works, and vice versa. Remote (hosts.conf) targets are attach-only; lifecycle commands act on the local runtime exclusively.

Two deliberate differences from the bash tools: when a name has *both* a hosts.conf entry and a local state file, `devenv-wiz attach` prefers the remote — pass `--local` to get `bin/devenv attach` semantics. And `devenv-wiz down`/`purge` confirm before destroying anything, so scripts must pass `-y`/`--yes` (`bin/devenv down` never prompts).

The wizard has a pytest suite in `bin/tests/` that pins its interop contract with the bash tools (port hash, naming, env-file resolution, hosts.conf parsing, generated `run`/`ssh` argv). It needs no container runtime or ssh — only uv:

```bash
uv run --no-project --with pytest \
       --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' \
       pytest bin/tests
```

The `--with` pins mirror the script's PEP 723 inline metadata — keep them in sync when bumping dependencies in `bin/devenv-wiz` (and in `pyproject.toml`). `--no-project` keeps the run hermetic: the root `pyproject.toml` otherwise puts `uv run` in project mode and would sync a `.venv/` at the repo root.

### Install as a uv tool

`devenv-wiz` can be installed onto your `PATH` as a uv-managed tool. The install **must be editable** — `devenv-wiz` reads sibling repo files (the `Dockerfile` for `build`'s context, `completions/` for `completions`), so a non-editable install (which copies the module into the venv) breaks those:

```bash
uv tool install --editable /path/to/remote-persistent-devenv
#   installs ~/.local/bin/devenv-wiz; `git pull` keeps it current (editable)
uv tool upgrade devenv-wiz     # after dependency bumps
uv tool uninstall devenv-wiz
```

This only installs the Python wizard; `bin/devenv` (bash) is not a Python package — symlink it separately (via the oh-my-zsh plugin, or the `~/.local/bin` symlink shown under [Shell completions](#shell-completions)). If the repo's `bin/` is also on `PATH` (e.g. via the oh-my-zsh plugin), both `~/.local/bin/devenv-wiz` and `bin/devenv-wiz` resolve to the same editable code — harmless. The `uv run --script bin/devenv-wiz` path and the oh-my-zsh plugin are unaffected by installing the tool.

### Shell completions

Both CLIs ship bash and zsh completions under [`completions/`](completions/):
subcommands, per-subcommand flags (including the repeatable `--mount`), and
**container-name completion** for `up` / `down` / `attach` / `logs` / `purge`.
Names are gathered directly in the shell from your state files
(`$XDG_STATE_HOME/devenv/*.port`) and `hosts.conf` — no `docker`, `podman`, or
`uv` is spawned on Tab, so completion stays instant and works offline.

Completion triggers on the command **name**, so put the tools on your `PATH`
(this also lets the `build` / `completions` subcommands find the repo):

```bash
# add the repo's bin/ to PATH (in ~/.bashrc or ~/.zshrc)
export PATH="$HOME/remote-persistent-devenv/bin:$PATH"
```

**bash** — source the scripts (works with or without the `bash-completion`
package):

```bash
# ~/.bashrc
source "$HOME/remote-persistent-devenv/completions/devenv.bash"
source "$HOME/remote-persistent-devenv/completions/devenv-wiz.bash"
# or generate them: devenv completions bash > ~/.local/share/bash-completion/completions/devenv
```

**zsh** — drop the scripts onto `$fpath` as `_devenv` / `_devenv-wiz`, then
`compinit`:

```zsh
mkdir -p ~/.zfunc
devenv     completions zsh > ~/.zfunc/_devenv
devenv-wiz completions zsh > ~/.zfunc/_devenv-wiz
# ~/.zshrc, before compinit:
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

**oh-my-zsh** — a plugin under [`completions/oh-my-zsh/devenv/`](completions/oh-my-zsh/devenv/)
bundles PATH wiring, both CLIs' completions, and aliases (`dv`, `dvw`, `dva`,
`dvl`, `dvu`). Symlink it into your custom plugins dir and enable it:

```zsh
ln -s "$HOME/Git/ondrasek/remote-persistent-devenv/completions/oh-my-zsh/devenv" \
      "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/devenv"
# then add `devenv` to plugins=(...) in ~/.zshrc:
#   plugins=(git devenv)
```

`DEVENV_REPO` is the path to this repo checkout; the plugin auto-detects it from
its own symlink-resolved location, so a symlink install needs no configuration.
(If you *copy* the plugin dir instead of symlinking, set `DEVENV_REPO=<repo>` in
`~/.zshrc` before oh-my-zsh loads.)

For `PATH`, the plugin prefers the canonical user bin dir — `$XDG_BIN_HOME`, or
`~/.local/bin` when that's unset. If `devenv`/`devenv-wiz` are symlinked there
(e.g. `ln -s "$DEVENV_REPO/bin/"* "${XDG_BIN_HOME:-$HOME/.local/bin}/"`) it puts
that dir on `PATH`; otherwise it falls back to the repo's own `bin/`, so the
plugin works with or without a separate install step. This alone makes both CLIs
callable with completions — no manual `PATH` or `~/.zfunc` edits.

The completion scripts and the oh-my-zsh plugin are covered by
`bin/tests/test_completions.sh` (needs only bash; the zsh/omz cases are skipped
when zsh is absent).

### Working inside tmux

`Ctrl-B` is the tmux prefix. Cheat sheet:

| Keys           | Action                                  |
|----------------|-----------------------------------------|
| `Ctrl-B  c`    | New window (a fresh shell)              |
| `Ctrl-B  ,`    | Rename current window                   |
| `Ctrl-B  n` / `p` | Next / previous window               |
| `Ctrl-B  N`    | Jump to window N (`Ctrl-B 0` … `9`)     |
| `Ctrl-B  %`    | Split pane vertically                   |
| `Ctrl-B  "`    | Split pane horizontally                 |
| `Ctrl-B  arrow`| Move between panes                      |
| `Ctrl-B  z`    | Zoom current pane to full window        |
| `Ctrl-B  [`    | Enter copy/scrollback mode (`q` to exit)|
| `Ctrl-B  d`    | **Detach** (the magic key)              |

Typical workflow once attached:

```bash
cd /workspace
git clone https://github.com/me/my-project.git
cd my-project

# Window "edit"
Ctrl-B ,    edit
nvim .

# Window "claude"
Ctrl-B c
Ctrl-B ,    claude
cd /workspace/my-project && claude

# Window "codex"
Ctrl-B c
Ctrl-B ,    codex
cd /workspace/my-project && codex
```

You now have three concurrent windows: nvim, Claude Code, Codex — all running against the same checkout, all surviving SSH disconnects.

### Detach — this is the point

Press **`Ctrl-B d`**. SSH closes, your laptop shell returns. Everything you started inside tmux **keeps running on the VPS**:

- nvim stays open with its unsaved buffers.
- Agents keep processing whatever you had them on.
- Background commands (`make`, `pytest --watch`, anything) keep going.

You can close the laptop lid, switch networks, reboot the laptop, or fly to another continent. Reconnect later with `devenv-attach acme` and everything is exactly where you left it.

The chain that makes this work:

1. `ssh` is `exec`ed by `devenv-attach`, not backgrounded — closing it cleanly drops the TTY without killing remote processes.
2. tmux session `main` was started detached by the container's entrypoint; it has no parent process tied to your SSH session.
3. The container was started detached (`podman run -d`) and stays running independent of any login.
4. `loginctl enable-linger` keeps user-level systemd (and therefore the Quadlet-supervised container) alive across all logins / logouts of your VPS user.
5. The VPS itself is, well, always on. That's what VPSes do.

### View what's running

On the VPS:

```bash
./bin/devenv list                                       # devenv-managed containers + their ports
systemctl --user list-units 'devenv-*.service'           # Quadlet-supervised services
```

Inside the container (after attach):

```bash
tmux ls                                                  # tmux sessions (just "main" by default)
tmux lsw -t main                                         # windows in main
ps -ef                                                   # everything alive in the container
```

### Run multiple environments in parallel

Each project gets its own container with its own workspace, SSH port, tmux session, and host keys. They don't share state. Spin up a second one:

```bash
# on the VPS
./bin/devenv up blog
# or via Quadlet (repeat Step 5 Quadlet recipe with NAME=blog, a different PORT)

# on the laptop
cat >> ~/.config/devenv/hosts.conf <<EOF
BLOG_HOST=<vps-ip-or-dns>
BLOG_PORT=2247
EOF

devenv-attach blog                                       # totally separate session
```

`bin/devenv up` allocates ports deterministically from the container name (hash → 2200-2299 range) so the same name always gets the same port across rebuilds.

### Lose a container, keep your work

The hard constraint that drives the design: **every agent commits AND pushes every change.** So even on catastrophic container loss, your work lives on GitHub.

- `./bin/devenv down acme` — stops + removes the container. **All per-container volumes are kept** — `/workspace`, plus the agent-login volumes (`~/.claude`, `~/.codex`, `~/.pi`) and the shell-env volume (`~/.devenv`). `./bin/devenv up acme` later restores the same `/workspace` contents *and* your agent logins.
- `./bin/devenv down acme --purge` — also drops **every** per-container volume (workspace + claude + codex + pi + shellenv). Use for a true clean slate; you will re-`login` to the agents afterward.
- VPS reboot — if you used the Quadlet path, the container comes back automatically. If you used the quick path, run `./bin/devenv up acme` again. Pushed commits are unaffected either way.
- Quadlet service crashed — `systemctl --user restart devenv-acme.service`. Look at `journalctl --user -u devenv-acme.service` first.

### Log in to agents (persists across restarts)

You don't have to put provider API keys in `.env`. Each container has its own
persistent volume for each agent's credentials, so you can **log in once,
interactively, inside the container** and it survives `down`/`up` and crashes:

```bash
./bin/devenv attach acme        # or: devenv-wiz attach acme
# then, inside the tmux session:
claude          # run /login and follow the prompt
codex login
```

The headless SSH login flow shows a URL — open it in your laptop's browser,
authorize, and paste the code back into the container. The credential lands on
that container's `~/.claude` / `~/.codex` / `~/.pi` volume and the agent
auto-refreshes it, so "log in once" effectively means "indefinitely" — strictly
better than a static key in `.env`, which never refreshes.

**Per-container = per-account.** Because each container name has its own
credential volumes, `devenv up work` and `devenv up personal` can be logged into
different Claude/Codex accounts at the same time with no cross-talk. (You can
still set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `.env` instead — they're now
optional. `GH_TOKEN` and git identity remain required.)

> The login credential persists on a host-side named volume (inside the Lima VM
> on macOS). That's an accepted trade-off — see [`docs/credentials.md`](docs/credentials.md).
> `down --purge` deletes it.

### Persistent shell environment

Each container mounts a `~/.devenv` volume holding an `env` file that is sourced
into **every** bash and zsh session (login, SSH, and tmux panes). Use it for
per-container exports, aliases, or extra secrets that should outlive the
container:

```bash
# inside the container — the file is seeded with a commented template on first boot
nvim ~/.devenv/env       # add lines like:  export FOO=bar
# new shells (or: source ~/.devenv/env) pick it up; it survives down/up.
```

It's read with `set -a` semantics, so plain `KEY=VALUE` lines are exported. A
malformed file can't break your shell — the source hook is guarded.

### Mount a host directory (optional)

To give a container read/write access to a directory on your machine, pass
`--mount` at `up` (repeatable). With no `--mount`, nothing extra is mounted:

```bash
./bin/devenv up acme --mount ~/code/myproject
#   -> appears inside the container at /workspace/myproject (read/write)

# explicit target, and more than one:
./bin/devenv up acme --mount ~/code/myproject:/workspace/proj --mount ~/data
```

`devenv-wiz up acme --mount ~/code/myproject` does the same.

> **macOS / Lima prerequisite:** the host directory must sit inside a **writable**
> Lima mount, or the container sees it read-only / not at all. If R/W fails, add
> the path to your Lima VM's config under `mounts:` with `writable: true` and
> restart the VM (`limactl edit <vm>` then `limactl restart <vm>`). The commit-
> and-push discipline still applies to any git repo you mount this way.

### Update the image

```bash
# on the VPS
cd ~/remote-persistent-devenv
git pull
./bin/devenv build

# then restart whichever path you used
systemctl --user restart devenv-acme.service              # Quadlet path
# OR
./bin/devenv down acme && ./bin/devenv up acme            # quick path
```

The workspace volume is independent of the image, so a rebuild does **not** disturb the contents of `/workspace`.

### Rotate the GitHub PAT

When your `GH_TOKEN` expires:

1. Generate a new PAT on GitHub (same `repo` scope, new expiration).
2. Update the `.env` file (the one you launched the container from — `~/.config/devenv/devenv-acme.env` for Quadlet, or `./.env` for the quick path).
3. Restart the container so the new value is loaded into env:
   ```bash
   systemctl --user restart devenv-acme.service
   # OR
   ./bin/devenv down acme && ./bin/devenv up acme
   ```

The credential helper reads `$GH_TOKEN` fresh on every push, so the next `git push` after the restart uses the new token.

## Container image

The image is built from a single `Dockerfile` at the repo root. The same file works under both `docker build` (operator's local Lima + docker-cli setup) and `podman build` (the VPS runtime per ADR 0001).

### Build

```bash
docker build -t devenv:latest .
# or, on the VPS:
podman build -t devenv:latest .
```

No build args. No secrets. Credentials are injected **only at `run` time** via `--env-file .env` (see [`docs/credentials.md`](docs/credentials.md)).

### Smoke test (item B scope)

The entrypoint shipped with item B is a **stub** — it just generates SSH host keys and execs `sshd` in the foreground. Real entrypoint logic (git identity, credential helper, tmux session) lands in item C. Until then, a successful build + a container that stays running is the bar:

```bash
docker build -t devenv:latest .
docker run --rm -d --name devenv-smoke devenv:latest
docker exec devenv-smoke nvim --version | head -n1
docker exec devenv-smoke node --version
docker exec devenv-smoke claude --version || true
docker stop devenv-smoke
```

### Layering rationale

Layers are ordered cheapest-to-rebuild last, so an edit to the entrypoint (which changes most often) doesn't bust the expensive apt + NodeSource layers:

1. **apt base packages** — `ca-certificates`, `curl`, `gnupg`, `git`, `openssh-server`, `tmux`, `sudo`, `locales`, `less`, `jq`, `build-essential`, `python3`, `python3-pip`, `python3-venv`. Single `RUN`; cache cleaned in the same layer.
2. **Node 22 LTS via NodeSource** — `setup_22.x` then `apt-get install nodejs`. Cache cleaned in the same layer.
3. **Agent CLIs (global npm installs)** — `@anthropic-ai/claude-code`, `@openai/codex`, `--ignore-scripts @earendil-works/pi-coding-agent`. Changes when an agent releases.
4. **Neovim upstream tarball** — fetched from `https://github.com/neovim/neovim/releases/latest`, extracted to `/usr/local`. Picks the asset matching `dpkg --print-architecture`: `nvim-linux-x86_64.tar.gz` (with fallback to `nvim-linux64.tar.gz` for older releases) on amd64, `nvim-linux-arm64.tar.gz` on arm64. Debian's repo `nvim` is too old.
5. **User + sshd config** — non-root `dev` (uid 1000, home `/home/dev`), passwordless sudo via `/etc/sudoers.d/90-dev`, `/workspace` owned by `dev:dev`. sshd configured for key-based dev-only login. **Host keys are deliberately empty in the image** — the entrypoint regenerates them on first run, so each container instance has a distinct SSH identity (a hard requirement for parallel-container safety).
6. **entrypoint.sh** — last `COPY`, since this is the most-frequently-edited file during development.

### What is NOT in the image (by design)

- No `.env` content, `GH_TOKEN`, API keys, or any other secret. Credentials are injected at `run` time only.
- No SSH host keys. Generated by the entrypoint on first launch.
- No `~/.ssh/authorized_keys` content for `dev`. Operator provides this at run time via volume mount or entrypoint-side fetch (item C / item E).
- No `.devcontainer/` configs. SSH + tmux is the only supported attach path.

### Image size

Measured on first build (`docker images localhost/remote-persistent-devenv:latest`):

- **Uncompressed (`DISK USAGE`):** ~1.84 GB
- **Compressed (`CONTENT SIZE`):** ~432 MB

`build-essential` and `python3-*` dominate the apt layer. They are kept because pi-coding-agent and most npm packages with native addons need a working C toolchain at install or runtime. Trimming is a future optimization, not an MVP concern.

### Runtime contract (preview, item C)

The container expects to be launched with:

- `--env-file .env` (local docker) or `EnvironmentFile=` (VPS Quadlet) supplying at least `GH_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. See [`.env.example`](.env.example).
- A mounted workspace at `/workspace` (so committed work survives container recreation).
- Port 22 mapped to a host port chosen by the orchestration layer (item E).

The image itself enforces none of this — that's item C's entrypoint and item E's orchestration. The image is the substrate.

## Entrypoint behavior

`entrypoint.sh` runs as PID 1 inside the container, as the non-root `dev` user. It is idempotent — restarting the container reruns it safely.

**Execution order:**

1. **Debug override.** If the operator passes arguments (`docker run image bash`), the entrypoint `exec`s them and the rest of the flow is skipped.
2. **Env-var validation.** Required vars must be set and non-empty; missing ones cause an immediate non-zero exit with a message naming the offender. Values are **never logged**.
3. **SSH host keys.** Generated via `ssh-keygen -A` only if `/etc/ssh/ssh_host_ed25519_key` is absent. This guarantees each container instance gets a distinct SSH identity — a hard requirement for running multiple containers in parallel.
4. **Git identity + credential helper.** Configures `user.name`, `user.email`, `init.defaultBranch=main`, `pull.rebase=false`, and the HTTPS credential helper that returns `${GH_TOKEN}` from process env. The helper is a shell function stored verbatim in `~/.gitconfig`; the token itself is never written to disk in the container.
5. **sshd.** Started in the background via `sudo /usr/sbin/sshd` (daemonized; not `-D`). Listens on port 22 inside the container; map this to a host port via the orchestration layer.
6. **tmux session.** A detached session named `main` is created with a single shell pane. Attach from a client with `ssh -t user@host -p <port> tmux attach -t main`.
7. **PID 1 lifecycle.** The script `wait`s on a background `tail -f /dev/null`, keeping PID 1 alive. `SIGTERM` / `SIGINT` trigger a clean shutdown: `tmux kill-server`, then `sudo pkill sshd`, then `exit 0`.

**Required env vars (entrypoint exits non-zero if missing):**

| Variable          | Purpose                                                |
|-------------------|--------------------------------------------------------|
| `GH_TOKEN`        | GitHub PAT used by the git credential helper for HTTPS push. |
| `GIT_USER_NAME`   | `user.name` in the container's gitconfig.              |
| `GIT_USER_EMAIL`  | `user.email` in the container's gitconfig.             |

**Optional env vars (warned-but-not-failed):**

| Variable            | Purpose                              |
|---------------------|--------------------------------------|
| `ANTHROPIC_API_KEY` | Claude Code authentication.          |
| `OPENAI_API_KEY`    | Codex (`@openai/codex`) authentication. |

The agents themselves enforce their own keys at run time; the entrypoint just surfaces a warning so the operator notices before they `ssh` in.

## Orchestration

Host-side orchestration is a single Bash script, `bin/devenv`, plus two deployment templates. Full doc: [`docs/orchestration.md`](docs/orchestration.md).

```bash
bin/devenv build                  # build the image
bin/devenv up alpha               # start container devenv-alpha (detached)
bin/devenv up bravo               # start another, in parallel, on a different port
bin/devenv list                   # see what's running
bin/devenv attach alpha           # ssh + tmux attach
bin/devenv logs alpha             # tail container logs
bin/devenv down alpha             # stop + remove (volume preserved)
bin/devenv down alpha --purge     # stop + remove + delete workspace volume
```

**Runtime auto-detection:** `bin/devenv` prefers `podman` over `docker` (the VPS target). Override with `DEVENV_RUNTIME=docker|podman`.

**Templates:**
- `orchestration/compose.yaml` — Docker Compose, for the local Lima + docker-cli path.
- `orchestration/devenv.container` — Podman Quadlet template, instantiated per container on the VPS.

## Client-side attach

`bin/devenv-attach` is a thin client-side helper that resolves a symbolic container name to the right `ssh + tmux` invocation. It runs **on your laptop**, not in the container, and reads files only — no dependency on `bin/devenv` being installed locally.

```bash
bin/devenv-attach acme        # remote: read ACME_HOST + ACME_PORT from hosts.conf
bin/devenv-attach -l alpha    # local:  read port from XDG_STATE_HOME/devenv/alpha.port
```

Detach is `Ctrl-B d` (tmux default) and returns you to your local shell — `ssh` is `exec`ed with `-t`, so signals and exit codes propagate through.

**Remote config** — `~/.config/devenv/hosts.conf` (or `$XDG_CONFIG_HOME/devenv/hosts.conf`).

Flat `KEY=VALUE` file, sourced by Bash. For each container name `foo`, set `FOO_HOST` and `FOO_PORT`. The name argument is uppercased (and hyphens become underscores) before lookup, so `devenv-attach my-box` reads `MY_BOX_HOST` / `MY_BOX_PORT`. Template: [`docs/devenv-hosts.example`](docs/devenv-hosts.example).

```ini
ACME_HOST=vps1.example.com
ACME_PORT=2231
BLOG_HOST=vps1.example.com
BLOG_PORT=2247
```

Why this format: parseable by `source` with no third-party dependency, trivial to hand-edit, and the same primitives a Bash user already knows.

**Local mode** — `devenv-attach -l <name>` connects to `localhost` using the port written by `bin/devenv up` at `$XDG_STATE_HOME/devenv/<name>.port`. This is the path for running the container under Lima on macOS while attaching from the same laptop.

**Env overrides:** `DEVENV_USER=<user>` (default `dev`).

**Errors are actionable** — missing config, missing keys, and missing local state each print the exact file path you need to create or fix. SSH's own exit code is propagated on connection failure.

## Smoke test

`scripts/smoke-test.sh` exercises the full happy path end-to-end: build, up, in-container HTTPS git push via the credential helper, host-side push verification, and torn-down cleanup. It retroactively verifies the deferred acceptance criteria of the credential contract (item D).

```bash
DEVENV_SMOKE_REPO=your-handle/devenv-smoke-target ./scripts/smoke-test.sh
```

Pre-flight refuses to run without `docker`/`podman`, an executable `bin/devenv`, a populated `.env`, and a target repo your `GH_TOKEN` can push to. Full details, safety properties, and what is intentionally *not* covered: [`docs/smoke-test.md`](docs/smoke-test.md).
