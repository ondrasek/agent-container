# agent-container

Always-on, containerized development environment for a single operator. Hosts AI coding agents (Claude Code, Codex, pi-coding-agent), `nvim`, `tmux`, and `git` behind OpenSSH. Designed to run on a personal Linux VPS and be attached to over `ssh`.

Design contract: [`CLAUDE.md`](CLAUDE.md).
Runtime + base-image decision: [`docs/decisions/0001-runtime-and-base-image.md`](docs/decisions/0001-runtime-and-base-image.md).
Credential contract: [`docs/credentials.md`](docs/credentials.md).

## How it fits together

```
laptop                                        VPS (Hetzner / Debian 12)
------                                        ------------------------
~/.config/agent-container/hosts.conf                   user systemd (linger enabled)
  ACME_HOST=vps1.example                        |
  ACME_PORT=2218                                +-- Quadlet: agent-container-acme.container
                                                    |
$ agent-container attach acme                                +-- container: agent-container-acme
   |                                                       +-- sshd  (port 2222 -> host 2218)
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

# uv — needed only for the `agent-container` CLI (Quick path below). The Quadlet path
# drives podman via systemd and needs neither uv nor agent-container.
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`enable-linger` is **load-bearing** for the always-on model: it keeps your user-level systemd alive even after you SSH out. Without it, any container managed under user systemd (via Quadlet) gets killed when your SSH session ends. Run it once per user, ever.

### Step 4 — clone, configure, build

```bash
git clone https://github.com/ondrasek/agent-container.git
cd agent-container
cp .env.example .env
chmod 0600 .env
$EDITOR .env       # fill in GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL, agent API keys
uv tool install --editable .   # puts `agent-container` on PATH (editable; needs uv)
agent-container build
```

(If you prefer not to install the tool, `uv run --script bin/agent-container build`
runs it in place.) First build takes ~5-10 minutes (NodeSource, npm globals,
neovim tarball). Subsequent builds reuse cached layers.

### Step 5 — start your first container

Two paths. Pick one per container.

**Quick path** — `agent-container up` (needs `uv` + `agent-container`, installed in Step 4, plus a **Compose v2**-capable runtime). Generates a compose project and runs it on the host (building the image there). Survives SSH disconnects (because of `enable-linger`) but **not** a VPS reboot. Fine for experimentation and for environments you intentionally want to recreate often:

```bash
agent-container up acme
# prints something like:
# [agent-container] name=acme port=2206 env-file=/home/ondra/agent-container/.env
```

Note the port. You'll need it on the laptop side.

**Quadlet path** — recommended for "always-on" production use. systemd supervises the container, restarts it on failure, brings it back on reboot, captures its logs in `journald`:

```bash
mkdir -p ~/.config/containers/systemd ~/.config/agent-container
cp .env ~/.config/agent-container/agent-container-acme.env
chmod 0600 ~/.config/agent-container/agent-container-acme.env

sed -e 's/${NAME}/acme/g' \
    -e "s|\${ENV_FILE}|$HOME/.config/agent-container/agent-container-acme.env|g" \
    -e 's/${PORT}/2218/g' \
    orchestration/agent-container.container \
    > ~/.config/containers/systemd/agent-container-acme.container

systemctl --user daemon-reload
systemctl --user start agent-container-acme.service        # Quadlet generates the .service from .container
systemctl --user status agent-container-acme.service
```

To stop / restart / log:

```bash
systemctl --user stop    agent-container-acme.service
systemctl --user restart agent-container-acme.service
journalctl --user -u agent-container-acme.service -f
```

### Step 6 — grant SSH access from your laptop

Nothing operator-specific is baked into the image, so a fresh container has no
authorized keys of its own. But the SSH identity — `authorized_keys` and the
host key — now lives on the per-container `-ssh` volume (mounted at
`~/.ssh`) and **persists across `down`/`up`**: inject your public key **once** and
it survives every recreate (no more `REMOTE HOST IDENTIFICATION HAS CHANGED`
churn, since the host key is stable too). Pick whichever injection path fits:

**Declare your devices ONCE — the key collection (Feature 020):**

```sh
for d in iPhone iPad Macbook; do cat ~/.ssh/$d.pub; done \
  >> ~/.config/agent-container/authorized_keys
agent-container up acme            # no key flags; all three devices connect
```

Plain `authorized_keys` format, at the user level or per project
(`<project>/.agent-container/authorized_keys`, which **replaces** the user file so a
project can narrow the set). **Removing a key and recreating ends its access**;
anything you added by hand inside the environment survives. `agent-container keys
show acme` prints what the collection says *and* what the environment actually
holds. See [docs/credentials.md](docs/credentials.md#the-key-collection--declare-devices-once-feature-020).

**Per deployment — `up --authorized-key`:**

```bash
agent-container up acme --authorized-key ~/.ssh/id_ed25519.pub
```

The file is delivered read-only and installed onto the `~/.ssh` volume by the
entrypoint before sshd starts.

**Into an already-running container — `agent-container keys`:**

```bash
agent-container keys add acme --authorized-key ~/.ssh/id_ed25519.pub
```

No recreate: the key is streamed over stdin (never on argv), merged with dedup,
and sshd is reloaded in place.

**Via the `.env` file:** set `SSH_AUTHORIZED_KEYS` (newline-separated public keys);
the entrypoint installs them at boot. This is the natural fit for the Quadlet path,
whose credentials already flow through the env-file.

`authorized_keys` are a deduped union of the persisted file plus every injected
source.

**The host key is captured, never supplied.** The container generates its own
ed25519 host key on the `-ssh` volume and it never leaves. Every deploy reads the
**public** half through the runtime and pins it under
`$XDG_STATE_HOME/agent-container/<host>/known_hosts`; `attach` verifies against it and
refuses a mismatch. When nothing is pinned yet, attach warns, shows the fingerprint,
says plainly that accepting **cannot detect a container that was replaced**, and asks.

`--host-key`, `keys --host-key` and `SSH_HOST_ED25519_KEY_B64` were **removed** — they
put a plaintext private key on your disk and verified nothing.

<details>
<summary>Fallback: copy a key in by hand</summary>

If you'd rather not use the first-class paths, you can still write into the
`~/.ssh` volume directly (it persists just the same):

```bash
podman exec -u dev -i agent-container-acme \
    tee -a /home/dev/.ssh/authorized_keys < ~/.ssh/id_ed25519.pub >/dev/null
podman exec -u dev agent-container-acme chmod 0600 /home/dev/.ssh/authorized_keys
```
</details>

### Step 7 — set up `agent-container` on the laptop

On your **laptop**, not the VPS. Install the same CLI (it runs client-side for
attach) and point it at the VPS via `hosts.conf`:

```bash
git clone https://github.com/ondrasek/agent-container.git
uv tool install --editable ./agent-container   # puts `agent-container` on PATH

mkdir -p ~/.config/agent-container
chmod 0700 ~/.config/agent-container
cat >> ~/.config/agent-container/hosts.conf <<EOF
ACME_HOST=<vps-ip-or-dns>
ACME_PORT=2218
EOF
chmod 0600 ~/.config/agent-container/hosts.conf
```

### Step 8 — verify

```bash
agent-container attach acme
```

You should land inside a tmux session named `main`, prompt is `dev@<container-id>:/workspace$`. `tmux ls` shows one session. Detach with `Ctrl-B d`. Re-attach to confirm everything's still there.

## Daily use

### Attach to a container

```bash
agent-container attach acme            # auto: hosts.conf -> remote, else local state file
agent-container attach --local acme    # local (Lima on macOS); reads port from local state file
```

Behind the scenes: `ssh dev@<host> -p <port> -t tmux attach -t main`. The `-t` allocates a TTY (required for tmux); `tmux attach -t main` joins the existing session rather than creating a new one (which would mask bugs).

### The `agent-container` CLI

`agent-container` is the single command for the whole lifecycle — build, start, attach,
logs, stop/start, redeploy, down/wipe — plus an interactive wizard when run with no arguments. It is a
PEP 723 single-file script (`bin/agent-container`) and needs nothing but
[uv](https://docs.astral.sh/uv/) installed:

```bash
agent-container                # guided wizard: state-aware — leads with the one best next step
agent-container context --json # what an AI AGENT reads: state + suggested next step
agent-container skill install  # teach your agent (claude|codex|opencode|pi) to drive this tool
agent-container host add local --docker-context lima-docker --default  # register a host
agent-container host ls        # list registered hosts (where containers run)
agent-container host show hz1 --json   # one host's full record (driver/context/provisioning)
agent-container host rm hz1            # remove the registration only (server left untouched)
agent-container host rm hz1 --destroy  # also deprovision — refused if it still hosts containers
agent-container up acme        # deploy to the default host; --host NAME picks another
agent-container list           # live state: queries each host's daemon + reconciles state files
agent-container list --local --json  # fast local-only view (skips remote round-trips), machine-readable
agent-container stop acme      # pause/reclaim: halt the container, keep it + its volumes
agent-container start acme     # resume a stopped deployment (no rebuild, no recreate)
agent-container redeploy acme  # rebuild the image on the host + recreate, preserving volumes
agent-container down acme      # dispose the container (volumes kept); --purge also drops volumes
agent-container wipe acme      # remove container + volumes + the locally-built image (confirmed)
agent-container attach acme    # hosts.conf -> remote, else local state file; execs ssh
agent-container --self-test    # doctests + port-hash corpus (port hash, key derivation)
```

**Lifecycle verbs and persistence levels.** The deployment moves through three
levels of reclaim: `stop`/`start` (pause — keep everything, just free the
running process), `down` (dispose the container, keep the volumes; `down --purge`
also removes the volumes), and `wipe` (remove the container, its volumes, **and**
the image built for it). `redeploy` rebuilds the image and recreates the
container while preserving the volumes — it is deliberately **non-idempotent**
(always rebuilds; the idempotent no-op path stays `up`). Every mutating verb
takes a per-`(host, name)` lock, so a second lifecycle op on the same deployment
fails fast rather than interleaving. `list` reads **live** host state (querying
each registered host's daemon and reconciling it against the on-disk state
files), so status is truthful after a reboot or an out-of-band change; a dead
host renders `unreachable` (never hangs, never dropped), and `--local` skips the
remote round-trips for the fast local view.

**Sidecar / helper services.** A deployment may declare helper services in an
operator-supplied compose override file, discovered next to the `.env`
(`.agent-container/<name>.services.yaml`, then
`~/.config/agent-container/<name>.services.yaml`). When present it is merged as a
second `-f` into every compose invocation, so the agent and its helpers share one
project and one lifecycle — `up`/`stop`/`start`/`redeploy`/`down`/`wipe` all act
on the unit. The override must be a `services:`-only fragment and must not
redefine the tool-owned `agent` service.

**Execution modes, sessions & workspaces (Feature 004).** `up`/`redeploy` choose
what runs inside and how you interact with it:

```bash
# Interactive (default): the agent in a persistent tmux session you attach to.
agent-container up acme --agent claude --task "triage the failing CI"
agent-container attach acme            # lands on the agent's window

# Headless: the agent runs the task as the container's workload and EXITS with
# its result — a disposable one-shot job (a success is not resurrected).
agent-container up job --mode headless --agent claude --task @task.md            # detached
agent-container up job --mode headless --task "run the tests" --foreground       # stream + exit code
agent-container logs job               # retrieve the output afterward
```

- **`--mode interactive|headless`** (default `interactive`) — interactive keeps
  the container alive (`restart: unless-stopped`) with the agent in a tmux window;
  headless runs the agent non-interactively as PID 1 and the **container's exit
  code is the result** (`restart: on-failure` — a success exits and is not
  restarted; a failure follows the restart policy). Headless `--foreground`
  streams the run and returns that exit code as the CLI's own (it is headless-only).
- **`--agent claude|codex|pi`** (default `claude`) — the primary agent; **`--task
  <text|@file>`** seeds it (interactive) or is the job (headless), delivered as an
  injected file so it never rides the host-side compose model (the CLI's argv/env);
  the entrypoint reads that file and passes it to the agent in-container.
- **`--workspace persistent|bind|ephemeral`** (default `persistent`) — what mounts
  at `/workspace`: a named volume that survives recreation; a local directory
  (**`--workspace-dir`**, local hosts only — a remote host refuses it); or nothing
  (the container layer, **gone on teardown** — commit-and-push or lose it).
- **`--repo <url>`** — clone-on-start for a persistent/ephemeral workspace, credential
  by URL scheme: `git@…`/`ssh://…` uses the container's **own** SSH key (**a first
  boot cannot clone — the forge has never seen the key — so it starts anyway, says
  so, and exits `3`; register, then `redeploy`**), `https://…` uses `GH_TOKEN`.

Detach/reattach is unchanged (tmux survives disconnect; reattach from any machine).
`attach` now probes the live session first, so a session that has ended is reported
clearly (**"nothing running"**, redeploy to start fresh) instead of a silent empty
shell. Execution mode and workspace mode are independently selectable.

**Shell integration — print/emit mode (Feature 005).** Rather than only *invoking*
`ssh`/`docker` for you, the tool can **emit shell-evaluable configuration** to
stdout so you `eval $(…)` it, alias it, or drop it into `~/.ssh/config`:

```bash
agent-container attach acme --print          # prints: ssh dev@localhost -p 2206 -t tmux attach -t main
eval "$(agent-container attach acme --print)"    # run it in YOUR shell (your ssh-agent/config apply)
agent-container attach acme --ssh-config >> ~/.ssh/config   # then: ssh acme
eval "$(agent-container host env hz1)"       # your own `docker` now targets host hz1
eval "$(agent-container host env --unset)"   # revert
agent-container host env hz1 --shell pwsh | Invoke-Expression   # PowerShell idiom
```

- **`attach --print` / `--ssh-config`** — the printed command is byte-for-byte what
  execute runs (execute stays the default). **`host env <name>`** emits the host's
  `DOCKER_CONTEXT`/`CONTAINER_CONNECTION` (or `DOCKER_HOST`/`CONTAINER_HOST` via
  `--endpoint`); `--unset` reverts. **`--shell posix|fish|pwsh`** picks the dialect.
- **The eval contract**: stdout is config-only (humans → stderr); any error emits
  **nothing to stdout** and exits non-zero (so `eval` runs nothing); output is
  eval-safe-quoted; printing has no side effects and **never emits a secret** — only
  connection coordinates. Details: [docs/shell-integration.md](docs/shell-integration.md).

**Agent-as-code — declarative `.agent-container/` projects (Feature 006).** A
directory can *be* the desired state: run the tool inside a project holding a
`.agent-container/` spec and it reconciles reality to the files (Compose/Terraform-
adjacent). Additive — with no `.agent-container/` up the tree, the tool behaves
exactly as today.

```bash
# .agent-container/environments.yaml declares one or more environments (name/host/container/credentials)
agent-container plan        # per-environment: absent / matching / drifted (no mutation)
agent-container apply        # discover -> validate -> plan -> converge (idempotent)
agent-container destroy      # remove only what the spec owns (by deterministic identity)
```

- The spec is parsed with **`yaml.safe_load`** and **validated before any action**
  (a bad field names the offending file+field, no partial change). Ownership derives
  from the **deterministic identity** — no state file. The spec **wins for its scope**
  over the global registry (reported).
- **Spec integrity (FR-020):** when a repo that carries `.agent-container/` becomes
  the agent's workspace, the governing spec is **immutable from inside the
  container** — read only host-side, and delivered **read-only** via the compose-
  `configs` channel (remote-context-safe). An untrusted agent cannot re-govern
  itself. Details: [docs/agent-as-code.md](docs/agent-as-code.md).

**Hosts and the run mechanism.** A *host* is a named target where containers run — a
local or remote container-runtime context, registered with `host add` and stored in
`~/.config/agent-container/hosts.json` (the registry supersedes the older `hosts.conf`
address book, which is still read for attach-only legacy targets). `up`/`down` take
`--host NAME` (default: the registry default). Deployment is **compose-based**: `up`
generates an inspectable compose project under
`$XDG_STATE_HOME/agent-container/<host>/<name>.compose.yaml` and runs it on the host,
building the image **on the host** — so a **Compose v2**-capable runtime is required
(`docker compose` / `podman compose`). Injected SSH identity travels as compose
configs (so it works over a remote context, not just locally). **Server and
container lifecycles are separate:** `down` never touches the server; removing a
tool-provisioned server is the explicit `host rm --destroy`, which is refused while
the server still hosts any container and for hosts the tool did not create.

It keeps all state on disk, namespaced per host (container names, the port hash,
`<host>/<name>.port` state files, env-file resolution, the host registry) so a
container that dies loses nothing. `attach` resolves a target as remote when the name
has a `hosts.conf` entry, else local from the state file — pass `--local`/`--remote`
to force one. `down`/`purge` confirm before destroying anything, so scripts must pass
`-y`/`--yes`.

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
when bumping dependencies in `bin/agent-container` (and in `pyproject.toml`).
`--no-project` keeps the run hermetic: the root `pyproject.toml` otherwise puts
`uv run` in project mode and would sync a `.venv/` at the repo root.

### Install from PyPI

Once published, install `agent-container` onto your `PATH` from PyPI — no checkout
required:

```bash
uv tool install agent-container      # or: pipx install agent-container
agent-container --help
```

A PyPI install is primarily a **client / attach tool**: `attach`, `list`,
`logs`, `down`, `purge`, and `completions` all work standalone (the completion
scripts are bundled as package data). Two commands still need a repo checkout on
the host they run on:

- **`build`** needs a checkout as the docker build context.
- **`up`** needs the image `localhost/agent-container:latest` to already exist locally
  (it dies otherwise). No prebuilt image is published to any registry, so
  producing it requires `build` — hence a checkout. On a fresh host the server
  side still needs a checkout; a pure-PyPI install alone cannot `up` a container.

Point `build` at a checkout explicitly:

```bash
agent-container build --context /path/to/agent-container
# or, once, for the session:
export AGENT_CONTAINER_REPO=/path/to/agent-container
agent-container build
```

`AGENT_CONTAINER_REPO` (or an auto-detected checkout you happen to run from) also lets
the standalone install read the on-disk `completions/` instead of the bundled
copy — handy when hacking on the completions.

### Install as a uv tool (editable, for development)

For working **on** `agent-container`, install it editable so `git pull` keeps the
`PATH` command current and `build` / `completions` resolve the live repo files:

```bash
uv tool install --editable /path/to/agent-container
#   installs ~/.local/bin/agent-container; `git pull` keeps it current (editable)
uv tool upgrade agent-container     # after dependency bumps
uv tool uninstall agent-container
```

The `uv run --script bin/agent-container` path and the oh-my-zsh plugin are unaffected
by installing the tool; if the repo's `bin/` is also on `PATH` (e.g. via the
plugin), both resolve to the same code — harmless.

### Shell completions

`agent-container` ships bash and zsh completions under [`completions/`](completions/):
subcommands, per-subcommand flags (including the repeatable `--mount`), and
**container-name completion** for `up` / `down` / `attach` / `logs` / `purge`.
Names are gathered directly in the shell from your per-host state files
(`$XDG_STATE_HOME/agent-container/<host>/*.port`) and `hosts.conf` — no `docker`,
`podman`, or `uv` is spawned on Tab, so completion stays instant and works offline.

Completion triggers on the command **name**, so put the tool on your `PATH`
(this also lets the `build` / `completions` subcommands find the repo):

```bash
# add the repo's bin/ to PATH (in ~/.bashrc or ~/.zshrc)
export PATH="$HOME/agent-container/bin:$PATH"
```

**bash** — source the script (works with or without the `bash-completion`
package):

```bash
# ~/.bashrc
source "$HOME/agent-container/completions/agent-container.bash"
# or generate it: agent-container completions bash > ~/.local/share/bash-completion/completions/agent-container
```

**zsh** — drop the script onto `$fpath` as `_agent-container`, then `compinit`:

```zsh
mkdir -p ~/.zfunc
agent-container completions zsh > ~/.zfunc/_agent-container
# ~/.zshrc, before compinit:
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

**oh-my-zsh** — a plugin under [`completions/oh-my-zsh/agent-container/`](completions/oh-my-zsh/agent-container/)
bundles PATH wiring, the completion, and aliases (`ae`, `aeu`, `aea`, `ael`).
Symlink it into your custom plugins dir and enable it:

```zsh
ln -s "$HOME/Git/ondrasek/agent-container/completions/oh-my-zsh/agent-container" \
      "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/agent-container"
# then add `agent-container` to plugins=(...) in ~/.zshrc:
#   plugins=(git agent-container)
```

`AGENT_CONTAINER_REPO` is the path to this repo checkout; the plugin auto-detects it from
its own symlink-resolved location, so a symlink install needs no configuration.
(If you *copy* the plugin dir instead of symlinking, set `AGENT_CONTAINER_REPO=<repo>` in
`~/.zshrc` before oh-my-zsh loads.)

For `PATH`, the plugin prefers the canonical user bin dir — `$XDG_BIN_HOME`, or
`~/.local/bin` when that's unset. If `agent-container` is symlinked there
(e.g. `ln -s "$AGENT_CONTAINER_REPO/bin/agent-container" "${XDG_BIN_HOME:-$HOME/.local/bin}/"`)
it puts that dir on `PATH`; otherwise it falls back to the repo's own `bin/`, so
the plugin works with or without a separate install step. This alone makes
`agent-container` callable with completions — no manual `PATH` or `~/.zfunc` edits.

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

You can close the laptop lid, switch networks, reboot the laptop, or fly to another continent. Reconnect later with `agent-container attach acme` and everything is exactly where you left it.

The chain that makes this work:

1. `ssh` is `exec`ed by `agent-container attach`, not backgrounded — closing it cleanly drops the TTY without killing remote processes.
2. tmux session `main` was started detached by the container's entrypoint; it has no parent process tied to your SSH session.
3. The container was started detached (`podman run -d`) and stays running independent of any login.
4. `loginctl enable-linger` keeps user-level systemd (and therefore the Quadlet-supervised container) alive across all logins / logouts of your VPS user.
5. The VPS itself is, well, always on. That's what VPSes do.

### View what's running

On the VPS:

```bash
agent-container list                                       # agent-container-managed containers + their ports
systemctl --user list-units 'agent-container-*.service'           # Quadlet-supervised services
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
agent-container up blog
# or via Quadlet (repeat Step 5 Quadlet recipe with NAME=blog, a different PORT)

# on the laptop
cat >> ~/.config/agent-container/hosts.conf <<EOF
BLOG_HOST=<vps-ip-or-dns>
BLOG_PORT=2247
EOF

agent-container attach blog                                       # totally separate session
```

`agent-container up` allocates ports deterministically from the container name (hash → 2200-2299 range) so the same name always gets the same port across rebuilds.

### Lose a container, keep your work

The hard constraint that drives the design: **every agent commits AND pushes every change.** So even on catastrophic container loss, your work lives on GitHub.

- `agent-container down acme` — stops + removes the container. **All per-container volumes are kept** — `/workspace`, plus the agent-login volumes (`~/.claude`, `~/.codex`, `~/.pi`), the shell-env volume (`~/.agent-env`), the tmux-config volume (`~/.config/tmux`), and the SSH-identity volume (`~/.ssh`). `agent-container up acme` later restores the same `/workspace` contents *and* your agent logins *and* your `tmux.conf` *and* your SSH host key + authorized_keys.
- `agent-container down acme --purge` — also drops **every** per-container volume (workspace + claude + codex + pi + shellenv + tmux + ssh). Use for a true clean slate; you will re-`login` to the agents afterward and re-inject your SSH key.
- VPS reboot — if you used the Quadlet path, the container comes back automatically. If you used the quick path, run `agent-container up acme` again. Pushed commits are unaffected either way.
- Quadlet service crashed — `systemctl --user restart agent-container-acme.service`. Look at `journalctl --user -u agent-container-acme.service` first.

### Log in to agents (persists across restarts)

You don't have to put provider API keys in `.env`. Each container has its own
persistent volume for each agent's credentials, so you can **log in once,
interactively, inside the container** and it survives `down`/`up` and crashes:

```bash
agent-container attach acme        # or: agent-container attach --local acme
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
credential volumes, `agent-container up work` and `agent-container up personal` can be logged into
different Claude/Codex accounts at the same time with no cross-talk. (You can
still set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `.env` instead — they're now
optional. `GH_TOKEN` and git identity remain required.)

> The login credential persists on a host-side named volume (inside the Lima VM
> on macOS). That's an accepted trade-off — see [`docs/credentials.md`](docs/credentials.md).
> `down --purge` deletes it.

### Preflight — `doctor` (Feature 013)

Ask whether a deploy would work, without attempting one and **without changing anything**:

```bash
agent-container doctor                 # this project's environments + the machine
agent-container doctor acme --json     # one environment, machine-readable
agent-container doctor && agent-container up acme
```

Every check reports **pass / fail / unknown** — three states, because a check that cannot complete
and reports *pass* is worse than no check at all. Every finding names the action that fixes it, and
one run reports **all** problems rather than stopping at the first. Exit `0` when a deploy would
succeed (advisories and unknowns permitted), `1` on a blocking failure, `2` if `doctor` itself could
not run.

It reads credential *declarations* but never **resolves** one — for a manager source, resolving is
the prompt — so no secret value is retrieved at all. Full contract:
[`docs/doctor.md`](docs/doctor.md).

### Manage from a phone — the control plane (Feature 017)

An SSH-reachable container holding a **configured** CLI, so the management surface is something you
attach to rather than something that lives only on your laptop:

```bash
agent-container up hub --role control-plane
agent-container attach hub          # `list`, `stop`, `redeploy` — nothing to configure on arrival
```

It runs a narrower image with **no agent CLI installed**, mints its own **passphrase-protected**
keypair, and enumerates your hosts **live** — naming any it could not reach rather than showing a
short list that looks complete. Output switches to a block form at 80 columns automatically, because
the operator on a phone should not have to remember a flag.

**Read [`docs/control-plane.md`](docs/control-plane.md) before deploying one.** This is the
highest-risk feature in the tool: a session in it reaches a sandbox shell *and* machine-level daemon
access, the passphrase is printed **once** and is **unrecoverable**, and `revoke` is the only
concrete way to narrow its reach. `panic` from inside excludes its own container and says so.

### The observability trail (Feature 017)

Every container now keeps a **local trail** and can **export it** to an OTLP collector you declare.
The two legs are independent and carry identical payloads:

```bash
agent-container telemetry collect      # download the trail from every host
agent-container telemetry reconcile    # do the two legs agree?
```

Export is a `curl` POST from the entrypoint — **zero added dependencies** — fires at **write time**
(so a `kill -9` does not lose what was already written), and is **fail-open**: an unreachable
collector degrades to the local record and reports the gap. `accepted` on a record means *the
endpoint returned success for it*, never that a backend holds it. The **task text is exported by
default**; see [`docs/observability.md`](docs/observability.md) for why, and how to exclude it.

### Credential model (the agent's SSH key, API keys, canonical config)

Beyond interactive login, `up`/`redeploy` inject an agent's credentials and
config at runtime under a strict **least-exposure** discipline — a tool-injected
secret lands under `/run/agent-container/…` (ephemeral) and is **never** copied
onto a persistent volume (it vanishes with the container; your local copy is the
sole durable copy). Full contract: [`docs/credentials.md`](docs/credentials.md).

- **The agent's own SSH key pair (the default push channel).** The container
  **generates** an ed25519 key on first boot at `~/.ssh/id_ed25519` and the
  **private half never leaves it**. You register the **public** half:

  ```bash
  agent-container ssh-key show acme     # paste into the forge as a deploy key
  agent-container ssh-key rotate acme   # a new key, workspace intact
  ```

  Nothing wires it — the conventional path is the whole mechanism, so `git`, `ssh`,
  `scp` and `rsync` all use it. The key is **distinct** from the inbound sshd host
  key, and it **persists across a recreate** (regenerating each boot would silently
  invalidate what you registered); `down --purge` rotates it and warns that it did.

  This is a least-privilege gain, not only a hygiene one: a per-container key
  registered on one repository authorises **one repository**, where the removed
  `--push-key` was in practice your *personal* key. HTTPS + `GH_TOKEN` remains the
  alternative. `--known-hosts` / `PUSH_KNOWN_HOSTS` stay — they verify the
  **forge**, which is the opposite direction and public data.

  > **No private key of any kind is written to your disk.** Feature 018 removed the
  > host key, 019 removed the agent key; the tool has no channel that accepts one,
  > and `--push-key` / `SSH_PUSH_KEY_B64` / `target: push_key` are **refused with an
  > explanation** rather than silently ignored.

- **File-first API keys.** Drop a per-provider key file next to your `.env` and
  it is discovered and injected **ephemerally** (Claude gets an `apiKeyHelper`;
  Codex/pi get an ephemeral `$HOME` redirect so their `auth.json` never touches
  the volume):

  ```
  ./agent-container.acme.anthropic.key      # or .openai.key, ...
  ```

- **Canonical config, fresh each deploy.** Operator-owned, non-secret settings /
  guidance / tool defs delivered fresh on every deploy (local edits propagate on
  `redeploy`) while the agent's mutable runtime state persists on its volume:

  ```
  ./agent-container.acme.config/.claude/settings.json   # + CLAUDE.md, MCP defs, ...
  ```

  A config file that embeds a secret is treated **as a secret** (ephemeral), not
  persisted. Rotating any secret is just a local edit + `redeploy`.

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
`AGENT_CONTAINER_TMUX_WINDOWS`; see [Entrypoint behavior](#entrypoint-behavior).

### Mount a host directory (optional)

To give a container read/write access to a directory on your machine, pass
`--mount` at `up` (repeatable). With no `--mount`, nothing extra is mounted:

```bash
agent-container up acme --mount ~/code/myproject
#   -> appears inside the container at /workspace/myproject (read/write)

# explicit target, and more than one:
agent-container up acme --mount ~/code/myproject:/workspace/proj --mount ~/data
```

> **macOS / Lima prerequisite:** the host directory must sit inside a **writable**
> Lima mount, or the container sees it read-only / not at all. If R/W fails, add
> the path to your Lima VM's config under `mounts:` with `writable: true` and
> restart the VM (`limactl edit <vm>` then `limactl restart <vm>`). The commit-
> and-push discipline still applies to any git repo you mount this way.

### Update the image

```bash
# on the VPS
cd ~/agent-container
git pull
agent-container build

# then restart whichever path you used
systemctl --user restart agent-container-acme.service              # Quadlet path
# OR
agent-container down acme && agent-container up acme            # quick path
```

The workspace volume is independent of the image, so a rebuild does **not** disturb the contents of `/workspace`.

### Rotate the GitHub PAT

When your `GH_TOKEN` expires:

1. Generate a new PAT on GitHub (same `repo` scope, new expiration).
2. Update the `.env` file (the one you launched the container from — `~/.config/agent-container/agent-container-acme.env` for Quadlet, or `./.env` for the quick path).
3. Restart the container so the new value is loaded into env:
   ```bash
   systemctl --user restart agent-container-acme.service
   # OR
   agent-container down acme && agent-container up acme
   ```

The credential helper reads `$GH_TOKEN` fresh on every push, so the next `git push` after the restart uses the new token.

## Container image

The image is built from a single `Dockerfile` at the repo root. The same file works under both `docker build` (operator's local Lima + docker-cli setup) and `podman build` (the VPS runtime per ADR 0001).

### Build

```bash
docker build -t agent-container:latest .
# or, on the VPS:
podman build -t agent-container:latest .
```

No build args. No secrets. Credentials are injected **only at `run` time** via `--env-file .env` (see [`docs/credentials.md`](docs/credentials.md)).

### Build sanity check

The entrypoint requires credentials (`GH_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL`) and exits immediately without them, so a bare `docker run` won't stay up. To verify the image built and the tooling is present **without** wiring up an `.env`, use the entrypoint's **debug override** — any arguments passed after the image are `exec`'d instead of the sshd + tmux flow:

```bash
docker build -t agent-container:latest .
docker run --rm agent-container:latest \
  bash -lc 'nvim --version | head -n1; node --version; claude --version || true'
```

For a full end-to-end check (build → launch with credentials → in-container HTTPS git push → host-side verify → teardown), run `scripts/smoke-test.sh` — see [Smoke test](#smoke-test) and [`docs/smoke-test.md`](docs/smoke-test.md).

### Layering rationale

Layers are ordered cheapest-to-rebuild last, so an edit to the entrypoint (which changes most often) doesn't bust the expensive apt + NodeSource layers:

1. **apt base packages** — `ca-certificates`, `curl`, `gnupg`, `git`, `openssh-server`, `tmux`, `zsh`, `locales`, `less`, `jq`, `build-essential`, `python3`, `python3-pip`, `python3-venv`. No `sudo` — the runtime is rootless. Single `RUN`; cache cleaned in the same layer.
2. **Node 22 LTS via NodeSource** — `setup_22.x` then `apt-get install nodejs`. Cache cleaned in the same layer.
3. **Agent CLIs (global npm installs)** — `@anthropic-ai/claude-code`, `@openai/codex`, `--ignore-scripts @earendil-works/pi-coding-agent`. Changes when an agent releases.
4. **Neovim upstream tarball** — fetched from `https://github.com/neovim/neovim/releases/latest`, extracted to `/usr/local`. Picks the asset matching `dpkg --print-architecture`: `nvim-linux-x86_64.tar.gz` (with fallback to `nvim-linux64.tar.gz` for older releases) on amd64, `nvim-linux-arm64.tar.gz` on arm64. Debian's repo `nvim` is too old.
5. **User + rootless sshd config** — non-root `dev` (uid 1000, home `/home/dev`), no `sudo`/root at runtime, `/workspace` owned by `dev:dev`. sshd is configured for key-based dev-only login on the unprivileged **port 2222** (`UsePAM no`, `HostKey`/`PidFile` under the dev-owned `~/.ssh` volume), and is started **by** `dev`. **No host key is baked into the image** — the entrypoint installs an injected key or generates an ed25519 one onto the persisted `-ssh` volume, so each container has a distinct but **stable** SSH identity across `down`/`up` (a hard requirement for parallel-container safety).
6. **entrypoint.sh** — last `COPY`, since this is the most-frequently-edited file during development.

### What is NOT in the image (by design)

- No `.env` content, `GH_TOKEN`, API keys, or any other secret. Credentials are injected at `run` time only.
- No SSH host key baked into the image. The entrypoint generates an ed25519 key (or installs an injected one) onto the per-container `-ssh` volume, so the identity **persists** across `down`/`up` instead of being regenerated each launch.
- No `~/.ssh/authorized_keys` content for `dev` in the image. The operator declares it in a key collection (Feature 020) or injects it at run time — `up --authorized-key`, `agent-container keys add <name>`, or `SSH_AUTHORIZED_KEYS` in the env-file. The tool-managed portion is **rewritten on every boot** from the collection, so removing a key and recreating withdraws it; anything outside that region is preserved.
- No `sudo` / root at runtime. The image is **rootless**: sshd runs as `dev` on port 2222 and all dependencies are baked at build time (agents never `apt install`), so root is never needed.
- No `.devcontainer/` configs. SSH + tmux is the only supported attach path.

### Image size

Measured on first build (`docker images localhost/agent-container:latest`):

- **Uncompressed (`DISK USAGE`):** ~1.84 GB
- **Compressed (`CONTENT SIZE`):** ~432 MB

`build-essential` and `python3-*` dominate the apt layer. They are kept because pi-coding-agent and most npm packages with native addons need a working C toolchain at install or runtime. Trimming is a future optimization, not an MVP concern.

### Runtime contract (preview, item C)

The container expects to be launched with:

- `--env-file .env` (local docker) or `EnvironmentFile=` (VPS Quadlet) supplying at least `GH_TOKEN`, `GIT_USER_NAME`, `GIT_USER_EMAIL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. See [`.env.example`](.env.example).
- A mounted workspace at `/workspace` (so committed work survives container recreation).
- Container-internal port 2222 (rootless sshd) mapped to a host port chosen by the orchestration layer (item E).

The image itself enforces none of this — that's item C's entrypoint and item E's orchestration. The image is the substrate.

## Entrypoint behavior

`entrypoint.sh` runs as PID 1 inside the container, as the non-root `dev` user. The container is **fully rootless**: no `sudo` package, no root at runtime — all system dependencies are baked at build time (agents never `apt install` at runtime), so root buys nothing and is dropped. It is idempotent — restarting the container reruns it safely.

**Execution order:**

1. **Debug override.** If the operator passes arguments (`docker run image bash`), the entrypoint `exec`s them and the rest of the flow is skipped.
2. **Env-var validation.** Required vars must be set and non-empty; missing ones cause an immediate non-zero exit with a message naming the offender. Values are **never logged**.
3. **SSH host key + authorized_keys (rootless).** The host key is an ed25519 key under `~/.ssh/hostkeys` — dev-owned, on the persisted `-ssh` volume — so a container keeps a **stable** identity across `down`/`up` while different containers differ. It is **generated in the container and never leaves**: the entrypoint keeps the persisted key or creates one, and derives the world-readable `.pub` the tool captures at deploy to pin (Feature 018). `authorized_keys` holds a tool-managed region, **replaced on every boot** from the resolved admit set (the key collection plus any `--authorized-key`/`SSH_AUTHORIZED_KEYS`); content outside the region is preserved byte-for-byte. It used to be a union with the persisted file, which meant a key injected once could never be withdrawn. No root or `sudo` is involved.
4. **Git identity + credential helper.** Configures `user.name`, `user.email`, `init.defaultBranch=main`, `pull.rebase=false`, and the HTTPS credential helper that returns `${GH_TOKEN}` from process env. The helper is a shell function stored verbatim in `~/.gitconfig` and **scoped to `https://github.com`** (`credential.https://github.com.helper`) so the token is never handed to any other host; the token itself is never written to disk in the container.
5. **sshd.** Started in the background as the `dev` user (rootless — no `sudo`), daemonized (not `-D`). Listens on the unprivileged port **2222** inside the container, using the host key + pidfile under the dev-owned `~/.ssh` volume; the orchestration layer maps this to the operator-facing host port (the hashed `2200 +` value, unchanged).
6. **tmux session.** A detached session named `main` is created on first launch. Its windows are built from `AGENT_CONTAINER_TMUX_WINDOWS` (space-separated names, default `shell edit agents`); each window is a **bare shell** (no agent is auto-started). Set `AGENT_CONTAINER_TMUX_WINDOWS=""` (empty) to opt out and get a single window. Window names are validated against `[A-Za-z0-9._-]+`; invalid ones are skipped. The layout is built only when the session is first created, so a container restart never duplicates windows. Attach from a client with `ssh -t user@host -p <port> tmux attach -t main` (or `agent-container attach <name> --window <w>` to land in a specific window). The tmux config dir `~/.config/tmux` is a per-container volume, so a `tmux.conf` (and tpm plugins) you drop there persist across `down`/`up`.
7. **PID 1 lifecycle.** The script `wait`s on a background `tail -f /dev/null`, keeping PID 1 alive. `SIGTERM` / `SIGINT` trigger a clean shutdown: `tmux kill-server`, then `pkill -TERM -x sshd` (dev signals its own rootless sshd — no `sudo`), then `exit 0`.

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

Host-side orchestration is the single `agent-container` CLI, plus two deployment templates. Full doc: [`docs/orchestration.md`](docs/orchestration.md).

```bash
agent-container build                  # build the image
agent-container up alpha               # start container agent-container-alpha (detached)
agent-container up bravo               # start another, in parallel, on a different port
agent-container list                   # see what's running
agent-container attach alpha           # ssh + tmux attach
agent-container attach alpha --window edit  # attach and select the 'edit' window
agent-container logs alpha             # tail container logs
agent-container down alpha             # stop + remove (all volumes preserved)
agent-container down alpha --purge     # stop + remove + delete ALL per-container volumes
```

**Runtime auto-detection:** the default is platform-aware — on macOS (Lima + docker-cli) `agent-container` prefers `docker`, on Linux (the VPS) it prefers `podman`, falling back to the other. Override with `AGENT_CONTAINER_RUNTIME=docker|podman`.

**Templates:**
- `orchestration/compose.yaml` — Docker Compose, for the local Lima + docker-cli path.
- `orchestration/agent-container.container` — Podman Quadlet template, instantiated per container on the VPS.

## Client-side attach

`agent-container attach` resolves a symbolic container name to the right `ssh + tmux` invocation. It runs **on your laptop** (reading `hosts.conf` and local state files) and hands over to `ssh`:

```bash
agent-container attach acme                 # remote: read ACME_HOST + ACME_PORT from hosts.conf
agent-container attach --local alpha        # local:  read port from XDG_STATE_HOME/agent-container/alpha.port
agent-container attach --window edit acme   # select the 'edit' tmux window on attach
```

`--window`/`-w NAME` selects a tmux window in session `main` before attaching, so you land where you want. The name is validated against `[A-Za-z0-9._-]+`. If the window does not exist, tmux stays on the current one and still attaches.

Detach is `Ctrl-B d` (tmux default) and returns you to your local shell — `ssh` is `exec`ed with `-t`, so signals and exit codes propagate through.

**Remote config** — `~/.config/agent-container/hosts.conf` (or `$XDG_CONFIG_HOME/agent-container/hosts.conf`).

Flat `KEY=VALUE` file. For each container name `foo`, set `FOO_HOST` and `FOO_PORT`. The name argument is uppercased (and hyphens become underscores) before lookup, so `agent-container attach my-box` reads `MY_BOX_HOST` / `MY_BOX_PORT`. Template: [`docs/agent-container-hosts.example`](docs/agent-container-hosts.example).

```ini
ACME_HOST=vps1.example.com
ACME_PORT=2231
BLOG_HOST=vps1.example.com
BLOG_PORT=2247
```

Why this format: trivial to hand-edit and the same primitives a shell user already knows. `agent-container` parses it line-by-line and **never** sources or executes it (values with `$` or backticks are taken literally, with a one-time warning).

**Local mode** — `agent-container attach --local <name>` connects to `localhost` using the port written by `agent-container up` at `$XDG_STATE_HOME/agent-container/<name>.port`. This is the path for running the container under Lima on macOS while attaching from the same laptop.

**Env overrides:** `AGENT_CONTAINER_USER=<user>` (default `dev`), `AGENT_CONTAINER_HOST=<host>` (default `localhost` for local targets).

**Errors are actionable** — missing config, missing keys, and missing local state each print the exact file path you need to create or fix. SSH's own exit code is propagated on connection failure.

## Smoke test

`scripts/smoke-test.sh` exercises the full happy path end-to-end: build, up, in-container HTTPS git push via the credential helper, host-side push verification, and torn-down cleanup. It retroactively verifies the deferred acceptance criteria of the credential contract (item D).

```bash
AGENT_CONTAINER_SMOKE_REPO=your-handle/agent-container-smoke-target ./scripts/smoke-test.sh
```

Pre-flight refuses to run without `docker`/`podman`, `uv` plus `bin/agent-container`, a populated `.env`, and a target repo your `GH_TOKEN` can push to. Full details, safety properties, and what is intentionally *not* covered: [`docs/smoke-test.md`](docs/smoke-test.md).

## Releasing — Continuous Deployment

Releases are **fully automated** — there is no manual tagging and no release PR.
**Every substantive merge to `main` is a release.**

1. Land a change on `main` with a [Conventional Commit](https://www.conventionalcommits.org/)
   message: `feat:` → minor, `fix:` → patch, `feat!:`/`BREAKING CHANGE:` → minor
   (while pre-1.0). `docs:`/`ci:`/`chore:`/`test:`/`style:` merges cut **no** release.
2. `ci.yml` runs the full pipeline (lint · test matrix · shell · build · acceptance).
3. Once `ci` is green on `main`, `publish.yml` fires (via `workflow_run`).
   [python-semantic-release](https://python-semantic-release.readthedocs.io/) computes
   the next version from the commits, bumps `pyproject.toml` + `CHANGELOG.md`, commits
   `chore(release): X.Y.Z [skip ci]`, tags `vX.Y.Z`, creates the GitHub Release, and
   publishes the wheel + sdist to PyPI via **Trusted Publishing** (OIDC — no stored
   token). A red pipeline never ships (the release is gated on `ci` success).

The version is single-sourced in `pyproject.toml`; check the installed version with
`agent-container --version`.

**One-time operator setup (arming CD):**
1. Configure the [PyPI trusted publisher](https://docs.pypi.org/trusted-publishers/)
   for the `agent-container` project (owner `ondrasek`, repo `agent-container`,
   workflow `publish.yml`, environment `release`).
2. Arm the pipeline: `gh variable set RELEASE_ENABLED --body true`.

Until `RELEASE_ENABLED` is set, `publish.yml` stays dormant (so a release can't
half-fire before PyPI is ready). After both steps, releases are automatic and
need no stored secrets.

## License

MIT — see [`LICENSE`](LICENSE).
