# Installation

There are two sides to an `agent-container` setup, and they have different
requirements:

| | What runs there | What it needs |
|---|---|---|
| **Your laptop** (the client) | `attach`, `ls`, `logs`, `plan`, `down`, `completions` | [uv](https://docs.astral.sh/uv/) and an `ssh` client |
| **The host** (where containers live) | the image, the containers, `build`, `up` | Podman or Docker with **Compose v2**, and a checkout of this repository |

A PyPI install alone is a fine **client**. It cannot `up` a container on a fresh
host, because `up` needs the image `localhost/agent-container:latest` to already
exist and no prebuilt image is published to any registry — producing it requires
`build`, which needs a checkout as the build context.

## Prerequisites

- **Python 3.14.** The CLI uses 3.14-only syntax. You do not have to install it
  yourself; `uv` fetches it.
- **[uv](https://docs.astral.sh/uv/).** The one hard prerequisite on the client.

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- **A container runtime on the host** — Podman (the default, per
  [ADR 0001](site:docs/decisions/0001-runtime-and-base-image/)) or Docker. It must
  be **Compose v2**-capable: deployment generates a compose project and runs it on
  the host.

## Install the CLI

### From PyPI — the normal path

```bash
uv tool install agent-container
agent-container --help
agent-container --version
```

`pipx install agent-container` works equally well. Both put the command on your
`PATH`; the completion scripts ship as package data, so completions work from a
PyPI install with no checkout.

### From a checkout, editable — for development

Install it editable so `git pull` keeps the `PATH` command current, and so
`build` and `completions` resolve the live repository files:

```bash
git clone https://github.com/ondrasek/agent-container.git
cd agent-container
uv tool install --editable .
#   installs ~/.local/bin/agent-container, tracking your checkout
uv tool upgrade agent-container      # after a dependency bump
uv tool uninstall agent-container
```

### Without installing anything

The CLI is a single [PEP 723](https://peps.python.org/pep-0723/) script. Run it
in place; `uv` resolves its inline dependency metadata on the fly:

```bash
uv run --script bin/agent-container --help
```

## Point `build` at a checkout

If you installed from PyPI but want to build the image, tell `build` where the
build context is — the repository is the context:

```bash
agent-container build --context /path/to/agent-container

# or, once, for the session:
export AGENT_CONTAINER_REPO=/path/to/agent-container
agent-container build
```

`AGENT_CONTAINER_REPO` also lets a standalone install read the on-disk
`completions/` rather than the bundled copy — useful while hacking on them.

## Prepare the host

On the machine where containers will actually run — a VPS, or a local VM:

```bash
sudo apt-get update
sudo apt-get install -y podman git netcat-openbsd
loginctl enable-linger "$USER"
```

`enable-linger` is **load-bearing** for the always-on model. It keeps your
user-level systemd alive after you SSH out; without it, anything supervised under
user systemd is killed when your session ends. Run it once per user, ever.

Then clone and build:

```bash
git clone https://github.com/ondrasek/agent-container.git
cd agent-container
cp .env.example .env
chmod 0600 .env
$EDITOR .env        # GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL, agent API keys
agent-container build
```

The first build takes roughly 5–10 minutes (NodeSource, npm globals, the neovim
tarball). Later builds reuse cached layers.

The [tutorial](site:tutorial/) walks this from an empty Hetzner VPS, including the
operator user, SSH access and the two supervision paths.

## Register a host

A *host* is a named target where containers run — a local or remote
container-runtime context, stored in `~/.config/agent-container/hosts.json`.

```bash
agent-container host add hz1 --docker-context vps1 --default
agent-container host ls
agent-container host show hz1 --json
```

On macOS a local host is typically a Lima VM:

```bash
agent-container host add local --docker-context lima-docker --default
```

## Check that it will work

`doctor` reports whether a deploy would succeed **without performing one**. It
changes nothing.

```bash
agent-container doctor
```

Run it before you file a bug; its output is the useful half of a report. See
[the doctor documentation](site:docs/doctor/) for what each check means and why
*absent*, *defaulted*, *declared-empty* and *unexamined* are four different
answers.

## Shell completions

The completions cover subcommands, per-subcommand flags (including the repeatable
`--mount`) and **container-name completion** for `up`, `down`, `attach`, `logs`
and `purge`. Names come straight from your per-host state files in the shell — no
`docker`, `podman` or `uv` is spawned on Tab, so completion stays instant and
works offline.

Completion triggers on the command **name**, so the tool must be on your `PATH`.

### bash

```bash
# ~/.bashrc
source "$HOME/agent-container/completions/agent-container.bash"

# or generate it:
agent-container completions bash > ~/.local/share/bash-completion/completions/agent-container
```

### zsh

```zsh
mkdir -p ~/.zfunc
agent-container completions zsh > ~/.zfunc/_agent-container

# ~/.zshrc, before compinit:
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

### oh-my-zsh

The plugin bundles `PATH` wiring, the completion and the aliases `ae`, `aeu`,
`aea`, `ael`. Symlink it in and enable it:

```zsh
ln -s "$HOME/Git/ondrasek/agent-container/completions/oh-my-zsh/agent-container" \
      "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/agent-container"
# then add agent-container to plugins=(...) in ~/.zshrc:
#   plugins=(git agent-container)
```

The plugin auto-detects the repository from its own symlink-resolved location, so
a symlink install needs no configuration. If you *copy* the directory instead,
set `AGENT_CONTAINER_REPO=<repo>` in `~/.zshrc` before oh-my-zsh loads.

## Teach your agent to drive the tool

`agent-container` has a machine-readable surface, and it will install the skill
that describes it into a local agent config for you:

```bash
agent-container skill install          # claude | codex | opencode | pi
agent-container context --json         # state plus the suggested next step
agent-container commands               # every command, argument and effect
```

Details in [the agent interface documentation](site:docs/agent-interface/).

## Verify the install

```bash
agent-container --version
agent-container --self-test     # doctests plus the port-hash and key-derivation corpus
agent-container ls
```

## Where files land

Configuration is two levels, project winning, with the **same filename at both**;
plaintext credentials are **user-level only**. `AGENT_CONTAINER_ROOT` relocates
config, state and data together; per-directory variables beat it, and XDG is the
fallback. Pre-011 layouts are **refused, not silently migrated**.

The one map is [the layout documentation](site:docs/layout/).
