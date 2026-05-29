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
# Debian 12's nvim package is too old. The release asset name changed across
# versions (nvim-linux64.tar.gz -> nvim-linux-x86_64.tar.gz); try both.
RUN set -eux; \
    cd /tmp; \
    BASE="https://github.com/neovim/neovim/releases/latest/download"; \
    if curl -fsSLO "${BASE}/nvim-linux-x86_64.tar.gz"; then \
        TARBALL="nvim-linux-x86_64.tar.gz"; \
        DIR="nvim-linux-x86_64"; \
    elif curl -fsSLO "${BASE}/nvim-linux64.tar.gz"; then \
        TARBALL="nvim-linux64.tar.gz"; \
        DIR="nvim-linux64"; \
    else \
        echo "neither nvim-linux-x86_64.tar.gz nor nvim-linux64.tar.gz could be downloaded" >&2; \
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
    } > /etc/ssh/sshd_config.d/10-devenv.conf \
    && mkdir -p /home/dev/.ssh \
    && chown dev:dev /home/dev/.ssh \
    && chmod 0700 /home/dev/.ssh

# --- Layer 6: entrypoint (most-frequently-changed; STUB until item C) -------
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

EXPOSE 22

USER dev
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
