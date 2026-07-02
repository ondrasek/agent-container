#!/usr/bin/env bash
# entrypoint.sh — container PID 1 for the remote-persistent-devenv image.
#
# Responsibilities (in order):
#   1. Validate required env vars (fail fast, never log their values).
#   2. Generate SSH host keys on first run (so each container has a distinct identity).
#   3. Configure git identity + HTTPS credential helper for the dev user.
#   4. Start sshd in the background.
#   5. Start a detached tmux session named 'main' for the dev user.
#   6. Stay alive as PID 1, forwarding SIGTERM/SIGINT to a clean shutdown.
#
# Runs as the non-root 'dev' user. Privileged actions go through passwordless sudo
# (configured in the Dockerfile). NEVER echoes env-var contents to logs.
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
# /home/dev/.devenv lives on the per-container 'shellenv' named volume and is
# sourced into every interactive bash/zsh shell (see Dockerfile). On first boot
# the volume is empty, so drop a commented template explaining its purpose.
# Idempotent: never overwrite an existing file, and never echo its contents.
DEVENV_ENV_FILE="/home/dev/.devenv/env"
if [[ ! -f "${DEVENV_ENV_FILE}" ]]; then
    log "seeding persistent shell-env template at ${DEVENV_ENV_FILE}"
    mkdir -p /home/dev/.devenv
    cat > "${DEVENV_ENV_FILE}" <<'EOF'
# ~/.devenv/env — persistent shell environment for this devenv container.
#
# This file lives on the per-container 'shellenv' named volume, so it survives
# `devenv down` / `devenv up` and crashes (it is dropped only by `down --purge`).
# It is sourced with `set -a` into every interactive bash and zsh shell,
# including tmux panes. Keep it to simple KEY=VALUE / export lines.
#
# Example:
#   export FOO=bar
EOF
else
    log "persistent shell-env file already present, leaving it alone"
fi

# --- 2. SSH host keys -------------------------------------------------------
# Idempotent: only regenerate if the ed25519 key is absent. ssh-keygen -A
# creates whichever key types are missing under /etc/ssh/.
if [[ ! -f /etc/ssh/ssh_host_ed25519_key ]]; then
    log "Generating SSH host keys..."
    sudo ssh-keygen -A
else
    log "SSH host keys already present, skipping generation"
fi

# sshd's privilege-separation directory. Idempotent.
sudo mkdir -p /run/sshd
sudo chmod 0755 /run/sshd

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
git config --global credential.helper \
    '!f() { echo "username=x-access-token"; echo "password=${GH_TOKEN}"; }; f'

log "Configured git identity for ${GIT_USER_NAME}"

# --- 4. sshd ----------------------------------------------------------------
# Daemonize (no -D) so the entrypoint can continue to start tmux and tail.
# sshd's own logs go to stderr / syslog per the image's sshd_config.
sudo /usr/sbin/sshd
log "sshd listening"

# --- 5. tmux session --------------------------------------------------------
# Detached session named 'main'. On first creation, build a configurable set of
# windows from DEVENV_TMUX_WINDOWS (space-separated names). Default when unset:
# "shell edit agents". Opt-out: setting DEVENV_TMUX_WINDOWS to an EMPTY string
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
    tmux_windows="${DEVENV_TMUX_WINDOWS-shell edit agents}"
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
    # sshd was started via sudo and runs as root; kill it the same way.
    sudo pkill -TERM -x sshd 2>/dev/null || true
    exit 0
}

trap shutdown TERM INT

tail -f /dev/null &
TAIL_PID=$!
wait "${TAIL_PID}"
