# Tutorial

This walks a fresh Linux VPS to a running, always-on agent environment you attach
to over SSH and detach from without losing anything. It uses Hetzner Cloud for
step 1; **nothing after that is Hetzner-specific** — any Debian 12 or Ubuntu 24.04
host behaves identically.

Budget about thirty minutes, most of it the first image build.

> Already have a host and just want the CLI? Go to
> [Installation](site:install/) instead. Want to see the tool applying a real
> specification? Go to [Samples](site:samples/).

## Step 1 — provision the VPS

In the Hetzner Cloud Console choose **Create Server**. The smallest shared-CPU
instance is more than enough: the image is about 1.8 GB on disk and an idle dev
container costs roughly 50 MB of RAM. Pick **Debian 12** or **Ubuntu 24.04** and
add your laptop's SSH public key during provisioning.

You should now be able to reach it:

```bash
ssh root@<vps-ip>
```

## Step 2 — create an operator user

Don't run dev environments as root. From `root@vps`:

```bash
adduser --gecos "" --disabled-password ondra     # use your own username
usermod -aG sudo ondra
install -d -m 0700 -o ondra -g ondra /home/ondra/.ssh
cp /root/.ssh/authorized_keys /home/ondra/.ssh/
chown ondra:ondra /home/ondra/.ssh/authorized_keys
chmod 0600 /home/ondra/.ssh/authorized_keys
```

From here on you connect as `ssh ondra@<vps-ip>`. Disabling root SSH login in
`/etc/ssh/sshd_config` is a worthwhile next step, and out of scope here.

## Step 3 — install Podman and enable lingering

```bash
sudo apt-get update
sudo apt-get install -y podman git netcat-openbsd
loginctl enable-linger "$USER"

# uv — needed only for the agent-container CLI (the quick path in step 5).
# The Quadlet path drives podman via systemd and needs neither.
curl -LsSf https://astral.sh/uv/install.sh | sh
```

<div class="callout">
<span class="label">Why lingering matters</span>

`enable-linger` is **load-bearing** for the always-on model: it keeps your
user-level systemd alive even after you SSH out. Without it, any container
managed under user systemd is killed the moment your session ends. Run it once
per user, ever.
</div>

## Step 4 — clone, configure, build

```bash
git clone https://github.com/ondrasek/agent-container.git
cd agent-container
cp .env.example .env
chmod 0600 .env
$EDITOR .env         # GH_TOKEN, GIT_USER_NAME, GIT_USER_EMAIL, agent API keys
uv tool install --editable .    # puts `agent-container` on PATH, tracking the checkout
agent-container build
```

If you'd rather not install the tool, `uv run --script bin/agent-container build`
runs it in place. The first build takes 5–10 minutes — NodeSource, the npm
globals, the neovim tarball. Later builds reuse cached layers.

Before going further, ask the tool whether a deploy would work. It changes
nothing:

```bash
agent-container doctor
```

## Step 5 — start your first container

Two paths. Pick one **per container**.

### Quick path — `agent-container up`

Needs `uv`, the CLI from step 4, and a **Compose v2**-capable runtime. It
generates a compose project and runs it on the host, building the image there.
Survives SSH disconnects (thanks to lingering) but **not** a VPS reboot — fine for
experimentation and for environments you intend to recreate often.

```bash
agent-container up acme
# [agent-container] name=acme port=2206 env-file=/home/ondra/agent-container/.env
```

**Note the port.** You need it on the laptop side.

### Quadlet path — recommended for always-on use

systemd supervises the container, restarts it on failure, brings it back after a
reboot and captures its logs in `journald`.

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
systemctl --user start agent-container-acme.service
systemctl --user status agent-container-acme.service
```

Quadlet generates the `.service` unit from the `.container` file. To manage it:

```bash
systemctl --user stop    agent-container-acme.service
systemctl --user restart agent-container-acme.service
journalctl --user -u agent-container-acme.service -f
```

## Step 6 — grant SSH access from your laptop

Nothing operator-specific is baked into the image, so a fresh container has no
authorized keys of its own. The SSH identity — `authorized_keys` and the host key
— lives on the per-container `-ssh` volume mounted at `~/.ssh` and **persists
across `down`/`up`**. Inject your public key once and it survives every recreate.

### Declare your devices once — the key collection

The recommended path. Plain `authorized_keys` format, at the user level or per
project:

```sh
for d in iPhone iPad Macbook; do cat ~/.ssh/$d.pub; done \
  >> ~/.config/agent-container/authorized_keys
agent-container up acme          # no key flags; all three devices connect
```

A project file (`<project>/.agent-container/authorized_keys`) **replaces** the
user file, so a project can narrow the set. **Removing a key and recreating ends
its access** — anything you added by hand inside the environment survives. To see
both sides:

```bash
agent-container keys show acme   # what the collection says AND what the environment holds
```

### The other injection paths

```bash
# per deployment — pass it on each recreate
agent-container up acme --authorized-key ~/.ssh/id_ed25519.pub

# into an already-running container, no recreate
agent-container keys add acme --authorized-key ~/.ssh/id_ed25519.pub
```

`keys add` streams the key over stdin — never on argv — and merges it with dedup
into the tool-managed region. sshd needs no reload; it re-reads `authorized_keys`
on every connection.

For the Quadlet path, whose credentials already flow through the env-file, set
`SSH_AUTHORIZED_KEYS` (newline-separated public keys) in that file instead.

<div class="callout warn">
<span class="label">The grant lasts only until the next recreate</span>

The tool does not create access it cannot withdraw, so `down`/`up` removes a
per-deployment key along with everything else the tool wrote. To make a key
permanent, put it in the collection.

`authorized_keys` holds a tool-managed region that is **replaced on every boot**
from the resolved admit set; everything outside that region is preserved
byte-for-byte. It used to be a deduped union with the persisted file — which
meant a key injected once could never be withdrawn.
</div>

<div class="callout">
<span class="label">The host key is captured, never supplied</span>

The container generates its own ed25519 host key on the `-ssh` volume, and it
never leaves. Every deploy reads the **public** half and pins it under
`$XDG_STATE_HOME/agent-container/<host>/known_hosts`; `attach` verifies against
that pin and **refuses a mismatch rather than prompting**. When nothing is pinned
yet, attach warns, shows the fingerprint, says plainly that accepting cannot
detect a container that was replaced, and asks.

`--host-key`, `keys --host-key` and `SSH_HOST_ED25519_KEY_B64` were **removed**:
they put a plaintext private key on your disk and verified nothing.
</div>

## Step 7 — set up the CLI on your laptop

On your **laptop**, not the VPS. Install the same CLI — it runs client-side for
attach — and point it at the VPS:

```bash
git clone https://github.com/ondrasek/agent-container.git
uv tool install --editable ./agent-container

mkdir -p ~/.config/agent-container
chmod 0700 ~/.config/agent-container
cat >> ~/.config/agent-container/hosts.conf <<EOF
ACME_HOST=<vps-ip-or-dns>
ACME_PORT=2218
EOF
chmod 0600 ~/.config/agent-container/hosts.conf
```

Or install from PyPI instead — `uv tool install agent-container` — which is
plenty for a pure client. See [Installation](site:install/).

## Step 8 — attach, and verify the point of all this

```bash
agent-container attach acme
```

You land inside a tmux session named `main`, with the prompt
`dev@<container-id>:/workspace$`. `tmux ls` shows one session.

Now the part that matters:

1. Start something long-running in a pane — an agent, a build, `top`.
2. Press <kbd>Ctrl-B</kbd> then <kbd>d</kbd> to detach. You are back on your laptop.
3. Close the terminal. Close the laptop.
4. Later, from **any** machine whose key is admitted: `agent-container attach acme`.

Everything is where you left it. Behind the scenes attach is just
`ssh dev@<host> -p <port> -t tmux attach -t main` — the `-t` allocates the TTY
tmux needs, and `attach -t main` joins the existing session rather than creating a
new one, which would mask exactly the bug you care about.

<div class="callout warn">
<span class="label">The one way to lose work</span>

Detach is non-destructive at every layer, but **the container is not your backup**.
The design contract forbids relying on container persistence: every agent must
`commit` **and** `push` every change. If work only exists in the container, one
`wipe` ends it.
</div>

## What to do next

### Run an agent on a task

```bash
# interactive: the agent in a tmux window you attach to
agent-container up acme --agent claude --task "triage the failing CI"
agent-container attach acme

# headless: the agent IS the workload and the container's exit code is the result
agent-container up job --mode headless --task @task.md
agent-container up job --mode headless --task "run the tests" --foreground
agent-container logs job
```

Read [execution modes](site:docs/execution/) for what `--workspace` and `--repo`
do, including why a first SSH clone-on-start **cannot** clone and exits 3.

### Move the whole thing into version control

Rather than passing flags, let a directory *be* the desired state:

```bash
agent-container plan       # per environment: absent / matching / drifted — mutates nothing
agent-container apply      # converge, idempotently
agent-container destroy    # remove only what the spec owns
```

The [samples](site:samples/) are four such specifications you can apply today, and
[agent as code](site:docs/agent-as-code/) explains the schema.

### Learn the lifecycle verbs

| Verb | What survives |
|---|---|
| `stop` / `start` | everything — this only frees the running process |
| `down` | the volumes (add `--purge` to drop them too) |
| `redeploy` | the volumes; the image is rebuilt and the container recreated |
| `wipe` | nothing — container, volumes **and** the built image are removed |

`ls` reads **live** state, querying each registered host's daemon and reconciling
it against the on-disk state files, so status stays truthful after a reboot or an
out-of-band change. A dead host renders `unreachable` — never `stopped`, and never
silently dropped.

### Put a boundary around it

```bash
agent-container egress acme    # what the boundary refused, and what it allowed that you never declared
agent-container panic          # stop everything this tool is running, everywhere
```

See [egress control](site:docs/egress/) and the
[threat model](site:docs/threat-model/).

### Run several at once

Naming, ports, volumes and git identity are all designed for N containers on one
host without collision. Repeat step 5 with a different name and port; on the
laptop, add another `hosts.conf` stanza.

The complete surface — every flag, the image layering, the entrypoint, the
release pipeline — is in the [reference guide](site:guide/).
