#!/usr/bin/env bash
# entrypoint.sh — container PID 1 for the CONTROL-PLANE image (Feature 017).
#
# This is a DIFFERENT PROGRAM from image/entrypoint.sh, not a copy of it. There
# is no agent here: no model credentials, no canonical agent config, no headless
# dispatch, no clone-on-start. Duplicating 1300 lines of agent machinery to reach
# the ~200 lines this container needs would create drift in every one of those
# lines. What DOES have to agree between the two images is marked with
# SHARED-BLOCK sentinels below, and a drift guard in bin/tests/test_pure_logic.py
# asserts those regions are byte-identical.
#
# Responsibilities (in order):
#   1. Validate required env vars (fail fast, never log their values).
#   2. Install/persist/generate the SSH host key + assemble authorized_keys.
#   3. Configure git identity.
#   3b. Generate THIS CONTROL PLANE'S OWN keypair — PASSPHRASE-PROTECTED.
#   4. Start sshd in the background.
#   5. Start a detached tmux session named 'main'.
#   6. Stay alive as PID 1, forwarding SIGTERM/SIGINT to a clean shutdown.
#
# Runs as the non-root 'dev' user with NO root/sudo (fully rootless container).
# NEVER echoes env-var contents to logs — and, in this image, never echoes the
# key passphrase anywhere at all (see §3b).

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
if [[ $# -gt 0 ]]; then
    exec "$@"
fi

# --- 1. Validate env vars ---------------------------------------------------
# Presence by name only; values are never printed or traced.
require_env() {
    local name=$1
    if [[ -z "${!name:-}" ]]; then
        die "required environment variable ${name} is unset or empty"
    fi
}

require_env GIT_USER_NAME
require_env GIT_USER_EMAIL

AGENT_CONTAINER_HOME="${AGENT_CONTAINER_HOME:-/home/dev}"
INJECT_DIR="${AGENT_CONTAINER_INJECT_DIR:-/run/agent-container}"

# --- 2. SSH host key (rootless: dev-owned, on the persisted ~/.ssh volume) ---
# Identical posture and identical reasoning to the agent image: the host key is
# created HERE and NEVER LEAVES (Feature 018), only the public half is captured
# and pinned by the tool.
SSH_DIR="${AGENT_CONTAINER_HOME}/.ssh"
HOSTKEY_DIR="${SSH_DIR}/hostkeys"
HOSTKEY="${HOSTKEY_DIR}/ssh_host_ed25519_key"
mkdir -p "${HOSTKEY_DIR}"
chmod 0700 "${SSH_DIR}" "${HOSTKEY_DIR}"

if [[ ! -f "${HOSTKEY}" ]]; then
    log "generating SSH host key (ed25519) at ${HOSTKEY}"
    ssh-keygen -q -t ed25519 -f "${HOSTKEY}" -N ''
else
    log "SSH host key already present, skipping generation"
fi
if ! ssh-keygen -y -f "${HOSTKEY}" > "${HOSTKEY}.pub" 2>/dev/null; then
    die "SSH host key at ${HOSTKEY} is missing or invalid"
fi
chmod 0600 "${HOSTKEY}"
chmod 0644 "${HOSTKEY}.pub"

# --- 2b. authorized_keys: a tool-managed REGION, replaced every boot ---------
# NOT a union with the persisted file, which is what this used to be: a union
# retains every key ever granted, so removal could never revoke (020, FR-006).
# SHARED-BLOCK BEGIN authorized_keys (drift-guarded; see test_pure_logic)
AUTHKEYS="${SSH_DIR}/authorized_keys"
# This region is REPLACED on every boot. `~/.ssh/config`'s identically-styled
# block is WRITE-ONCE (an agent's own settings must survive) — same idiom,
# OPPOSITE update rule, so both sites say which they are. A region that is never
# rewritten cannot revoke; a block that is rewritten would discard agent settings.
# DETECTED by stable prefix, WRITTEN with the hint. The hint invites editing, so
# if detection required the whole decorated line an operator who reworded it would
# ORPHAN the region: its keys would become outside-content — permanent and
# unrevocable — while a fresh region was appended below. FR-006 failing silently.
AK_BEGIN_ID="# BEGIN agent-container managed keys"
AK_END_ID="# END agent-container managed keys"
AK_BEGIN="${AK_BEGIN_ID} — replaced on every boot; edit outside this region"
AK_END="${AK_END_ID}"
# What the TOOL grants THIS boot. Deliberately NOT unioned with the persisted
# file: a union retains every key ever injected, so removing a key from the
# source could never withdraw access (Feature 020, FR-006). SSH_AUTHORIZED_KEYS
# is supplied per boot, so it belongs INSIDE the region, not outside it.
_akr="$(mktemp)"
[[ -f "${INJECT_DIR}/authorized_keys" ]] && cat "${INJECT_DIR}/authorized_keys" >> "${_akr}"
[[ -n "${SSH_AUTHORIZED_KEYS:-}" ]] && printf '%s\n' "${SSH_AUTHORIZED_KEYS}" >> "${_akr}"
_akb=0
_ake=0
if [[ -f "${AUTHKEYS}" ]]; then
    _akb="$(awk -v b="${AK_BEGIN_ID}" 'index($0, b) == 1 { n++ } END { print n + 0 }' "${AUTHKEYS}")"
    _ake="$(awk -v e="${AK_END_ID}" 'index($0, e) == 1 { n++ } END { print n + 0 }' "${AUTHKEYS}")"
fi
# REFUSE rather than repair: a lone or repeated sentinel means the region's extent
# is unknown, and guessing a boundary risks deleting keys the operator added.
if [[ "${_akb}" != "${_ake}" ]] || [[ "${_akb}" -gt 1 ]]; then
    rm -f "${_akr}"
    die "authorized_keys has a malformed managed region (${_akb} begin, ${_ake} end marker(s)); refusing to rewrite it. Edit ${AUTHKEYS} so the markers form exactly one pair, or delete both marker lines."
fi
if [[ -s "${_akr}" ]] || [[ -f "${AUTHKEYS}" ]]; then
    # Content outside the region is NOT the tool's to remove (FR-016).
    _ako="$(mktemp)"
    if [[ -f "${AUTHKEYS}" ]]; then
        awk -v b="${AK_BEGIN_ID}" -v e="${AK_END_ID}" \
            'index($0, b) == 1 { inside = 1; next } index($0, e) == 1 { inside = 0; next } !inside { print }' \
            "${AUTHKEYS}" > "${_ako}"
    fi
    # A key the operator keeps OUTSIDE the region wins: we drop OUR duplicate, not
    # their line, so a recreate still withdraws what the tool granted while their
    # line survives. Dropping theirs would leave the key authorised after removal
    # and fail FR-006 silently.
    _akf="$(mktemp)"
    {
        cat "${_ako}"
        printf '%s\n' "${AK_BEGIN}"
        # FILENAME, not the usual NR == FNR: that idiom INVERTS when the first
        # file is empty (NR and FNR both restart), and an empty _ako is exactly
        # the fresh-deploy case — every granted key would be classified as
        # already-present and dropped, authorising nobody on first boot.
        awk -v ako="${_ako}" 'FILENAME == ako { if (NF) outside[$0] = 1; next }
             NF && !($0 in outside) && !seen[$0]++ { print }' "${_ako}" "${_akr}"
        printf '%s\n' "${AK_END}"
    } > "${_akf}"
    mv "${_akf}" "${AUTHKEYS}"
    chmod 0600 "${AUTHKEYS}"
    log "authorized_keys managed region rewritten ($(awk 'NF && $0 !~ /^#/' "${AUTHKEYS}" | wc -l | tr -d ' ') key(s) authorized)"
    rm -f "${_ako}"
fi
rm -f "${_akr}"
# SHARED-BLOCK END authorized_keys

# --- 3. Git identity --------------------------------------------------------
# Identity is non-secret. No credential helper is configured here: this
# container manages containers, it does not push code. A GH_TOKEN helper would
# be a credential this image has no use for.
git config --global user.name "${GIT_USER_NAME}"
git config --global user.email "${GIT_USER_EMAIL}"
git config --global init.defaultBranch main
git config --global pull.rebase false
log "Configured git identity for ${GIT_USER_NAME}"

# --- 3b. THE CONTROL PLANE'S OWN KEYPAIR — PASSPHRASE-PROTECTED -------------
# FR-007, contract C3, research R3. This is the one keypair in the whole tool
# that is encrypted at rest, and the reason is that it is the one worth stealing:
# it authorises a shell in a sandbox AND machine-level daemon access, so whoever
# holds this volume and the passphrase holds both.
#
# `-N "${passphrase}"` rather than the agent image's `-N ''`. That single
# difference is the feature: an unencrypted key on this volume means possessing
# the volume is possessing the fleet.
#
# THE PASSPHRASE IS GENERATED HERE AND WRITTEN NOWHERE.
# It goes to exactly one place: standard output, once, on the boot that creates
# the key, for the tool to relay to the operator's password manager. It is not
# logged (log() writes stderr and we deliberately do not use it), not stored,
# not exported, and not recoverable. FR-017: losing it means redeploying with a
# fresh keypair and withdrawing the old public half via `revoke`.
#
# `head -c 32 /dev/urandom | base64` rather than $RANDOM: bash's $RANDOM is a
# 15-bit LCG seeded from the pid and time, which is guessable by anyone who
# knows roughly when the container started — and they do, because it is in the
# container metadata.
CONTROL_PLANE_KEY="${SSH_DIR}/id_ed25519"
if [[ ! -f "${CONTROL_PLANE_KEY}" ]]; then
    # Local to this block. Never assigned to anything that outlives it, and the
    # only consumers are ssh-keygen's argument and the single print below.
    _cp_passphrase="$(head -c 32 /dev/urandom | base64 | tr -d '\n=' | cut -c1-40)"
    if [[ -z "${_cp_passphrase}" ]]; then
        die "could not generate a key passphrase — refusing to create an unencrypted control-plane key"
    fi
    log "generating the control-plane SSH key (ed25519, passphrase-encrypted) at ${CONTROL_PLANE_KEY}"
    if ! ssh-keygen -q -t ed25519 -f "${CONTROL_PLANE_KEY}" -N "${_cp_passphrase}" 2>/dev/null; then
        die "could not generate the control-plane SSH key at ${CONTROL_PLANE_KEY}"
    fi
    # The ONE crossing. A sentinel-delimited line on stdout, read once by the
    # tool and relayed to the operator. The sentinels exist so the tool can
    # extract exactly this and nothing adjacent; a looser parse could scrape a
    # neighbouring log line into a password manager.
    printf '%s\n' "AGENT_CONTAINER_CONTROL_PLANE_PASSPHRASE_BEGIN"
    printf '%s\n' "${_cp_passphrase}"
    printf '%s\n' "AGENT_CONTAINER_CONTROL_PLANE_PASSPHRASE_END"
    unset _cp_passphrase
else
    log "control-plane SSH key already present, keeping it (authorisations stay valid)"
fi
# Deriving the public half from an ENCRYPTED key would prompt for the
# passphrase, which there is nobody to answer at boot. So the .pub written by
# ssh-keygen at creation is the one that persists, and its absence is a real
# error rather than something to paper over by prompting.
if [[ ! -f "${CONTROL_PLANE_KEY}.pub" ]]; then
    die "the control-plane public key is missing at ${CONTROL_PLANE_KEY}.pub — the private half cannot be read without the passphrase, so redeploy to mint a fresh pair"
fi
chmod 0600 "${CONTROL_PLANE_KEY}"
chmod 0644 "${CONTROL_PLANE_KEY}.pub"

# FR-007a: the key is LOCKED whenever no operator is attached. No ssh-agent is
# started here and none is started at boot; the passphrase is supplied per
# session, on connect. Starting an agent here would unlock the key for the
# container's lifetime, which is precisely the property being refused — and
# nothing would look wrong.
if [[ -n "${SSH_AUTH_SOCK:-}" ]]; then
    log "WARNING: SSH_AUTH_SOCK is set at boot; the control-plane key must stay locked until an operator attaches"
fi

# known_hosts at the conventional path, so nothing has to be wired.
if [[ -f "${INJECT_DIR}/known_hosts" ]]; then
    cat "${INJECT_DIR}/known_hosts" >> "${SSH_DIR}/known_hosts"
fi
[[ -f "${SSH_DIR}/known_hosts" ]] || : > "${SSH_DIR}/known_hosts"
chmod 0644 "${SSH_DIR}/known_hosts"

# The tool's ssh_config block — APPENDED IF THE BLOCK IS ABSENT, never
# rewritten. Write-once applies to the BLOCK, not the file.
#
# StrictHostKeyChecking is `yes`, NOT `accept-new` as in the agent image. The
# difference is deliberate: this container reaches the operator's own hosts,
# whose keys the tool pins at deploy time (Feature 018), so a first-contact
# acceptance here would accept an unpinned host silently — from the one
# container whose reach is the whole fleet.
SSH_CONFIG="${SSH_DIR}/config"
if ! grep -q '^# BEGIN agent-container' "${SSH_CONFIG}" 2>/dev/null; then
    cat >> "${SSH_CONFIG}" <<EOF
# BEGIN agent-container (managed; appended once, never rewritten)
Host *
    IdentityFile ${CONTROL_PLANE_KEY}
    IdentitiesOnly yes
    UserKnownHostsFile ${SSH_DIR}/known_hosts
    StrictHostKeyChecking yes
# END agent-container
EOF
    log "wrote the control-plane ssh_config block"
fi
chmod 0600 "${SSH_CONFIG}"

# --- 3c. The injected host registry (Feature 017 FR-002/FR-004) -------------
# The CLI in this container must resolve hosts with NO on-arrival configuration:
# that is the whole of US1. The operator's registry is injected as non-secret
# config at /run/agent-container/hosts.json, and the CLI reads it from
# $XDG_CONFIG_HOME — so it is COPIED to where the CLI already looks rather than
# the CLI being taught a second location.
#
# Copied, not symlinked: /run is tmpfs and vanishes on restart, and a dangling
# symlink at the CLI's config path reads as a corrupt registry rather than an
# absent one. The copy is refreshed on every boot from whatever the current
# deploy injected, so a redeploy is how the snapshot advances.
#
# IT IS A SNAPSHOT and the log says so. A host registered on the operator's
# machine after this deploy is invisible here until redeploy — stating it in the
# boot log means the operator meets that fact before it confuses them.
CP_CONFIG_DIR="${XDG_CONFIG_HOME:-${AGENT_CONTAINER_HOME}/.config}/agent-container"
INJECTED_REGISTRY="${INJECT_DIR}/hosts.json"
if [[ -f "${INJECTED_REGISTRY}" ]]; then
    mkdir -p "${CP_CONFIG_DIR}"
    if cp "${INJECTED_REGISTRY}" "${CP_CONFIG_DIR}/hosts.json"; then
        chmod 0644 "${CP_CONFIG_DIR}/hosts.json"
        log "host registry installed ($(jq -r '.hosts | length' "${CP_CONFIG_DIR}/hosts.json" 2>/dev/null || echo '?') host(s)) — a SNAPSHOT; a host registered later needs a redeploy to appear"
    else
        # LOUD. The CLI would start and resolve no hosts, which looks like an
        # empty fleet rather than a broken install — and an operator who
        # attached to manage something would conclude it was gone.
        log "WARNING: could not install the injected host registry; the CLI here will resolve NO hosts"
    fi
else
    log "no host registry was injected; the CLI here will resolve no hosts until you redeploy with hosts registered"
fi

# --- 4. sshd ----------------------------------------------------------------
# Daemonize (no -D) so the entrypoint can continue to start tmux and tail.
# AGENT_CONTAINER_SSHD lets the test harness substitute a stub.
"${AGENT_CONTAINER_SSHD:-/usr/sbin/sshd}"
log "sshd listening"

# --- 5. tmux session --------------------------------------------------------
# Detached session named 'main'. Windows are BARE SHELLS. Idempotent: the layout
# is built only inside the has-session guard, so a restart never duplicates
# windows. Window names are validated before reaching tmux.
if tmux has-session -t main 2>/dev/null; then
    log "tmux session 'main' already exists, leaving it alone"
else
    tmux_windows="${AGENT_CONTAINER_TMUX_WINDOWS-shell}"
    valid_windows=()
    for w in ${tmux_windows}; do
        if [[ "${w}" =~ ^[A-Za-z0-9._-]+$ ]]; then
            valid_windows+=("${w}")
        else
            log "skipping invalid tmux window name (must match [A-Za-z0-9._-]+)"
        fi
    done
    if [[ ${#valid_windows[@]} -eq 0 ]]; then
        tmux new-session -d -s main
    else
        tmux new-session -d -s main -n "${valid_windows[0]}"
        for w in "${valid_windows[@]:1}"; do
            tmux new-window -t main -n "${w}"
        done
        tmux select-window -t "main:${valid_windows[0]}"
    fi
    log "tmux session 'main' created"
fi

# --- 6. PID 1 lifecycle + signal handling -----------------------------------
shutdown() {
    log "shutdown signal received, stopping tmux and sshd"
    tmux kill-server 2>/dev/null || true
    pkill -TERM -x sshd 2>/dev/null || true
    exit 0
}

trap shutdown TERM INT

tail -f /dev/null &
TAIL_PID=$!
wait "${TAIL_PID}"
