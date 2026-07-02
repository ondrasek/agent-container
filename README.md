# agent-env

Always-on, containerized development environment for a single operator. Hosts AI coding agents (Claude Code, Codex, pi-coding-agent), `nvim`, `tmux`, and `git` behind OpenSSH. Designed to run on a personal Linux VPS and be attached to over `ssh`.

Design contract: [`CLAUDE.md`](CLAUDE.md).
Runtime + base-image decision: [`docs/decisions/0001-runtime-and-base-image.md`](docs/decisions/0001-runtime-and-base-image.md).
Credential contract: [`docs/credentials.md`](docs/credentials.md).

## How it fits together

```
laptop                                        VPS (Hetzner / Debian 12)
------                                        ------------------------
~/.config/agent-env/hosts.conf                   user systemd (linger enabled)
  ACME_HOST=vps1.example                        |
  ACME_PORT=2218                                +-- Quadlet: agent-env-acme.container
                                                    |
$ agent-env attach acme                                +-- container: agent-env-acme
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

# uv — needed only for the `agent-env` CLI (Quick path below). The Quadlet path
# drives podman via systemd and needs neither uv nor agent-env.
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`enable-linger` is **load-bearing** for the always-on model: it keeps your user-level systemd alive even after you SSH out. Without it, any container managed under user systemd (via Quadlet) gets killed when your SSH session ends. Run it once per user, ever.

### Step 4 — clone, configure, build

```bash
git clone https://github.com/ondrasek/agent-env.git
cd agent-env
cp .env.example .env
chmod 0600 .env
$EDITOR .env       # fill in GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL, agent API keys
uv tool install --editable .   # puts `agent-env` on PATH (editable; needs uv)
agent-env build
```

(If you prefer not to install the tool, `uv run --script bin/agent-env build`
runs it in place.) First build takes ~5-10 minutes (NodeSource, npm globals,
neovim tarball). Subsequent builds reuse cached layers.

### Step 5 — start your first container

Two paths. Pick one per container.

**Quick path** — `agent-env up` (needs `uv` + `agent-env`, installed in Step 4). Runs `podman run -d`. Survives SSH disconnects (because of `enable-linger`) but **not** a VPS reboot. Fine for experimentation and for environments you intentionally want to recreate often:

```bash
agent-env up acme
# prints something like:
# [agent-env] name=acme port=2218 env-file=/home/ondra/agent-env/.env
```

Note the port. You'll need it on the laptop side.

**Quadlet path** — recommended for "always-on" production use. systemd supervises the container, restarts it on failure, brings it back on reboot, captures its logs in `journald`:

```bash
mkdir -p ~/.config/containers/systemd ~/.config/agent-env
cp .env ~/.config/agent-env/agent-env-acme.env
chmod 0600 ~/.config/agent-env/agent-env-acme.env

sed -e 's/${NAME}/acme/g' \
    -e "s|\${ENV_FILE}|$HOME/.config/agent-env/agent-env-acme.env|g" \
    -e 's/${PORT}/2218/g' \
    orchestration/agent-env.container \
    > ~/.config/containers/systemd/agent-env-acme.container

systemctl --user daemon-reload
systemctl --user start agent-env-acme.service        # Quadlet generates the .service from .container
systemctl --user status agent-env-acme.service
```

To stop / restart / log:

```bash
systemctl --user stop    agent-env-acme.service
systemctl --user restart agent-env-acme.service
journalctl --user -u agent-env-acme.service -f
```

### Step 6 — grant SSH access from your laptop

The container starts with **no** keys in `dev`'s `authorized_keys` (per the hard constraint that nothing operator-specific lives in the image). One-time setup, on the VPS, after first launch:

```bash
# inside the container, set up .ssh
podman exec -u dev agent-env-acme install -d -m 0700 /home/dev/.ssh

# copy your laptop's pubkey into the container
podman exec -u dev -i agent-env-acme \
    tee -a /home/dev/.ssh/authorized_keys < ~/.ssh/authorized_keys >/dev/null

# tighten perms
podman exec -u dev agent-env-acme chmod 0600 /home/dev/.ssh/authorized_keys
```

(This step is a known wart of the MVP — a future iteration will accept an `AUTHORIZED_KEYS` env var or a mounted file so it happens automatically at container start. Tracked separately.)

### Step 7 — set up `agent-env` on the laptop

On your **laptop**, not the VPS. Install the same CLI (it runs client-side for
attach) and point it at the VPS via `hosts.conf`:

```bash
git clone https://github.com/ondrasek/agent-env.git
uv tool install --editable ./agent-env   # puts `agent-env` on PATH

mkdir -p ~/.config/agent-env
chmod 0700 ~/.config/agent-env
cat >> ~/.config/agent-env/hosts.conf <<EOF
ACME_HOST=<vps-ip-or-dns>
ACME_PORT=2218
EOF
chmod 0600 ~/.config/agent-env/hosts.conf
```

### Step 8 — verify

```bash
agent-env attach acme
```

You should land inside a tmux session named `main`, prompt is `dev@<container-id>:/workspace$`. `tmux ls` shows one session. Detach with `Ctrl-B d`. Re-attach to confirm everything's still there.

## Daily use

### Attach to a container

```bash
agent-env attach acme            # auto: hosts.conf -> remote, else local state file
agent-env attach --local acme    # local (Lima on macOS); reads port from local state file
```

Behind the scenes: `ssh dev@<host> -p <port> -t tmux attach -t main`. The `-t` allocates a TTY (required for tmux); `tmux attach -t main` joins the existing session rather than creating a new one (which would mask bugs).

### The `agent-env` CLI

`agent-env` is the single command for the whole lifecycle — build, start, attach,
logs, stop, purge — plus an interactive wizard when run with no arguments. It is a
PEP 723 single-file script (`bin/agent-env`) and needs nothing but
[uv](https://docs.astral.sh/uv/) installed:

```bash
agent-env                # interactive menu: build, start, attach, logs, stop, purge
agent-env up acme        # every menu action has a scriptable subcommand
agent-env list --json    # machine-readable state (merges runtime ps + state files)
agent-env attach acme    # hosts.conf -> remote, else local state file; execs ssh
agent-env --self-test    # doctests + port-hash corpus (port hash, key derivation)
```

It keeps all state on disk (container names, the port hash, `<name>.port` state
files, env-file resolution, `hosts.conf`) so a container that dies loses nothing.
`attach` resolves a target as remote when the name has a `hosts.conf` entry, else
local from the state file — pass `--local`/`--remote` to force one. `down`/`purge`
confirm before destroying anything, so scripts must pass `-y`/`--yes`.

The CLI has a pytest suite in `bin/tests/` that pins its on-disk contract (port
hash, naming, env-file resolution, hosts.conf parsing, generated `run`/`ssh`
argv) and the platform-aware runtime default. It needs no container runtime or
ssh — only uv:

```bash
uv run --no-project --with pytest \
       --with 'typer>=0.12,<1' --with 'questionary>=2.0,<3' --with 'rich>=13,<15' \
       pytest bin/tests
```

The `--with` pins mirror the script's PEP 723 inline metadata — keep them in sync
when bumping dependencies in `bin/agent-env` (and in `pyproject.toml`).
`--no-project` keeps the run hermetic: the root `pyproject.toml` otherwise puts
`uv run` in project mode and would sync a `.venv/` at the repo root.

### Install from PyPI

Once published, install `agent-env` onto your `PATH` from PyPI — no checkout
required:

```bash
uv tool install agent-env      # or: pipx install agent-env
agent-env --help
```

A PyPI install is primarily a **client / attach tool**: `attach`, `list`,
`logs`, `down`, `purge`, and `completions` all work standalone (the completion
scripts are bundled as package data). Two commands still need a repo checkout on
the host they run on:

- **`build`** needs a checkout as the docker build context.
- **`up`** needs the image `localhost/agent-env:latest` to already exist locally
  (it dies otherwise). No prebuilt image is published to any registry, so
  producing it requires `build` — hence a checkout. On a fresh host the server
  side still needs a checkout; a pure-PyPI install alone cannot `up` a container.

Point `build` at a checkout explicitly:

```bash
agent-env build --context /path/to/agent-env
# or, once, for the session:
export AGENT_ENV_REPO=/path/to/agent-env
agent-env build
```

`AGENT_ENV_REPO` (or an auto-detected checkout you happen to run from) also lets
the standalone install read the on-disk `completions/` instead of the bundled
copy — handy when hacking on the completions.

### Install as a uv tool (editable, for development)

For working **on** `agent-env`, install it editable so `git pull` keeps the
`PATH` command current and `build` / `completions` resolve the live repo files:

```bash
uv tool install --editable /path/to/agent-env
#   installs ~/.local/bin/agent-env; `git pull` keeps it current (editable)
uv tool upgrade agent-env     # after dependency bumps
uv tool uninstall agent-env
```

The `uv run --script bin/agent-env` path and the oh-my-zsh plugin are unaffected
by installing the tool; if the repo's `bin/` is also on `PATH` (e.g. via the
plugin), both resolve to the same code — harmless.

### Shell completions

`agent-env` ships bash and zsh completions under [`completions/`](completions/):
subcommands, per-subcommand flags (including the repeatable `--mount`), and
**container-name completion** for `up` / `down` / `attach` / `logs` / `purge`.
Names are gathered directly in the shell from your state files
(`$XDG_STATE_HOME/agent-env/*.port`) and `hosts.conf` — no `docker`, `podman`, or
`uv` is spawned on Tab, so completion stays instant and works offline.

Completion triggers on the command **name**, so put the tool on your `PATH`
(this also lets the `build` / `completions` subcommands find the repo):

```bash
# add the repo's bin/ to PATH (in ~/.bashrc or ~/.zshrc)
export PATH="$HOME/agent-env/bin:$PATH"
```

**bash** — source the script (works with or without the `bash-completion`
package):

```bash
# ~/.bashrc
source "$HOME/agent-env/completions/agent-env.bash"
# or generate it: agent-env completions bash > ~/.local/share/bash-completion/completions/agent-env
```

**zsh** — drop the script onto `$fpath` as `_agent-env`, then `compinit`:

```zsh
mkdir -p ~/.zfunc
agent-env completions zsh > ~/.zfunc/_agent-env
# ~/.zshrc, before compinit:
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

**oh-my-zsh** — a plugin under [`completions/oh-my-zsh/agent-env/`](completions/oh-my-zsh/agent-env/)
bundles PATH wiring, the completion, and aliases (`ae`, `aeu`, `aea`, `ael`).
Symlink it into your custom plugins dir and enable it:

```zsh
ln -s "$HOME/Git/ondrasek/agent-env/completions/oh-my-zsh/agent-env" \
      "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/agent-env"
# then add `agent-env` to plugins=(...) in ~/.zshrc:
#   plugins=(git agent-env)
```

`AGENT_ENV_REPO` is the path to this repo checkout; the plugin auto-detects it from
its own symlink-resolved location, so a symlink install needs no configuration.
(If you *copy* the plugin dir instead of symlinking, set `AGENT_ENV_REPO=<repo>` in
`~/.zshrc` before oh-my-zsh loads.)

For `PATH`, the plugin prefers the canonical user bin dir — `$XDG_BIN_HOME`, or
`~/.local/bin` when that's unset. If `agent-env` is symlinked there
(e.g. `ln -s "$AGENT_ENV_REPO/bin/agent-env" "${XDG_BIN_HOME:-$HOME/.local/bin}/"`)
it puts that dir on `PATH`; otherwise it falls back to the repo's own `bin/`, so
the plugin works with or without a separate install step. This alone makes
`agent-env` callable with completions — no manual `PATH` or `~/.zfunc` edits.

The completion script and the oh-my-zsh plugin are covered by
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

You can close the laptop lid, switch networks, reboot the laptop, or fly to another continent. Reconnect later with `agent-env attach acme` and everything is exactly where you left it.

The chain that makes this work:

1. `ssh` is `exec`ed by `agent-env attach`, not backgrounded — closing it cleanly drops the TTY without killing remote processes.
2. tmux session `main` was started detached by the container's entrypoint; it has no parent process tied to your SSH session.
3. The container was started detached (`podman run -d`) and stays running independent of any login.
4. `loginctl enable-linger` keeps user-level systemd (and therefore the Quadlet-supervised container) alive across all logins / logouts of your VPS user.
5. The VPS itself is, well, always on. That's what VPSes do.

### View what's running

On the VPS:

```bash
agent-env list                                       # agent-env-managed containers + their ports
systemctl --user list-units 'agent-env-*.service'           # Quadlet-supervised services
```

Inside the container (after attach):

```bash
tmux ls                                                  # tmux sessions (just "main" by default)
tmux lsw -t main                                         # windows in main (default: shell, edit, agents)
ps -ef                                                   # everything alive in the container
```

### Run multiple environments in parallel

Each project gets its own container with its own workspace, SSH port, tmux session, and host keys. They don't share state. Spin up a second one:

```bash
# on the VPS
agent-env up blog
# or via Quadlet (repeat Step 5 Quadlet recipe with NAME=blog, a different PORT)

# on the laptop
cat >> ~/.config/agent-env/hosts.conf <<EOF
BLOG_HOST=<vps-ip-or-dns>
BLOG_PORT=2247
EOF

agent-env attach blog                                       # totally separate session
```

`agent-env up` allocates ports deterministically from the container name (hash → 2200-2299 range) so the same name always gets the same port across rebuilds.

### Lose a container, keep your work

The hard constraint that drives the design: **every agent commits AND pushes every change.** So even on catastrophic container loss, your work lives on GitHub.

- `agent-env down acme` — stops + removes the container. **All per-container volumes are kept** — `/workspace`, plus the agent-login volumes (`~/.claude`, `~/.codex`, `~/.pi`), the shell-env volume (`~/.agent-env`), and the tmux-config volume (`~/.config/tmux`). `agent-env up acme` later restores the same `/workspace` contents *and* your agent logins *and* your `tmux.conf`.
- `agent-env down acme --purge` — also drops **every** per-container volume (workspace + claude + codex + pi + shellenv + tmux). Use for a true clean slate; you will re-`login` to the agents afterward.
- VPS reboot — if you used the Quadlet path, the container comes back automatically. If you used the quick path, run `agent-env up acme` again. Pushed commits are unaffected either way.
- Quadlet service crashed — `systemctl --user restart agent-env-acme.service`. Look at `journalctl --user -u agent-env-acme.service` first.

### Log in to agents (persists across restarts)

You don't have to put provider API keys in `.env`. Each container has its own
persistent volume for each agent's credentials, so you can **log in once,
interactively, inside the container** and it survives `down`/`up` and crashes:

```bash
agent-env attach acme        # or: agent-env attach --local acme
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
credential volumes, `agent-env up work` and `agent-env up personal` can be logged into
different Claude/Codex accounts at the same time with no cross-talk. (You can
still set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `.env` instead — they're now
optional. `GH_TOKEN` and git identity remain required.)

> The login credential persists on a host-side named volume (inside the Lima VM
> on macOS). That's an accepted trade-off — see [`docs/credentials.md`](docs/credentials.md).
> `down --purge` deletes it.

### Persistent shell environment

Each container mounts a `~/.agent-env` volume holding an `env` file that is sourced
into **every** bash and zsh session (login, SSH, and tmux panes). Use it for
per-container exports, aliases, or extra secrets that should outlive the
container:

```bash
# inside the container — the file is seeded with a commented template on first boot
nvim ~/.agent-env/env       # add lines like:  export FOO=bar
# new shells (or: source ~/.agent-env/env) pick it up; it survives down/up.
```

It's read with `set -a` semantics, so plain `KEY=VALUE` lines are exported. A
malformed file can't break your shell — the source hook is guarded.

### Persistent tmux config

Each container also mounts a `~/.config/tmux` volume (XDG standard; tmux 3.x
reads `~/.config/tmux/tmux.conf`). Drop your `tmux.conf` and any
[tpm](https://github.com/tmux-plugins/tpm) plugins there and they survive
`down`/`up`:

```bash
# inside the container
nvim ~/.config/tmux/tmux.conf    # e.g. set -g mouse on
tmux source ~/.config/tmux/tmux.conf   # or start a fresh session to pick it up
```

The default window layout (`shell edit agents`) is set by the entrypoint via
`AGENT_ENV_TMUX_WINDOWS`; see [Entrypoint behavior](#entrypoint-behavior).

### Mount a host directory (optional)

To give a container read/write access to a directory on your machine, pass
`--mount` at `up` (repeatable). With no `--mount`, nothing extra is mounted:

```bash
agent-env up acme --mount ~/code/myproject
#   -> appears inside the container at /workspace/myproject (read/write)

# explicit target, and more than one:
agent-env up acme --mount ~/code/myproject:/workspace/proj --mount ~/data
```

> **macOS / Lima prerequisite:** the host directory must sit inside a **writable**
> Lima mount, or the container sees it read-only / not at all. If R/W fails, add
> the path to your Lima VM's config under `mounts:` with `writable: true` and
> restart the VM (`limactl edit <vm>` then `limactl restart <vm>`). The commit-
> and-push discipline still applies to any git repo you mount this way.

### Update the image

```bash
# on the VPS
cd ~/agent-env
git pull
agent-env build

# then restart whichever path you used
systemctl --user restart agent-env-acme.service              # Quadlet path
# OR
agent-env down acme && agent-env up acme            # quick path
```

The workspace volume is independent of the image, so a rebuild does **not** disturb the contents of `/workspace`.

### Rotate the GitHub PAT

When your `GH_TOKEN` expires:

1. Generate a new PAT on GitHub (same `repo` scope, new expiration).
2. Update the `.env` file (the one you launched the container from — `~/.config/agent-env/agent-env-acme.env` for Quadlet, or `./.env` for the quick path).
3. Restart the container so the new value is loaded into env:
   ```bash
   systemctl --user restart agent-env-acme.service
   # OR
   agent-env down acme && agent-env up acme
   ```

The credential helper reads `$GH_TOKEN` fresh on every push, so the next `git push` after the restart uses the new token.

## Container image

The image is built from a single `Dockerfile` at the repo root. The same file works under both `docker build` (operator's local Lima + docker-cli setup) and `podman build` (the VPS runtime per ADR 0001).

### Build

```bash
docker build -t agent-env:latest .
# or, on the VPS:
podman build -t agent-env:latest .
```

No build args. No secrets. Credentials are injected **only at `run` time** via `--env-file .env` (see [`docs/credentials.md`](docs/credentials.md)).

### Smoke test (item B scope)

The entrypoint shipped with item B is a **stub** — it just generates SSH host keys and execs `sshd` in the foreground. Real entrypoint logic (git identity, credential helper, tmux session) lands in item C. Until then, a successful build + a container that stays running is the bar:

```bash
docker build -t agent-env:latest .
docker run --rm -d --name agent-env-smoke agent-env:latest
docker exec agent-env-smoke nvim --version | head -n1
docker exec agent-env-smoke node --version
docker exec agent-env-smoke claude --version || true
docker stop agent-env-smoke
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

Measured on first build (`docker images localhost/agent-env:latest`):

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
6. **tmux session.** A detached session named `main` is created on first launch. Its windows are built from `AGENT_ENV_TMUX_WINDOWS` (space-separated names, default `shell edit agents`); each window is a **bare shell** (no agent is auto-started). Set `AGENT_ENV_TMUX_WINDOWS=""` (empty) to opt out and get a single window. Window names are validated against `[A-Za-z0-9._-]+`; invalid ones are skipped. The layout is built only when the session is first created, so a container restart never duplicates windows. Attach from a client with `ssh -t user@host -p <port> tmux attach -t main` (or `agent-env attach <name> --window <w>` to land in a specific window). The tmux config dir `~/.config/tmux` is a per-container volume, so a `tmux.conf` (and tpm plugins) you drop there persist across `down`/`up`.
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

Host-side orchestration is the single `agent-env` CLI, plus two deployment templates. Full doc: [`docs/orchestration.md`](docs/orchestration.md).

```bash
agent-env build                  # build the image
agent-env up alpha               # start container agent-env-alpha (detached)
agent-env up bravo               # start another, in parallel, on a different port
agent-env list                   # see what's running
agent-env attach alpha           # ssh + tmux attach
agent-env attach alpha --window edit  # attach and select the 'edit' window
agent-env logs alpha             # tail container logs
agent-env down alpha             # stop + remove (all volumes preserved)
agent-env down alpha --purge     # stop + remove + delete ALL per-container volumes
```

**Runtime auto-detection:** the default is platform-aware — on macOS (Lima + docker-cli) `agent-env` prefers `docker`, on Linux (the VPS) it prefers `podman`, falling back to the other. Override with `AGENT_ENV_RUNTIME=docker|podman`.

**Templates:**
- `orchestration/compose.yaml` — Docker Compose, for the local Lima + docker-cli path.
- `orchestration/agent-env.container` — Podman Quadlet template, instantiated per container on the VPS.

## Client-side attach

`agent-env attach` resolves a symbolic container name to the right `ssh + tmux` invocation. It runs **on your laptop** (reading `hosts.conf` and local state files) and hands over to `ssh`:

```bash
agent-env attach acme                 # remote: read ACME_HOST + ACME_PORT from hosts.conf
agent-env attach --local alpha        # local:  read port from XDG_STATE_HOME/agent-env/alpha.port
agent-env attach --window edit acme   # select the 'edit' tmux window on attach
```

`--window`/`-w NAME` selects a tmux window in session `main` before attaching, so you land where you want. The name is validated against `[A-Za-z0-9._-]+`. If the window does not exist, tmux stays on the current one and still attaches.

Detach is `Ctrl-B d` (tmux default) and returns you to your local shell — `ssh` is `exec`ed with `-t`, so signals and exit codes propagate through.

**Remote config** — `~/.config/agent-env/hosts.conf` (or `$XDG_CONFIG_HOME/agent-env/hosts.conf`).

Flat `KEY=VALUE` file. For each container name `foo`, set `FOO_HOST` and `FOO_PORT`. The name argument is uppercased (and hyphens become underscores) before lookup, so `agent-env attach my-box` reads `MY_BOX_HOST` / `MY_BOX_PORT`. Template: [`docs/agent-env-hosts.example`](docs/agent-env-hosts.example).

```ini
ACME_HOST=vps1.example.com
ACME_PORT=2231
BLOG_HOST=vps1.example.com
BLOG_PORT=2247
```

Why this format: trivial to hand-edit and the same primitives a shell user already knows. `agent-env` parses it line-by-line and **never** sources or executes it (values with `$` or backticks are taken literally, with a one-time warning).

**Local mode** — `agent-env attach --local <name>` connects to `localhost` using the port written by `agent-env up` at `$XDG_STATE_HOME/agent-env/<name>.port`. This is the path for running the container under Lima on macOS while attaching from the same laptop.

**Env overrides:** `AGENT_ENV_USER=<user>` (default `dev`), `AGENT_ENV_HOST=<host>` (default `localhost` for local targets).

**Errors are actionable** — missing config, missing keys, and missing local state each print the exact file path you need to create or fix. SSH's own exit code is propagated on connection failure.

## Smoke test

`scripts/smoke-test.sh` exercises the full happy path end-to-end: build, up, in-container HTTPS git push via the credential helper, host-side push verification, and torn-down cleanup. It retroactively verifies the deferred acceptance criteria of the credential contract (item D).

```bash
AGENT_ENV_SMOKE_REPO=your-handle/agent-env-smoke-target ./scripts/smoke-test.sh
```

Pre-flight refuses to run without `docker`/`podman`, `uv` plus `bin/agent-env`, a populated `.env`, and a target repo your `GH_TOKEN` can push to. Full details, safety properties, and what is intentionally *not* covered: [`docs/smoke-test.md`](docs/smoke-test.md).

## Releasing

`agent-env` publishes to PyPI via **Trusted Publishing** (OIDC — no API tokens
stored in the repo). To cut a release:

1. Bump `version` in `pyproject.toml`, commit, and push.
2. Confirm `.github/workflows/ci.yml` is green for that commit (it runs the
   pytest suite and `uv build` on every push/PR). CI does not run on tag pushes,
   so this is a check on the pushed commit, not an automatic gate on the tag.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.

Pushing a `v*` tag triggers `.github/workflows/publish.yml`, which **re-runs the
pytest suite**, then builds the sdist + wheel with `uv build` and uploads them
through `pypa/gh-action-pypi-publish` using a short-lived OIDC token. Because the
suite runs first in the `build` job and `publish` `needs: build`, a red tagged
commit fails the build and never reaches PyPI. **One-time setup:**
the operator configures the [PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/)
for the `agent-env` project (owner `ondrasek`, repo `agent-env`, workflow
`publish.yml`, environment `release`) — after that, releases need no secrets.

## License

MIT — see [`LICENSE`](LICENSE).
