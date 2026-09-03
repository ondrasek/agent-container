# syntax-compatible with both `docker build` and `podman build`.
# No BuildKit-specific features. See docs/decisions/0001-runtime-and-base-image.md.
#
# Layering rationale (cheapest-to-rebuild last):
#   1. apt base packages          — rarely changes; large; cached aggressively.
#   2. Node 22 LTS (NodeSource)   — rarely changes; medium.
#   3. Agent CLIs (npm globals)   — changes with agent releases.
#   4. Neovim upstream tarball    — changes with nvim releases.
#   5. User + sshd config         — cheap; placed late so earlier layers cache.
#   6. entrypoint.sh              — changes most often (item C); last.

FROM debian:12-slim

# Feature 013 FR-012a: the version of the CLI that built this image, so `doctor` can
# tell locally whether the image is older than the tool — no network, no registry
# round-trip. A LABEL rather than an ENV because reading it must not start a
# container.
#
# The default is EMPTY, deliberately. `build` omits the arg when it cannot resolve a
# version, and an empty label reads as "no stamp" — which FR-012b maps to *unknown*.
# Stamping a sentinel like 0.0.0+unknown would be worse: a meaningless value that
# looks like an answer.
ARG AGENT_CONTAINER_VERSION=
LABEL org.opencontainers.image.version="${AGENT_CONTAINER_VERSION}"

# Fail fast on any unhandled error inside RUN blocks.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC

# --- Layer 1: base OS packages ----------------------------------------------
# Single RUN so the apt cache cleanup lands in the same layer as the install.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        git \
        openssh-server \
        tmux \
        zsh \
        locales \
        less \
        jq \
        build-essential \
        python3 \
        python3-pip \
        python3-venv \
        python3-pytest \
        fd-find \
        ripgrep \
    && sed -i 's/^# *\(C.UTF-8\)/\1/' /etc/locale.gen || true \
    && locale-gen C.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# `python3-pytest` is baked for the same reason as everything else here: a real
# agent asked to "run the test suite" on a Python repository reaches for pytest,
# and without it the only way forward is `pip install` at runtime. Behind an
# egress boundary that is not a slow path, it is a REFUSED one — pypi.org is not
# a declared destination — so the agent burns its turns retrying a download and
# never reaches the work. Measured: the pull-request test failed with a wall of
# `pypi.org A IN REFUSED` and no pull request. The Debian package rather than pip
# because Debian 12 marks its Python externally-managed (PEP 668).
#
# `fd` is the name every agent looks for; Debian ships the binary as `fdfind`
# because of a name clash with an unrelated package. Without this link
# pi-coding-agent decides `fd` is missing and DOWNLOADS its own copy at runtime,
# into an ephemeral dir, on every boot — which contradicts "bake every system dep
# at build" (CLAUDE.md) and, behind an egress boundary, simply fails: the download
# is not a declared destination, so the agent runs degraded and says so only in
# its startup chatter. Observed in a real interactive session.
RUN ln -s /usr/bin/fdfind /usr/local/bin/fd

# --- Layer 2: Node 22 LTS via NodeSource ------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Layer 3: agent CLIs (global npm installs) ------------------------------
# pi-coding-agent needs --ignore-scripts (postinstall pulls native bits we
# don't want resolved at build time).
RUN npm i -g @anthropic-ai/claude-code \
    && npm i -g @openai/codex \
    && npm i -g --ignore-scripts @earendil-works/pi-coding-agent \
    && npm i -g opencode-ai \
    && npm cache clean --force

# --- Layer 3b: OTLP telemetry extensions for the agents that lack it ---------
# Claude Code and Codex export OpenTelemetry themselves — Claude Code from
# environment variables, Codex from `~/.codex/config.toml`. pi and opencode do
# NOT: each needs a third-party extension, so telemetry for them is a dependency
# decision rather than a configuration one.
#
# These are COMMUNITY packages, not first-party ones, and that is the trade being
# made: uniform telemetry across all four agents in exchange for two more npm
# publishers in the image's trust boundary. They are installed globally at BUILD
# time and merely REGISTERED at runtime, because the alternative — installing on
# first use — is a network fetch behind an egress boundary that does not declare
# npm, i.e. a silent no-op exactly when telemetry is expected to work.
RUN npm i -g @devtheops/opencode-plugin-otel \
    && npm i -g @desek/pi-opentelemetry \
    && npm cache clean --force

# --- Layer 4: Neovim from upstream stable tarball ---------------------------
# Debian 12's nvim package is too old. Upstream ships per-architecture tarballs;
# pick the one matching the build platform (amd64 -> x86_64 / linux64 legacy
# name; arm64 -> linux-arm64). The asset name for amd64 also changed across
# releases (nvim-linux64.tar.gz -> nvim-linux-x86_64.tar.gz); fall through.
RUN set -eux; \
    cd /tmp; \
    BASE="https://github.com/neovim/neovim/releases/latest/download"; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
        amd64) CANDIDATES="nvim-linux-x86_64.tar.gz nvim-linux64.tar.gz" ;; \
        arm64) CANDIDATES="nvim-linux-arm64.tar.gz" ;; \
        *) echo "unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac; \
    TARBALL=""; \
    for CAND in ${CANDIDATES}; do \
        if curl -fsSLO "${BASE}/${CAND}"; then TARBALL="${CAND}"; break; fi; \
    done; \
    if [ -z "${TARBALL}" ]; then \
        echo "no neovim release asset matched for arch=${ARCH} (tried: ${CANDIDATES})" >&2; \
        exit 1; \
    fi; \
    tar -C /usr/local -xzf "${TARBALL}" --strip-components=1; \
    rm -f "${TARBALL}"; \
    nvim --version | head -n1

# --- Layer 4b: yq (mikefarah) for YAML processing ---------------------------
# Standalone Go binary; not reliably packaged for Debian 12. Pull the release
# asset matching the build architecture (dpkg arch names match yq's suffixes).
RUN set -eux; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
        amd64|arm64) : ;; \
        *) echo "unsupported architecture for yq: ${ARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/yq \
        "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${ARCH}"; \
    chmod 0755 /usr/local/bin/yq; \
    yq --version

# --- Layer 4c: GitHub CLI ---------------------------------------------------
# An agent that can commit and push but cannot open a pull request stops one step
# short of a reviewable handover, and the REST API is a poor substitute: it means
# hand-assembling JSON with a token on the command line, which is exactly the
# shape this project keeps credentials OUT of. `gh` reads GH_TOKEN from the
# environment, which is already how the token reaches the container.
#
# Upstream tarball rather than GitHub's apt repo: one fewer signing key and
# sources.list entry in the image, and the same arch-aware idiom as nvim/yq
# above. Note the tarball's inner directory carries the version, so it is
# resolved with a glob rather than --strip-components on a guessed name.
RUN set -eux; \
    cd /tmp; \
    ARCH="$(dpkg --print-architecture)"; \
    case "${ARCH}" in \
        amd64|arm64) : ;; \
        *) echo "unsupported architecture for gh: ${ARCH}" >&2; exit 1 ;; \
    esac; \
    VER="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
        | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -n1)"; \
    test -n "${VER}"; \
    curl -fsSLO "https://github.com/cli/cli/releases/download/v${VER}/gh_${VER}_linux_${ARCH}.tar.gz"; \
    tar -xzf "gh_${VER}_linux_${ARCH}.tar.gz"; \
    install -m 0755 "gh_${VER}_linux_${ARCH}/bin/gh" /usr/local/bin/gh; \
    rm -rf "gh_${VER}_linux_${ARCH}" "gh_${VER}_linux_${ARCH}.tar.gz"; \
    gh --version | head -n1

# --- Layer 5: user + ROOTLESS sshd config -----------------------------------
# The container is fully rootless: no sudo, no root at runtime. All system deps
# are baked at build (agents never apt-install at runtime), so root buys nothing
# and is dropped. sshd runs as the 'dev' user on an unprivileged port.
RUN useradd --create-home --home-dir /home/dev --shell /bin/bash --uid 1000 dev \
    && mkdir -p /workspace \
    && chown dev:dev /workspace \
    && chmod 0755 /workspace

# sshd: dev-only, key-based, no root, no passwords — and started BY dev (rootless).
#   - Port 2222: unprivileged (<1024 needs root to bind); the host-side published
#     port is unchanged (the CLI maps <hostport>:2222).
#   - UsePAM no: PAM session setup needs root; pubkey-only single-user needs no PAM.
#   - HostKey in the dev-owned ~/.ssh/hostkeys volume so identity persists across
#     down/up and is generated/installed by the entrypoint (as dev, no root).
#   - PidFile under ~/.ssh (dev-writable; /run/sshd.pid would need root).
# /run/sshd is the privilege-separation dir; it must exist and be root-owned 0755
# (created here at build time, when we still are root). sshd running as dev reads
# it fine and does not need to write to it.
RUN mkdir -p /etc/ssh /run/sshd \
    && chmod 0755 /run/sshd \
    && rm -f /etc/ssh/ssh_host_* \
    && { \
        echo 'AllowUsers dev'; \
        echo 'PasswordAuthentication no'; \
        echo 'PermitRootLogin no'; \
        echo 'PubkeyAuthentication yes'; \
        echo 'Port 2222'; \
        echo 'UsePAM no'; \
        echo 'KbdInteractiveAuthentication no'; \
        echo 'PrintMotd no'; \
        echo 'AcceptEnv LANG LC_*'; \
        echo 'HostKey /home/dev/.ssh/hostkeys/ssh_host_ed25519_key'; \
        echo 'PidFile /home/dev/.ssh/sshd.pid'; \
    } > /etc/ssh/sshd_config.d/10-agent-container.conf \
    && mkdir -p /home/dev/.ssh/hostkeys \
    && chown -R dev:dev /home/dev/.ssh \
    && chmod 0700 /home/dev/.ssh /home/dev/.ssh/hostkeys

# --- Layer 5b: per-container volume mount points + persistent shell env -----
# Each of these dirs is the mount point of a per-container named volume
# (agent-container-<name>-{claude,codex,pi,opencode,opencode-data,shellenv,tmux} — shellenv mounts at ~/.agent-env). Pre-creating them dev-owned
# (uid 1000) BEFORE the USER switch means a fresh, empty named volume
# initializes dev-owned too — the runtime seeds a new volume from the image
# directory's contents AND ownership/permissions. Without this the volume
# would come up root-owned and the agents could not write their credentials.
#
# pi-coding-agent's config/auth dir is ~/.pi (verified: package.json piConfig
# .configDir = ".pi"; dist/config.js getAgentDir() -> ~/.pi/agent, auth.json
# at ~/.pi/agent/auth.json). Overridable at runtime via PI_CODING_AGENT_DIR.
#
# opencode is the one agent that SPLITS config from credentials (it follows XDG),
# so it gets TWO volumes (verified against opencode.ai/docs AND by running it):
#   ~/.config/opencode      -> opencode.jsonc (the file it CREATES; opencode.json
#                              is the documented name and is also read),
#                              agents/, commands/, skills/, themes/
#   ~/.local/share/opencode -> auth.json (from `opencode auth login`) + opencode.db
# Deliberately NOT persisted: ~/.local/state/opencode/locks (a stale lock carried
# across a recreate is a self-inflicted failure) and ~/.cache/opencode (regenerated).
# NOTE ~/.local is chowned RECURSIVELY below: `mkdir -p .../.local/share/opencode`
# also creates ~/.local and ~/.local/share, and chowning only the leaf leaves both
# root-owned. Verified: without this, dev cannot write EITHER mount point — not even
# ~/.config/opencode, whose parent is already dev-owned (a new mount point does not
# inherit the parent's ownership).
# The credential dirs are 0700; .agent-env (shell env) and .config/tmux (tmux.conf
# + tpm plugins) are non-secret and 0755. ~/.config/tmux is XDG-standard: tmux
# 3.x on debian:12 reads ~/.config/tmux/tmux.conf, so persisting that dir on its
# own named volume carries the operator's tmux.conf/plugins across down/up.
#
# Shell-env wiring: agents and the operator drop KEY=VALUE exports in
# ~/.agent-env/env (on the shellenv volume, so it survives down/up). BOTH bash and
# zsh source it, guarded so a malformed file cannot break the shell. dev's
# LOGIN SHELL stays bash (sshd/tmux/entrypoint assume bash); zsh is available
# but not the default.
#
# The hook lives in ~/.bashrc (read by interactive shells). Login shells — SSH
# login sessions AND tmux panes (tmux spawns the default shell as a LOGIN shell
# when no default-command is set) — read ~/.bash_profile, not ~/.bashrc, so
# ~/.bash_profile must chain to ~/.bashrc. We source Debian's stock ~/.profile
# to do that: it sources ~/.bashrc under bash (firing the hook) AND restores the
# ~/.local/bin + ~/bin PATH additions that ~/.bash_profile would otherwise shadow
# (e.g. for `pip install --user` tools). This bash_profile->profile->bashrc chain
# is load-bearing for login-shell panes; do not "simplify" it away.
RUN set -eux; \
    mkdir -p /home/dev/.claude /home/dev/.codex /home/dev/.pi /home/dev/.agent-env /home/dev/.config/tmux /home/dev/.config/opencode /home/dev/.local/share/opencode; \
    chown -R dev:dev /home/dev/.claude /home/dev/.codex /home/dev/.pi /home/dev/.agent-env /home/dev/.config /home/dev/.local; \
    chmod 0700 /home/dev/.claude /home/dev/.codex /home/dev/.pi /home/dev/.config/opencode /home/dev/.local/share/opencode; \
    chmod 0755 /home/dev/.agent-env /home/dev/.config/tmux; \
    HOOK='if [ -f "$HOME/.agent-env/env" ]; then set -a; . "$HOME/.agent-env/env"; set +a; fi'; \
    printf '\n# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.bashrc; \
    printf '# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.zshrc; \
    printf '# agent-container: login shells load ~/.profile (sources ~/.bashrc + adds ~/.local/bin to PATH)\n[ -f "$HOME/.profile" ] && . "$HOME/.profile"\n' >> /home/dev/.bash_profile; \
    chown dev:dev /home/dev/.bashrc /home/dev/.zshrc /home/dev/.bash_profile

# --- Layer 5c: run-record volume mount point (Feature 016) ------------------
# Mount point of the TENTH per-container volume (agent-container-<name>-runs):
# the pending run record the entrypoint writes and the CLI later ingests.
#
# Created HERE for the reason stated above and enforced by the runtime: a named
# volume whose mount point does not exist in the image is created root:root, and
# a rootless container cannot write it — not even under a dev-owned parent. The
# record would then be missing for exactly the detached runs this volume exists
# to account for, and nothing would say so.
#
# Deliberately NOT under /home/dev. The shell-env and agent config dirs are
# writable by anything the operator or the agent runs in the container; the
# account of a run must not live where the subject of the account can edit it
# (research R2). 0700 because the task text is the one record field that can
# carry a credential (data-model §5).
RUN set -eux; \
    mkdir -p /var/lib/agent-container/runs; \
    chown -R dev:dev /var/lib/agent-container; \
    chmod 0755 /var/lib/agent-container; \
    chmod 0700 /var/lib/agent-container/runs

# --- Layer 6: entrypoint (most-frequently-changed; STUB until item C) -------
# Two-step COPY+chmod instead of `COPY --chmod=` so the file builds under both
# the legacy builder and BuildKit; --chmod requires BuildKit specifically.
# Constitution IX: secrets are DELIVERED to the running container, and the container
# decides where they land. Root-owned 0755 so the agent (dev) cannot rewrite the
# receiver, and a dev-owned 0700 directory for it to write into — under /run, so it
# dies with the container and is never a volume (FR-012), and PRIVATE rather than the
# shared world-writable /dev/shm.
COPY receive-secret.sh /usr/local/bin/agent-container-receive-secret
RUN chmod 0755 /usr/local/bin/agent-container-receive-secret; \
    mkdir -p /run/agent-container-secrets; \
    chown dev:dev /run/agent-container-secrets; \
    chmod 0700 /run/agent-container-secrets

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 2222

USER dev
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
