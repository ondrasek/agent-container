# The CONTROL-PLANE image (Feature 017). Syntax-compatible with both
# `docker build` and `podman build`; no BuildKit-specific features. See
# docs/decisions/0001-runtime-and-base-image.md.
#
# WHY THIS IS A SECOND IMAGE rather than a build arg on image/Dockerfile:
# FR-015a wants "no agents are installed here" to be a PROPERTY of the artifact.
# A shared Dockerfile with a conditional install is a property you have to read
# the build args to know — and this is the one container worth stealing, because
# its key spans a sandbox shell and machine-level daemon access. The narrowness
# has to be readable without reconstructing a build invocation.
#
# What is deliberately ABSENT: Node, npm, and every agent CLI. There is no
# `npm i -g` line in this file, and the agent census in
# bin/tests/test_pure_logic.py declares that expectation as "none" and enforces
# it. The census is parameterised over every Dockerfile in the tree and FAILS on
# one it has no expectation for — so a third image cannot be added unnoticed
# (research R2).
#
# Layering rationale (cheapest-to-rebuild last):
#   1. apt base packages   — rarely changes; large; cached aggressively.
#   2. the agent-container CLI from PyPI — changes per release.
#   3. user + sshd config  — cheap; placed late so earlier layers cache.
#   4. entrypoint.sh       — changes most often; last.

# BASE IMAGE DEVIATION FROM ADR 0001, and it is forced rather than chosen.
#
# ADR 0001 pins `debian:12-slim`. This image INSTALLS the agent-container
# distribution from PyPI, and that distribution declares `requires-python >=
# 3.14`. Debian 12 ships Python 3.11, so `pip install agent_container` there
# resolves to 0.1.0 — the last release published before the floor was raised —
# and every later version is skipped with "Requires-Python >=3.14". A build that
# "succeeded" would have shipped a CLI several dozen releases old while the image
# label claimed the current version, which is precisely the label-vs-installed
# disagreement FR-016 would then compare.
#
# Found by RUNNING the acceptance tier, not by reading: the pin is correct, the
# guard is correct, and pip's own resolution is what refuses.
#
# `python:3.14-slim` is Debian 13 (trixie) with Python 3.14, so the apt userland
# below is unchanged and ADR 0001's actual intent holds: Debian-based, no
# Docker-Desktop-only features, Podman-compatible. The agent image keeps
# `debian:12-slim` — it carries no Python of ours and has no reason to move.
FROM python:3.14-slim

# Feature 013 FR-012a, and Feature 017 FR-016. The version of the CLI that built
# this image, so `doctor` can tell locally whether the image is older than the
# tool — no network, no registry round-trip. A LABEL rather than an ENV because
# reading it must not start a container.
#
# The default is EMPTY, deliberately: `build` omits the arg when it cannot
# resolve a version, and an empty label reads as "no stamp", which FR-012b maps
# to *unknown*. Stamping a sentinel like 0.0.0+unknown would be worse — a
# meaningless value that looks like an answer.
#
# This is the SAME arg and the SAME label as the agent image, so `doctor` and
# FR-016's semver rule read ONE version source rather than two (research R1).
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
#
# `curl` is here for the same reason it is in the agent image, and it is now
# load-bearing rather than incidental: OTLP export is a `curl` POST of a JSON
# document from the entrypoint (research R5), which is what lets this feature add
# ZERO Python packages and zero image additions for telemetry.
#
# `openssh-client` (not only -server) because a control plane's whole job is
# reaching other hosts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        openssh-server \
        openssh-client \
        tmux \
        zsh \
        locales \
        less \
        jq \
    && sed -i 's/^# *\(C.UTF-8\)/\1/' /etc/locale.gen || true \
    && locale-gen C.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Layer 2: the agent-container CLI, from PyPI at a PINNED version ---------
# FR-002 is a BUILD, not configuration: the CLI is in no image today.
#
# Installed from PyPI rather than from the checkout because the build context IS
# this directory by construction (Feature 011), so the checkout is not reachable
# from here — and widening the context to grab it would undo a deliberate
# narrowness that exists because the context crosses the network to a possibly
# remote daemon (research R1).
#
# PINNED, and the pin is an ARG so `build` passes the version it resolved for the
# label. Same value, one source: an image whose label and whose installed CLI
# disagreed would make FR-016's semver comparison lie.
#
# No --break-system-packages: the `python:` images do not mark their interpreter
# externally managed (PEP 668), so passing it would suppress a real error if this
# base ever changed. This is a single-purpose image whose only Python consumer IS
# this tool, so installing into the system interpreter is the right home — a venv
# would put the console script somewhere nothing else in the image looks.
#
# NO DEFAULT, AND THE BUILD FAILS WITHOUT IT. A default version is a pin that
# goes stale on every release: the first version of this file defaulted to
# 0.31.0, and 0.32.0 shipped the same day. An unstamped build would then have
# installed a CLI older than the tree it was built from, while the image carried
# no label to say so — the label and the installed CLI are the two things FR-016
# compares, and a silent default makes them disagree.
#
# `build` refuses to produce this image when it cannot resolve a version, so the
# failure below is reachable only from a bare `docker build`, where naming the
# requirement is exactly right.
ARG AGENT_CONTAINER_PYPI_VERSION=
RUN set -eux; \
    if [ -z "${AGENT_CONTAINER_PYPI_VERSION}" ]; then \
        echo "AGENT_CONTAINER_PYPI_VERSION is required: this image pins the CLI it installs," >&2; \
        echo "and a default would install a version nobody chose. Use 'agent-container build'," >&2; \
        echo "or pass --build-arg AGENT_CONTAINER_PYPI_VERSION=<version>." >&2; \
        exit 1; \
    fi; \
    python3 -m pip install --no-cache-dir \
        "agent_container==${AGENT_CONTAINER_PYPI_VERSION}"; \
    agent-container --help > /dev/null; \
    command -v agent-container

# --- Layer 2b: BOTH container runtime CLIENTS ----------------------------------
# WITHOUT THESE THE CONTROL PLANE CANNOT MANAGE ANYTHING, and the failure is not
# subtle: `detect_runtime()` dies with "neither 'podman' nor 'docker' on PATH",
# so every management command refuses. The first version of this image omitted
# them and the acceptance test that SSHes in and runs `list` is what found it —
# no amount of reading the Dockerfile would have, because nothing in it looks
# missing.
#
# BOTH, and the reason is that the tool's DEFAULT runtime is podman.
# ADR 0001 chooses Podman; `detect_runtime()` prefers podman on Linux (the VPS);
# the README's VPS setup installs Podman; and `driver_runtime_argv` invokes
# `podman --connection <name>` for a host registered `driver: podman`. An image
# with only `docker-cli` can therefore manage the NON-DEFAULT configuration and
# nothing else — every command against a podman host dies on a missing binary.
#
# The second version of this file installed docker-cli alone and asserted, in a
# comment, that "the hosts it manages are reached through docker contexts". The
# project's own ADR contradicts that. The acceptance tier did not catch it either,
# because every test registers a docker host or the implicit local docker daemon —
# so the gap is invisible unless a podman host exists.
#
# CLIENTS ONLY. No daemon, no dockerd, no `podman machine`: this container talks
# to a REMOTE engine over the operator's contexts and connections (Feature 002),
# and a daemon here would need privileges the whole design refuses
# (Constitution II). `docker-cli` and `podman-remote` are the client binaries
# alone — `podman-remote` specifically, NOT `podman`, which would pull the local
# engine this container must not have.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli podman-remote \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && docker --version \
    && podman-remote --version \
    && ln -s "$(command -v podman-remote)" /usr/local/bin/podman \
    && podman --version

# --- Layer 3: user + ROOTLESS sshd config -----------------------------------
# Identical posture to the agent image, and deliberately so: a control plane is
# an ordinary environment (Constitution IV) with the same naming, ports and
# volumes. No sudo, no root at runtime; sshd runs as `dev` on unprivileged 2222.
RUN useradd --create-home --home-dir /home/dev --shell /bin/bash --uid 1000 dev \
    && mkdir -p /workspace \
    && chown dev:dev /workspace \
    && chmod 0755 /workspace

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

# --- Layer 3b: volume mount points ------------------------------------------
# A control plane is an ordinary environment, so the CLI mounts it the SAME
# volume set. Every mount point must exist here, dev-owned, BEFORE the USER
# switch: the runtime seeds a fresh named volume from the image directory's
# contents AND its ownership, so a mount point missing from the image is created
# root:root and a rootless container cannot write it.
#
# The agent-credential dirs are created even though NO agent is installed. That
# looks redundant and is not: the volume set is decided by the CLI, and a mount
# point absent here fails at runtime as an unwritable directory rather than at
# build time as a missing agent. Creating them costs four empty directories;
# omitting them makes the failure late, rootless-specific and confusing.
#
# /home/dev/.ssh is the volume that carries this container's PASSPHRASE-ENCRYPTED
# keypair across recreate (data-model §2). That persistence is deliberate and
# against Constitution I's grain: the keypair is IDENTITY, not work, and
# regenerating it per boot would invalidate every authorisation the operator
# made. `--purge` is therefore the revocation boundary.
RUN set -eux; \
    mkdir -p /home/dev/.claude /home/dev/.codex /home/dev/.pi \
             /home/dev/.agent-env /home/dev/.config/tmux \
             /home/dev/.config/opencode /home/dev/.local/share/opencode; \
    chown -R dev:dev /home/dev/.claude /home/dev/.codex /home/dev/.pi \
             /home/dev/.agent-env /home/dev/.config /home/dev/.local; \
    chmod 0700 /home/dev/.claude /home/dev/.codex /home/dev/.pi \
             /home/dev/.config/opencode /home/dev/.local/share/opencode; \
    chmod 0755 /home/dev/.agent-env /home/dev/.config/tmux; \
    HOOK='if [ -f "$HOME/.agent-env/env" ]; then set -a; . "$HOME/.agent-env/env"; set +a; fi'; \
    printf '\n# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.bashrc; \
    printf '# agent-container: source persistent shell env if present (guarded)\n%s\n' "$HOOK" >> /home/dev/.zshrc; \
    printf '# agent-container: login shells load ~/.profile (sources ~/.bashrc + adds ~/.local/bin to PATH)\n[ -f "$HOME/.profile" ] && . "$HOME/.profile"\n' >> /home/dev/.bash_profile; \
    chown dev:dev /home/dev/.bashrc /home/dev/.zshrc /home/dev/.bash_profile

# --- Layer 3c: run-record volume mount point (Feature 016) ------------------
# Same reasoning as the agent image, and it applies here too: a control plane
# performs management actions, and FR-009a requires those to be recorded. 0700,
# and NOT under /home/dev — the account of an action must not live where the
# subject of the account can edit it.
RUN set -eux; \
    mkdir -p /var/lib/agent-container/runs; \
    chown -R dev:dev /var/lib/agent-container; \
    chmod 0755 /var/lib/agent-container; \
    chmod 0700 /var/lib/agent-container/runs

# --- Layer 4: entrypoint (most-frequently-changed; last) --------------------
# Its own copy, because the build context is this directory alone. The shared
# regions are marked with SHARED-BLOCK sentinels and a drift guard in
# bin/tests/test_pure_logic.py asserts they are IDENTICAL to image/entrypoint.sh
# — two copies of shell that agree today drift the moment one is edited, and the
# drift would be invisible because each image still works on its own.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 2222

USER dev
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
