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
        sudo \
        locales \
        less \
        jq \
        build-essential \
        python3 \
        python3-pip \
        python3-venv \
    && sed -i 's/^# *\(C.UTF-8\)/\1/' /etc/locale.gen || true \
    && locale-gen C.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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

# --- Layer 5: user + sudo + sshd config -------------------------------------
RUN useradd --create-home --home-dir /home/dev --shell /bin/bash --uid 1000 dev \
    && echo 'dev ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/90-dev \
    && chmod 0440 /etc/sudoers.d/90-dev \
    && mkdir -p /workspace \
    && chown dev:dev /workspace \
    && chmod 0755 /workspace

# sshd: dev-only, key-based, no root, no passwords.
# Host keys are deliberately NOT generated here — entrypoint does it at first
# launch so every container instance gets a distinct identity.
RUN mkdir -p /etc/ssh \
    && rm -f /etc/ssh/ssh_host_* \
    && { \
        echo 'AllowUsers dev'; \
        echo 'PasswordAuthentication no'; \
        echo 'PermitRootLogin no'; \
        echo 'PubkeyAuthentication yes'; \
        echo 'Port 22'; \
        echo 'UsePAM yes'; \
        echo 'ChallengeResponseAuthentication no'; \
        echo 'PrintMotd no'; \
        echo 'AcceptEnv LANG LC_*'; \
    } > /etc/ssh/sshd_config.d/10-agent-container.conf \
    && mkdir -p /home/dev/.ssh \
    && chown dev:dev /home/dev/.ssh \
    && chmod 0700 /home/dev/.ssh

# --- Layer 5b: per-container volume mount points + persistent shell env -----
# Each of these dirs is the mount point of a per-container named volume
# (agent-container-<name>-{claude,codex,pi,shellenv,tmux}). Pre-creating them dev-owned
# (uid 1000) BEFORE the USER switch means a fresh, empty named volume
# initializes dev-owned too — the runtime seeds a new volume from the image
# directory's contents AND ownership/permissions. Without this the volume
# would come up root-owned and the agents could not write their credentials.
#
# pi-coding-agent's config/auth dir is ~/.pi (verified: package.json piConfig
# .configDir = ".pi"; dist/config.js getAgentDir() -> ~/.pi/agent, auth.json
# at ~/.pi/agent/auth.json). Overridable at runtime via PI_CODING_AGENT_DIR.
# The credential dirs are 0700; .agent-container (shell env) and .config/tmux (tmux.conf
# + tpm plugins) are non-secret and 0755. ~/.config/tmux is XDG-standard: tmux
# 3.x on debian:12 reads ~/.config/tmux/tmux.conf, so persisting that dir on its
# own named volume carries the operator's tmux.conf/plugins across down/up.
#
# Shell-env wiring: agents and the operator drop KEY=VALUE exports in
# ~/.agent-container/env (on the shellenv volume, so it survives down/up). BOTH bash and
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
    mkdir -p /home/dev/.claude /home/dev/.codex /home/dev/.pi /home/dev/.agent-container /home/dev/.config/tmux; \
    chown -R dev:dev /home/dev/.claude /home/dev/.codex /home/dev/.pi /home/dev/.agent-container /home/dev/.config; \
    chmod 0700 /home/dev/.claude /home/dev/.codex /home/dev/.pi; \
    chmod 0755 /home/dev/.agent-container /home/dev/.config/tmux; \
    HOOK='if [ -f "$HOME/.agent-container/env" ]; then set -a; . "$HOME/.agent-container/env"; set +a; fi'; \
    printf '\n# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.bashrc; \
    printf '# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.zshrc; \
    printf '# agent-container: login shells load ~/.profile (sources ~/.bashrc + adds ~/.local/bin to PATH)\n[ -f "$HOME/.profile" ] && . "$HOME/.profile"\n' >> /home/dev/.bash_profile; \
    chown dev:dev /home/dev/.bashrc /home/dev/.zshrc /home/dev/.bash_profile

# --- Layer 6: entrypoint (most-frequently-changed; STUB until item C) -------
# Two-step COPY+chmod instead of `COPY --chmod=` so the file builds under both
# the legacy builder and BuildKit; --chmod requires BuildKit specifically.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 22

USER dev
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
