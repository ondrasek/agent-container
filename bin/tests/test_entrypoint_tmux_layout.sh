#!/usr/bin/env bash
# Integration companion to test_entrypoint.sh: instead of a STUB tmux, this
# drives entrypoint.sh's window-building against a REAL, throwaway tmux server
# on a private '-L <socket>' so we assert the windows actually materialize the
# way the stub test only models. Guarded by `command -v tmux`: absent tmux =>
# SKIP (exit 0), so CI without tmux stays green.
#
# Run:  bin/tests/test_entrypoint_tmux_layout.sh
#
# Mechanics: sudo/git/tail are no-op stubs (no ssh-keygen/sshd/git/blocking),
# and a `tmux` WRAPPER on PATH execs the real tmux with '-L ${SOCKET}' injected
# ahead of every subcommand, so the entrypoint's unqualified `tmux ...` calls all
# land on one disposable server we can inspect afterwards. The server is a daemon
# (new-session -d), so it outlives the entrypoint's normal exit and we query it.
#
# Contract asserted against real tmux:
#   1. unset AGENT_CONTAINER_TMUX_WINDOWS -> windows 'shell edit agents' exist, in order,
#      and the ACTIVE window is 'shell' (the select-window-by-id fix, verified
#      against a real server rather than a stub echo).
#   2. idempotency: a second entrypoint run (session already exists) leaves the
#      window set byte-identical — no rebuild, no duplicates.
#   3. explicit-empty AGENT_CONTAINER_TMUX_WINDOWS='' -> exactly ONE window (opt-out).

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
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); note "FAIL: $1"; }

# --- guard: real tmux required ----------------------------------------------
if ! REAL_TMUX="$(command -v tmux)"; then
    note "SKIP: tmux not on PATH; real-socket layout test not run"
    exit 0
fi

SB="$(mktemp -d)"
STUB="${SB}/stub"; mkdir -p "${STUB}"
HOMEDIR="${SB}/home"; mkdir -p "${HOMEDIR}"
WORK="${SB}/work"; mkdir -p "${WORK}"
# Private tmux socket for this run; unique per pid so parallel runs never collide.
SOCK="agent-container-layout-test-$$"

cleanup() {
    "${REAL_TMUX}" -L "${SOCK}" kill-server >/dev/null 2>&1 || true
    rm -rf "${SB}"
}
trap cleanup EXIT

# no-op identity command + non-blocking tail (so PID-1 `wait` returns). The
# rootless entrypoint uses no sudo; sshd is substituted via AGENT_CONTAINER_SSHD
# (below), and ssh-keygen runs for real to seed the host key.
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/git"
chmod +x "${STUB}/git"
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/tail"
chmod +x "${STUB}/tail"
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/sshd"
chmod +x "${STUB}/sshd"

# tmux wrapper: forward every call to the REAL tmux on a private socket. The
# entrypoint calls `tmux <sub> ...` unqualified; injecting '-L ${SOCK}' ahead of
# the subcommand confines all of it to one disposable server.
cat > "${STUB}/tmux" <<'EOF'
#!/usr/bin/env bash
exec "${AGENT_CONTAINER_REAL_TMUX}" -L "${AGENT_CONTAINER_TMUX_SOCKET}" "$@"
EOF
chmod +x "${STUB}/tmux"

# run_entrypoint <mode>; mode is __unset__ | __empty__ | any literal value.
run_entrypoint() {
    local mode="$1"
    (
        cd "${WORK}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
        export AGENT_CONTAINER_REAL_TMUX="${REAL_TMUX}" AGENT_CONTAINER_TMUX_SOCKET="${SOCK}"
        export AGENT_CONTAINER_SSHD="${STUB}/sshd" AGENT_CONTAINER_INJECT_DIR="${SB}/inject"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS
        case "${mode}" in
            __unset__) : ;;
            __empty__) export AGENT_CONTAINER_TMUX_WINDOWS="" ;;
            *)         export AGENT_CONTAINER_TMUX_WINDOWS="${mode}" ;;
        esac
        bash "${ENTRY}" >/dev/null 2>&1
    )
}

# Query helpers against the real server.
windows()       { "${REAL_TMUX}" -L "${SOCK}" list-windows -t main -F '#{window_name}' 2>/dev/null; }
active_window() { "${REAL_TMUX}" -L "${SOCK}" list-windows -t main -F '#{?window_active,#{window_name},}' 2>/dev/null | grep -v '^$'; }
window_count()  { windows | grep -c .; }

# --- 1. unset -> real 'shell edit agents', active window is 'shell' ----------
"${REAL_TMUX}" -L "${SOCK}" kill-server >/dev/null 2>&1 || true
run_entrypoint __unset__
check_eq "unset: windows are exactly 'shell edit agents' in order" \
    "shell edit agents" "$(windows | paste -sd' ' -)"
check_eq "unset: exactly three windows" "3" "$(window_count)"
check_eq "unset: active window is 'shell' (select-window-by-id fix, real tmux)" \
    "shell" "$(active_window)"

# --- 2. idempotency: second run does not rebuild or duplicate ----------------
run_entrypoint __unset__
check_eq "idempotency: window set unchanged after a second run" \
    "shell edit agents" "$(windows | paste -sd' ' -)"
check_eq "idempotency: still exactly three windows" "3" "$(window_count)"

# --- 3. explicit-empty -> single window (opt-out) ----------------------------
"${REAL_TMUX}" -L "${SOCK}" kill-server >/dev/null 2>&1 || true
run_entrypoint __empty__
check_eq "empty: exactly one window (single default, opt-out)" "1" "$(window_count)"

note ""
note "entrypoint real-tmux layout tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
