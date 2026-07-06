#!/usr/bin/env bash
# Executes entrypoint.sh against STUBBED tmux/sudo/git/tail to assert its tmux
# window-layout logic AND its git credential/identity + require_env behavior —
# the pieces with zero prior coverage. No container, no real sshd/tmux, nothing
# privileged.
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
#
# Mechanics: `sudo` is a no-op stub, `git` records its argv (so the credential
# helper / identity config can be asserted while still exiting 0), `tail` exits
# immediately (so the PID-1 `tail -f /dev/null; wait` returns instead of
# blocking), and `tmux` is a dispatcher that records
# new-session/new-window/select-window argv and models has-session via a
# per-run sentinel file. AGENT_CONTAINER_HOME redirects the shell-env seeding path into a
# writable tmpdir. bash word-splits ${AGENT_CONTAINER_TMUX_WINDOWS}, so a valid injection
# payload must be ';'- or '$(...)'-based; 'a b' is NOT injection (bash splits it
# into two legitimate window names).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRY="${REPO_ROOT}/entrypoint.sh"

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
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); note "FAIL: $1"; }

cap_hasx()  { grep -qxF "$1" "${CAP}"; }              # exact captured line present
cap_has()   { grep -qF  "$1" "${CAP}"; }             # substring present anywhere
cap_count() { grep -c "^$1" "${CAP}" 2>/dev/null || true; }  # grep -c prints 0 itself
git_has()   { grep -qF "$1" "${GITCAP}"; }           # substring present in git argv log
log_has()   { grep -qF "$1" "${LOG}"; }

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"
CAP="${SB}/capture"
GITCAP="${SB}/gitcapture"
LOG="${SB}/log"
STATE="${SB}/stubstate"; mkdir -p "${STATE}"
HOMEDIR="${SB}/home"; mkdir -p "${HOMEDIR}"
WORK="${SB}/work"; mkdir -p "${WORK}"

# no-op privileged command (ssh-keygen/sshd/mkdir all run through sudo).
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/sudo"
chmod +x "${STUB}/sudo"
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

# run_entrypoint <mode>; mode is __unset__ | __empty__ | any literal value.
run_entrypoint() {
    local mode="$1"
    : > "${CAP}"; : > "${GITCAP}"; : > "${LOG}"
    (
        cd "${WORK}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
        export AGENT_CONTAINER_CAPTURE="${CAP}" AGENT_CONTAINER_STUB_STATE="${STATE}"
        export AGENT_CONTAINER_GIT_CAPTURE="${GITCAP}"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS
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
    : > "${CAP}"; : > "${GITCAP}"; : > "${LOG}"
    (
        cd "${WORK}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
        export AGENT_CONTAINER_CAPTURE="${CAP}" AGENT_CONTAINER_STUB_STATE="${STATE}"
        export AGENT_CONTAINER_GIT_CAPTURE="${GITCAP}"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS
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

note ""
note "entrypoint tmux tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
