#!/usr/bin/env bash
# Executes entrypoint.sh against STUBBED tmux/sshd/git/tail to assert its tmux
# window-layout logic, git credential/identity, require_env, and the rootless
# SSH identity (host-key persist/generate/inject + authorized_keys assembly).
# No container, no real sshd/tmux, nothing privileged — the entrypoint itself is
# fully rootless (no sudo).
#
# Run:  bin/tests/test_entrypoint.sh
#
# Covers:
#   1. AGENT_CONTAINER_TMUX_WINDOWS unset      -> windows 'shell edit agents' (${VAR-default}).
#   2. AGENT_CONTAINER_TMUX_WINDOWS=''         -> single default window (opt-out path).
#   3. an injection name is SKIPPED, never forwarded to tmux, and fires no
#      command substitution ('a;b' and '$(touch PWNED)').
#   4. idempotency: the has-session guard means a restart never rebuilds windows.
#   5. git credential helper is scoped to https://github.com (never the global
#      `credential.helper`), and git identity is configured from the env vars —
#      the mechanism behind the non-interactive-push hard constraint.
#   6. require_env: a missing/empty required var aborts with a naming message
#      and a non-zero exit, before sshd/tmux start.
#   7. SSH identity (rootless): host key is generated into ~/.ssh/hostkeys when
#      absent, persisted when present, and OVERRIDDEN by an env(B64) or
#      bind-mounted key (in precedence order); authorized_keys is assembled as a
#      deduped union of the persisted file + env source; sshd is then started.
#
# Mechanics: `sshd` is a recorder stub reached via the AGENT_CONTAINER_SSHD hook
# (the entrypoint calls it by absolute path), `git` records its argv, `tail`
# exits immediately (so the PID-1 `tail -f /dev/null; wait` returns), and `tmux`
# is a dispatcher recording new-session/new-window/select-window argv, modelling
# has-session via a per-run sentinel. `ssh-keygen` runs for real. AGENT_CONTAINER_HOME
# redirects ~/.ssh + the shell-env seeding into a tmpdir; AGENT_CONTAINER_INJECT_DIR
# redirects the bind-mount source dir. bash word-splits ${AGENT_CONTAINER_TMUX_WINDOWS},
# so a valid injection payload must be ';'- or '$(...)'-based; 'a b' is NOT
# injection (bash splits it into two legitimate window names).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRY="${REPO_ROOT}/image/entrypoint.sh"

pass=0
fail=0
note() { printf '%s\n' "$*" >&2; }

check_eq() {  # check_eq <label> <expected> <actual>
    if [[ "$2" == "$3" ]]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        note "FAIL: $1"
        note "  expected: [$2]"
        note "  actual:   [$3]"
    fi
}
check_ne() {  # check_ne <label> <unwanted> <actual>
    if [[ "$2" != "$3" ]]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        note "FAIL: $1"
        note "  must NOT equal: [$2]"
    fi
}
# GNU first, BSD second. The reverse order is a trap: on Linux `stat -f` is VALID
# (it means FILESYSTEM status) and SUCCEEDS, so a `stat -f … || stat -c …` fallback
# never fires and silently returns filesystem info instead of a mode.
perm() { stat -c '%a' "$1" 2>/dev/null || stat -f '%OLp' "$1"; }
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); note "FAIL: $1"; }

cap_hasx()  { grep -qxF "$1" "${CAP}"; }              # exact captured line present
cap_has()   { grep -qF  "$1" "${CAP}"; }             # substring present anywhere
cap_count() { grep -c "^$1" "${CAP}" 2>/dev/null || true; }  # grep -c prints 0 itself
git_has()   { grep -qF "$1" "${GITCAP}"; }           # substring present in git argv log
sshd_ran()  { [[ -s "${SSHDCAP}" ]]; }               # sshd stub was invoked
log_has()   { grep -qF "$1" "${LOG}"; }

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"
CAP="${SB}/capture"
GITCAP="${SB}/gitcapture"
SSHDCAP="${SB}/sshdcapture"
LOG="${SB}/log"
STATE="${SB}/stubstate"; mkdir -p "${STATE}"
HOMEDIR="${SB}/home"; mkdir -p "${HOMEDIR}"
WORK="${SB}/work"; mkdir -p "${WORK}"
INJECTDIR="${SB}/inject"; mkdir -p "${INJECTDIR}"
# Where DELIVERED secrets land (Constitution IX) — /dev/shm in a real
# container, redirected here so this harness can seed and inspect them.
DELIVERDIR="${SB}/deliver"; mkdir -p "${DELIVERDIR}"

# The rootless entrypoint uses NO sudo. sshd is invoked via the absolute path
# /usr/sbin/sshd, so we substitute it through the AGENT_CONTAINER_SSHD hook with
# a recorder stub. ssh-keygen runs for real (present on dev machines + CI), so
# host-key generation/validation is exercised genuinely.
cat > "${STUB}/sshd" <<'EOF'
#!/usr/bin/env bash
printf 'sshd %s\n' "$*" >> "${AGENT_CONTAINER_SSHD_CAPTURE}"
exit 0
EOF
chmod +x "${STUB}/sshd"
# git recorder: append the argv to the capture log (space-joined is fine for the
# substring assertions), then exit 0 so identity/credential config never fails.
cat > "${STUB}/git" <<'EOF'
#!/usr/bin/env bash
printf 'git %s\n' "$*" >> "${AGENT_CONTAINER_GIT_CAPTURE}"
exit 0
EOF
chmod +x "${STUB}/git"
# tail: return immediately so `tail -f /dev/null & wait` unblocks and PID-1 exits.
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/tail"
chmod +x "${STUB}/tail"

# tmux dispatcher: records the interesting argv, models has-session via a
# sentinel, and prints a window id for `new-session -P` (entrypoint captures it).
cat > "${STUB}/tmux" <<'EOF'
#!/usr/bin/env bash
sub="$1"; shift
case "${sub}" in
    has-session)
        [[ -f "${AGENT_CONTAINER_STUB_STATE}/exists" ]] && exit 0 || exit 1 ;;
    new-session)
        : > "${AGENT_CONTAINER_STUB_STATE}/exists"
        printf 'new-session %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"
        for a in "$@"; do [[ "${a}" == "-P" ]] && { printf '@0\n'; break; }; done
        exit 0 ;;
    new-window)
        printf 'new-window %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"; exit 0 ;;
    select-window)
        printf 'select-window %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"; exit 0 ;;
    *) exit 0 ;;
esac
EOF
chmod +x "${STUB}/tmux"

reset_session() { rm -f "${STATE}/exists"; }
# reset_ssh: clean SSH state so a run starts from "no persisted key, no
# injection". SSH-specific tests call this, then set the TEST_ENV_* globals
# and/or drop files in INJECTDIR before run_entrypoint.
reset_ssh() { rm -rf "${HOMEDIR}/.ssh"; rm -rf "${INJECTDIR:?}"/* "${DELIVERDIR:?}"/*; TEST_ENV_AUTHKEYS=""; TEST_ENV_HKB64=""; TEST_PUSH_RUNTIME=""; TEST_APIKEY_RUNTIME=""; }
TEST_ENV_AUTHKEYS=""
TEST_ENV_HKB64=""
TEST_PUSH_RUNTIME=""
TEST_APIKEY_RUNTIME=""

# Shared runtime env for the entrypoint under test (stubs + testability hooks).
_export_env() {
    export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
    export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
    export AGENT_CONTAINER_CAPTURE="${CAP}" AGENT_CONTAINER_STUB_STATE="${STATE}"
    export AGENT_CONTAINER_GIT_CAPTURE="${GITCAP}" AGENT_CONTAINER_SSHD_CAPTURE="${SSHDCAP}"
    # rootless testability hooks: substitute sshd, redirect the bind-mount dir.
    export AGENT_CONTAINER_SSHD="${STUB}/sshd" AGENT_CONTAINER_INJECT_DIR="${INJECTDIR}"
    # Feature 020 / Constitution IX: secrets are DELIVERED into the running
    # container rather than described, and land on a dev-writable tmpfs
    # (/dev/shm) because /run/agent-container is the runtime's root-owned mount
    # point. Redirected here so this off-container harness can seed them.
    export AGENT_CONTAINER_DELIVER_DIR="${DELIVERDIR}"
    # Feature 016: the run-record dir, redirected out of /var/lib. This suite
    # stays on the bare-shell path (no agent) and so writes no record today — the
    # hook is here so that stops being an assumption the moment one is added.
    export AGENT_CONTAINER_RUNS_DIR="${SB}/runs"
    export PATH="${STUB}:${PATH}"
    unset AGENT_CONTAINER_TMUX_WINDOWS
    [[ -n "${TEST_ENV_AUTHKEYS}" ]] && export SSH_AUTHORIZED_KEYS="${TEST_ENV_AUTHKEYS}" || unset SSH_AUTHORIZED_KEYS
    [[ -n "${TEST_ENV_HKB64}" ]] && export SSH_HOST_ED25519_KEY_B64="${TEST_ENV_HKB64}" || unset SSH_HOST_ED25519_KEY_B64
    [[ -n "${TEST_PUSH_RUNTIME}" ]] && export AGENT_CONTAINER_PUSH_RUNTIME="${TEST_PUSH_RUNTIME}" || unset AGENT_CONTAINER_PUSH_RUNTIME
    [[ -n "${TEST_APIKEY_RUNTIME}" ]] && export AGENT_CONTAINER_APIKEY_RUNTIME="${TEST_APIKEY_RUNTIME}" || unset AGENT_CONTAINER_APIKEY_RUNTIME
    # A leaked provider key env must never steer the US2 file-injection tests.
    unset ANTHROPIC_API_KEY OPENAI_API_KEY
    # Feature 004: keep this suite on the pre-004 bare-shell path — no execution
    # mode/agent/clone. Those behaviors are covered by test_entrypoint_execution.sh.
    unset AGENT_CONTAINER_MODE AGENT_CONTAINER_AGENT AGENT_CONTAINER_CLONE_URL AGENT_CONTAINER_WORKSPACE
}

# run_entrypoint <mode>; mode is __unset__ | __empty__ | any literal value.
run_entrypoint() {
    local mode="$1"
    : > "${CAP}"; : > "${GITCAP}"; : > "${SSHDCAP}"; : > "${LOG}"
    (
        cd "${WORK}" || exit 99
        _export_env
        case "${mode}" in
            __unset__) : ;;
            __empty__) export AGENT_CONTAINER_TMUX_WINDOWS="" ;;
            *)         export AGENT_CONTAINER_TMUX_WINDOWS="${mode}" ;;
        esac
        bash "${ENTRY}" >/dev/null 2>"${LOG}"
    )
}

# run_missing <varname>: run the entrypoint with one required var unset (others
# valid) and print its exit code. Captures the entrypoint's stderr into LOG.
run_missing() {
    local missing="$1"
    : > "${CAP}"; : > "${GITCAP}"; : > "${SSHDCAP}"; : > "${LOG}"
    (
        cd "${WORK}" || exit 99
        _export_env
        unset "${missing}"
        bash "${ENTRY}" >/dev/null 2>"${LOG}"
    )
    printf '%s' "$?"
}

# --- 1. unset AGENT_CONTAINER_TMUX_WINDOWS -> default 'shell edit agents' --------------
reset_session
run_entrypoint __unset__
check_eq "unset: first window is 'shell' on session main (with -P id capture)" \
    "new-session -d -P -F #{window_id} -s main -n shell" "$(grep '^new-session' "${CAP}")"
if cap_hasx 'new-window -t main -n edit';   then ok; else bad "unset: new-window edit"; fi
if cap_hasx 'new-window -t main -n agents'; then ok; else bad "unset: new-window agents"; fi
check_eq "unset: exactly two extra windows" "2" "$(cap_count 'new-window')"
# select-window targets the CAPTURED window id (@0), never the numeric/name
# string — the TMUX-1 fix. (Stub prints '@0' for the -P new-session.)
if cap_hasx 'select-window -t @0'; then ok; else bad "unset: select-window by id @0"; fi

# --- 2. empty AGENT_CONTAINER_TMUX_WINDOWS -> single default window (opt-out) ----------
reset_session
run_entrypoint __empty__
check_eq "empty: exactly one bare 'new-session -d -s main' (no -n, no -P)" \
    "new-session -d -s main" "$(grep '^new-session' "${CAP}")"
check_eq "empty: no new-window calls"    "0" "$(cap_count 'new-window')"
check_eq "empty: no select-window calls" "0" "$(cap_count 'select-window')"

# --- 3a. injection 'a;b' is skipped, never forwarded -------------------------
reset_session
run_entrypoint 'a;b'
if cap_has 'a;b'; then bad "'a;b': token must never reach tmux argv"; else ok; fi
check_eq "'a;b': falls back to single default window" \
    "new-session -d -s main" "$(grep '^new-session' "${CAP}")"
check_eq "'a;b': no new-window calls" "0" "$(cap_count 'new-window')"
if log_has 'skipping invalid tmux window name'; then ok; else bad "'a;b': skip log fires"; fi

# --- 3b. injection '$(touch PWNED)' skipped AND no command substitution -------
reset_session
rm -f "${WORK}/PWNED"
run_entrypoint '$(touch PWNED)'
if [[ -e "${WORK}/PWNED" ]]; then bad "'\$(touch PWNED)': command substitution must NOT fire"; else ok; fi
if cap_has 'PWNED'; then bad "'\$(touch PWNED)': token must never reach tmux argv"; else ok; fi
check_eq "'\$(touch PWNED)': falls back to single default window" \
    "new-session -d -s main" "$(grep '^new-session' "${CAP}")"
if log_has 'skipping invalid tmux window name'; then ok; else bad "'\$(touch PWNED)': skip log fires"; fi

# --- 4. idempotency: has-session guard prevents a rebuild on restart ---------
reset_session
run_entrypoint __unset__                       # pass 1: builds the layout
if cap_has 'new-session'; then ok; else bad "idempotency pass 1 should build the session"; fi
run_entrypoint __unset__                        # pass 2: session now 'exists'
check_eq "idempotency: pass 2 makes no new-session"   "0" "$(cap_count 'new-session')"
check_eq "idempotency: pass 2 makes no new-window"    "0" "$(cap_count 'new-window')"
check_eq "idempotency: pass 2 makes no select-window" "0" "$(cap_count 'select-window')"
if log_has "already exists, leaving it alone"; then ok; else bad "idempotency: pass 2 logs the guard"; fi

# --- 5. git credential helper scoping + identity -----------------------------
# The helper MUST be registered under credential.https://github.com.helper, not
# the global credential.helper, so ${GH_TOKEN} is never offered to other hosts.
# (Substring 'credential.helper' cannot appear inside the scoped key
# 'credential.https://github.com.helper', so it uniquely flags the global form.)
reset_session
run_entrypoint __unset__
if git_has 'credential.https://github.com.helper'; then ok; else bad "cred: helper is scoped to https://github.com"; fi
if git_has 'credential.helper '; then bad "cred: global unscoped credential.helper must NOT be set"; else ok; fi
# The token itself is stored as the literal '${GH_TOKEN}' (expanded at push
# time), never the resolved value — assert the literal is present.
if git_has 'password=${GH_TOKEN}'; then ok; else bad "cred: helper body carries literal \${GH_TOKEN}"; fi
# Identity is configured from the env vars.
if git_has 'user.name Test User';      then ok; else bad "identity: user.name configured"; fi
if git_has 'user.email t@example.com'; then ok; else bad "identity: user.email configured"; fi

# --- 6. require_env: a missing required var aborts before sshd/tmux -----------
for v in GH_TOKEN GIT_USER_NAME GIT_USER_EMAIL; do
    reset_session
    rc="$(run_missing "${v}")"
    check_eq "require_env(${v}): non-zero exit" "1" "${rc}"
    if log_has "required env var ${v} is missing"; then ok; else bad "require_env(${v}): names the offender"; fi
    # Aborts BEFORE the tmux layout is built.
    if cap_has 'new-session'; then bad "require_env(${v}): must abort before tmux starts"; else ok; fi
done

# --- 7. SSH identity: rootless host key + authorized_keys --------------------
HK="${HOMEDIR}/.ssh/hostkeys/ssh_host_ed25519_key"
AK="${HOMEDIR}/.ssh/authorized_keys"
fp() { ssh-keygen -lf "$1" 2>/dev/null | awk '{print $2}'; }

# 7a. generate-if-absent: fresh ~/.ssh -> host key created (0600), sshd started.
reset_session; reset_ssh
run_entrypoint __unset__
if [[ -f "${HK}" && -f "${HK}.pub" ]]; then ok; else bad "ssh: host key generated at ~/.ssh/hostkeys"; fi
if log_has 'generating SSH host key'; then ok; else bad "ssh: generation log fires"; fi
if sshd_ran; then ok; else bad "ssh: sshd started"; fi
GEN_FP="$(fp "${HK}.pub")"

# 7b. persistence: a second run keeps the SAME key (does not regenerate).
reset_session
run_entrypoint __unset__
check_eq "ssh: host key persists across runs" "${GEN_FP}" "$(fp "${HK}.pub")"
if log_has 'already present, skipping'; then ok; else bad "ssh: persist log fires"; fi

# A known ed25519 keypair, used to prove the removed channels are INERT.
KNOWN="${SB}/known_hostkey"
ssh-keygen -q -t ed25519 -f "${KNOWN}" -N '' <<<y >/dev/null 2>&1
KNOWN_FP="$(fp "${KNOWN}.pub")"

# 7c/7d. Feature 018 REMOVED both private-host-key injection channels. The
# assertions invert rather than disappearing: offering the key must now change
# NOTHING. A deleted test would leave nobody watching for the channel's return, and
# these two put a plaintext private key on the operator's disk.
reset_session; reset_ssh
run_entrypoint __unset__
GEN2_FP="$(fp "${HK}.pub")"          # whatever this container generated for itself
reset_session
TEST_ENV_HKB64="$(base64 < "${KNOWN}" | tr -d '\n')"
cp "${KNOWN}" "${INJECTDIR}/ssh_host_ed25519_key"
run_entrypoint __unset__
check_eq "ssh: SSH_HOST_ED25519_KEY_B64 is IGNORED (018)" "${GEN2_FP}" "$(fp "${HK}.pub")"
check_ne "ssh: the offered key never becomes the identity (018)" "${KNOWN_FP}" "$(fp "${HK}.pub")"
if log_has 'from SSH_HOST_ED25519_KEY_B64'; then bad "ssh: env-B64 channel still installs"; else ok; fi
if log_has 'installing bind-mounted SSH host key'; then bad "ssh: bind-mount channel still installs"; else ok; fi
rm -f "${INJECTDIR}/ssh_host_ed25519_key"
TEST_ENV_HKB64=""

# 7d2. The PUBLIC half is derived on every boot and world-readable: that file is what
# the tool reads back through the runtime to pin (Feature 018). If it stops being
# written, capture silently stops working and every attach falls to the prompt.
if [[ -f "${HK}.pub" ]]; then ok; else bad "ssh: the .pub the tool captures exists"; fi
check_eq "ssh: the .pub is world-readable for capture" "644" "$(perm "${HK}.pub")"
check_eq "ssh: the PRIVATE key stays 0600" "600" "$(perm "${HK}")"

# 7e. authorized_keys is a MANAGED REGION, not a union (Feature 020, FR-006).
# REWRITTEN, not deleted. The union this replaced retained every key ever injected,
# so removing a key from the source could never withdraw access — and an assertion
# that merely disappears leaves nobody watching for the union's return, which is
# why 7c/7d were inverted rather than dropped.
reset_session; reset_ssh
PUB1="ssh-ed25519 AAAAKEY1 laptop"; PUB2="ssh-ed25519 AAAAKEY2 desktop"
AK_B='BEGIN agent-container managed keys'; AK_E='END agent-container managed keys'
printf '%s\n%s\n' "${PUB1}" "${PUB2}" > "${INJECTDIR}/authorized_keys"
run_entrypoint __unset__
check_eq "ssh: the region holds both granted keys" "2" "$(grep -c '^ssh-' "${AK}")"
check_eq "ssh: exactly one region BEGIN marker" "1" "$(grep -c "${AK_B}" "${AK}")"
check_eq "ssh: exactly one region END marker" "1" "$(grep -c "${AK_E}" "${AK}")"
check_eq "ssh: authorized_keys stays 0600" "600" "$(perm "${AK}")"

# 7e2. REMOVAL REVOKES. This is the assertion the union made impossible, and the
# whole reason the region exists: drop PUB2 from the source, recreate, and it must
# be GONE rather than retained from the persisted file.
reset_session
printf '%s\n' "${PUB1}" > "${INJECTDIR}/authorized_keys"
run_entrypoint __unset__
if grep -qxF "${PUB2}" "${AK}"; then bad "ssh: a key removed from the source is STILL authorized (FR-006)"; else ok; fi
if grep -qxF "${PUB1}" "${AK}"; then ok; else bad "ssh: the still-granted key vanished with it"; fi

# 7e3. SSH_AUTHORIZED_KEYS is supplied per boot, so it belongs INSIDE the region.
# Outside, it would persist after the env var stopped being set — the same
# never-revocable grant in a different disguise.
reset_session; reset_ssh
TEST_ENV_AUTHKEYS="${PUB2}"
run_entrypoint __unset__
if sed -n "/${AK_B}/,/${AK_E}/p" "${AK}" | grep -qxF "${PUB2}"; then ok; else bad "ssh: the env-supplied key landed outside the region"; fi
TEST_ENV_AUTHKEYS=""

# --- 7f. The region's boundary: what the tool owns, and what it must not touch --
# 7f1. Content the tool did not write SURVIVES (FR-016). FR-015 governs what the
# tool grants; it does not make the tool the owner of a file the operator edits.
reset_session; reset_ssh
HAND="ssh-ed25519 AAAAHAND operator"
printf '%s\n' "${PUB1}" > "${INJECTDIR}/authorized_keys"
run_entrypoint __unset__
printf '%s\n' "${HAND}" >> "${AK}"          # as if added by hand from inside
reset_session
run_entrypoint __unset__
if grep -qxF "${HAND}" "${AK}"; then ok; else bad "ssh: a hand-added key outside the region was DELETED"; fi

# 7f2. A key present BOTH inside and outside: OUR duplicate goes, THEIRS stays, so
# a recreate still withdraws what the tool granted while their line survives.
# Dropping theirs instead would leave the key authorized after removal — FR-006
# failing silently, which is the worst of the available bugs.
reset_session; reset_ssh
printf '%s\n' "${PUB1}" > "${INJECTDIR}/authorized_keys"
run_entrypoint __unset__
printf '%s\n' "${PUB1}" > "${AK}.tmp"; cat "${AK}" >> "${AK}.tmp"; mv "${AK}.tmp" "${AK}"
reset_session
run_entrypoint __unset__
check_eq "ssh: a key held inside and outside appears once" "1" "$(grep -cxF "${PUB1}" "${AK}")"
if sed -n "/${AK_B}/,/${AK_E}/p" "${AK}" | grep -qxF "${PUB1}"; then bad "ssh: kept OUR copy instead of the operator's line"; else ok; fi

# 7f3. A collection that becomes absent EMPTIES the region rather than leaving a
# stale set behind (C16) — and still does not touch what is outside it.
reset_session
: > "${INJECTDIR}/authorized_keys"
run_entrypoint __unset__
check_eq "ssh: an absent source empties the region" "0" "$(sed -n "/${AK_B}/,/${AK_E}/p" "${AK}" | grep -c '^ssh-')"
if grep -qxF "${PUB1}" "${AK}"; then ok; else bad "ssh: emptying the region removed the operator's own line"; fi

# 7f4. A malformed region is REFUSED, never repaired (C17). One sentinel without
# its pair means the extent is unknown, and guessing a boundary risks deleting
# keys the operator added themselves.
reset_session; reset_ssh
mkdir -p "${HOMEDIR}/.ssh"                              # reset_ssh removed it
printf '# %s\n%s\n' "${AK_B}" "${PUB1}" > "${AK}"     # BEGIN with no END
run_entrypoint __unset__
if log_has 'malformed managed region'; then ok; else bad "ssh: a half-marked region was rewritten instead of refused"; fi
if grep -qxF "${PUB1}" "${AK}"; then ok; else bad "ssh: refusing to rewrite still lost a key"; fi
reset_ssh

# --- 8. The agent's own SSH key pair (Feature 019) ---------------------------
# GENERATED HERE and never supplied. The assertions INVERT rather than disappear:
# offering a key through either removed channel must now change NOTHING, and a
# removal with no test behind it is a removal nobody notices being undone.
reset_session; reset_ssh
PKSRC="${SB}/offered_key"; ssh-keygen -q -t ed25519 -f "${PKSRC}" -N '' <<<y >/dev/null 2>&1
cp "${PKSRC}" "${INJECTDIR}/push_ed25519_key"
TEST_ENV_PUSHB64="$(base64 < "${PKSRC}" | tr -d '\n')"
printf 'github.com ssh-ed25519 AAAAKH\n' > "${INJECTDIR}/known_hosts"
run_entrypoint __unset__

AGENTKEY="${HOMEDIR}/.ssh/id_ed25519"
# The key exists at the CONVENTIONAL path — which is what makes git, ssh, scp and
# rsync all use it with no wiring at all.
if [[ -f "${AGENTKEY}" ]]; then ok; else bad "agent key: generated at ~/.ssh/id_ed25519"; fi
check_eq "agent key: private is 0600" "600" "$(perm "${AGENTKEY}")"
check_eq "agent key: public is 0644" "644" "$(perm "${AGENTKEY}.pub")"
# NEITHER offered key became the identity.
if ! cmp -s "${PKSRC}" "${AGENTKEY}"; then ok; else bad "agent key: an OFFERED key became the identity"; fi
# core.sshCommand and the /tmp scaffolding are GONE, not rewired.
if git_has 'core.sshCommand'; then bad "agent key: core.sshCommand still configured"; else ok; fi
if [[ ! -e "${SB}/pushrt" ]]; then ok; else bad "agent key: PUSH_RUNTIME scaffolding survives"; fi
# Idempotent: a second boot KEEPS the key. Regenerating would silently invalidate
# the operator's registration while every other symptom looked healthy.
FP1="$(fp "${AGENTKEY}.pub")"
reset_session
run_entrypoint __unset__
check_eq "agent key: a second boot keeps it" "${FP1}" "$(fp "${AGENTKEY}.pub")"
# The ssh_config block is explicit, and appended ONCE.
CFG="${HOMEDIR}/.ssh/config"
if grep -q 'IdentitiesOnly yes' "${CFG}"; then ok; else bad "agent config: IdentitiesOnly"; fi
if grep -q 'StrictHostKeyChecking accept-new' "${CFG}"; then ok; else bad "agent config: StrictHostKeyChecking"; fi
check_eq "agent config: block appended once, not repeatedly" "1" "$(grep -c '^# BEGIN agent-container' "${CFG}")"
# THE CASE THAT MATTERS: a config the agent wrote FIRST must still gain the block,
# or StrictHostKeyChecking is never set and every ssh hangs on a prompt it cannot answer.
reset_session; reset_ssh
mkdir -p "${HOMEDIR}/.ssh"; printf 'Host early\n    User someone\n' > "${CFG}"
run_entrypoint __unset__
if grep -q 'Host early' "${CFG}"; then ok; else bad "agent config: the agent's own entry was clobbered"; fi
if grep -q 'IdentitiesOnly yes' "${CFG}"; then ok; else bad "agent config: pre-existing file never gained the block"; fi
TEST_ENV_PUSHB64=""
rm -f "${INJECTDIR}/push_ed25519_key"

# 8b. no push key injected -> no core.sshCommand (HTTPS path is unaffected)
reset_session; reset_ssh; PUSHRT2="${SB}/pushrt2"; rm -rf "${PUSHRT2}"; TEST_PUSH_RUNTIME="${PUSHRT2}"
run_entrypoint __unset__
if git_has 'core.sshCommand'; then bad "push: no key -> core.sshCommand must NOT be set"; else ok; fi

# --- 9. Model/API credentials (Feature 003 US2) ------------------------------
# Provider keys are DELIVERED as files under ${DELIVER_DIR}/apikey/<provider>,
# delivered EPHEMERALLY (H1/FR-012): Claude gets an apiKeyHelper that CATS the
# injected key (the key value never lands on the ~/.claude volume); Codex/pi get
# their homes REDIRECTED to an ephemeral dir so nothing they write hits the
# -codex/-pi volume. Absent injected keys -> no wiring at all.
CLAUDE_SETTINGS="${HOMEDIR}/.claude/settings.json"
CLAUDE_HELPER="${HOMEDIR}/.claude/apikey-helper.sh"

reset_session; reset_ssh
APIRT="${SB}/apirt"; rm -rf "${APIRT}"; TEST_APIKEY_RUNTIME="${APIRT}"
rm -rf "${HOMEDIR}/.claude" "${HOMEDIR}/.codex" "${HOMEDIR}/.pi"
mkdir -p "${DELIVERDIR}/apikey"
printf 'sk-ant-SECRETVALUE\n' > "${DELIVERDIR}/apikey/anthropic"
printf 'sk-oai-SECRETVALUE\n'  > "${DELIVERDIR}/apikey/openai"
run_entrypoint __unset__

# Claude: settings.json carries an apiKeyHelper pointing at a helper script that
# cats the EPHEMERAL injected key — never the key value itself.
if [[ -f "${CLAUDE_SETTINGS}" ]] && grep -qF 'apiKeyHelper' "${CLAUDE_SETTINGS}"; then ok; else bad "apikey: Claude settings.json gets apiKeyHelper"; fi
if [[ -x "${CLAUDE_HELPER}" ]] && grep -qF "${DELIVERDIR}/apikey/anthropic" "${CLAUDE_HELPER}"; then ok; else bad "apikey: helper cats the injected anthropic path"; fi
# H1/FR-012: the anthropic key VALUE must not be written onto the ~/.claude volume.
if grep -rqF 'sk-ant-SECRETVALUE' "${HOMEDIR}/.claude" 2>/dev/null; then bad "apikey: anthropic key value must NOT land on the ~/.claude volume"; else ok; fi

# Codex: CODEX_HOME redirected to the ephemeral runtime dir (off the -codex volume);
# the key value is never written under ~/.codex.
if [[ -d "${APIRT}/codex-home" ]]; then ok; else bad "apikey: Codex home redirected to the ephemeral dir"; fi
if grep -rqF 'sk-oai-SECRETVALUE' "${HOMEDIR}/.codex" 2>/dev/null; then bad "apikey: openai key value must NOT land on the ~/.codex volume"; else ok; fi
if log_has 'CODEX_HOME'; then ok; else bad "apikey: Codex redirect is logged"; fi

# pi: PI_CODING_AGENT_DIR redirected to the ephemeral runtime dir (off the -pi volume).
if [[ -d "${APIRT}/pi-home" ]]; then ok; else bad "apikey: pi home redirected to the ephemeral dir"; fi
if grep -rqF 'sk-ant-SECRETVALUE' "${HOMEDIR}/.pi" 2>/dev/null; then bad "apikey: key value must NOT land on the ~/.pi volume"; else ok; fi

# 9b. no injected key -> no apiKeyHelper, no ephemeral homes (env/.env path intact)
reset_session; reset_ssh
APIRT2="${SB}/apirt2"; rm -rf "${APIRT2}"; TEST_APIKEY_RUNTIME="${APIRT2}"
rm -rf "${HOMEDIR}/.claude" "${HOMEDIR}/.codex" "${HOMEDIR}/.pi"
run_entrypoint __unset__
if [[ -e "${HOMEDIR}/.claude/settings.json" ]]; then bad "apikey: no key -> no apiKeyHelper settings written"; else ok; fi
if [[ -d "${APIRT2}/codex-home" || -d "${APIRT2}/pi-home" ]]; then bad "apikey: no key -> no ephemeral homes created"; else ok; fi

note ""
note "entrypoint tmux tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
