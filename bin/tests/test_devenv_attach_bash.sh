#!/usr/bin/env bash
# Executes bin/devenv-attach (the standalone bash client) against a STUBBED ssh
# to assert the argv it constructs — the --window compound remote command, the
# WINDOW_RE injection rejection, the no-window legacy argv, and remote-mode
# hosts.conf resolution. No real ssh/docker/podman is needed.
#
# Run:  bin/tests/test_devenv_attach_bash.sh
#
# bin/devenv-attach is otherwise unexercised: bin/devenv cmd_attach is covered
# by test_devenv_bash.sh and bin/devenv-wiz cli_attach by the Python tests, but
# this third attach implementation had zero coverage before this harness.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ATTACH="${REPO_ROOT}/bin/devenv-attach"

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

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"
CAP="${SB}/capture"

# Seed local state (STATE_DIR/<name>.port) and remote hosts.conf so both attach
# paths resolve. Names: 'acme' (local, port 2206) and 'box' (remote).
STATE="${SB}/state/devenv"; mkdir -p "${STATE}"
printf '2206\n' > "${STATE}/acme.port"
CONF="${SB}/config/devenv"; mkdir -p "${CONF}"
cat > "${CONF}/hosts.conf" <<'EOF'
BOX_HOST=vps.example.com
BOX_PORT=2222
EOF

# Stub 'ssh' so `exec ssh ...` is captured, not executed: each argv element on
# its own line in the capture file (so the single compound --window remote arg
# stays on one line and is directly assertable).
cat > "${STUB}/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "${DEVENV_CAPTURE}"
EOF
chmod +x "${STUB}/ssh"

run_attach() {  # run_attach <args...>; resets + fills ${CAP}; returns rc
    : > "${CAP}"
    ( DEVENV_CAPTURE="${CAP}" \
        XDG_STATE_HOME="${SB}/state" XDG_CONFIG_HOME="${SB}/config" \
        PATH="${STUB}:${PATH}" \
        "${ATTACH}" "$@" >/dev/null 2>&1 )
}

# --- 1. local --window: select-then-attach single compound remote arg --------
run_attach -l -w edit acme
expected_local_w="dev@localhost
-p
2206
-t
tmux select-window -t main:edit 2>/dev/null; exec tmux attach -t main"
check_eq "-l -w edit == select-then-attach single remote arg" "${expected_local_w}" "$(cat "${CAP}")"

# --- 2. local no-window: exact legacy argv -----------------------------------
run_attach -l acme
expected_local="dev@localhost
-p
2206
-t
tmux
attach
-t
main"
check_eq "-l (no --window) == canonical legacy argv" "${expected_local}" "$(cat "${CAP}")"

# --- 3. injection window names rejected BEFORE any ssh call -------------------
for w in 'a;b' 'a b' 'a$(touch X)' '-oProxyCommand=x'; do
    if run_attach -l -w "${w}" acme; then bad "invalid --window '${w}' should exit nonzero"; else ok; fi
    check_eq "invalid --window '${w}' makes no ssh call" "" "$(cat "${CAP}")"
done

# --- 4. remote mode resolves host+port from hosts.conf -----------------------
run_attach -w agents box
expected_remote_w="dev@vps.example.com
-p
2222
-t
tmux select-window -t main:agents 2>/dev/null; exec tmux attach -t main"
check_eq "remote -w agents box == hosts.conf host/port + compound arg" "${expected_remote_w}" "$(cat "${CAP}")"
run_attach box
expected_remote="dev@vps.example.com
-p
2222
-t
tmux
attach
-t
main"
check_eq "remote box (no --window) == hosts.conf host/port legacy argv" "${expected_remote}" "$(cat "${CAP}")"

note ""
note "devenv-attach bash tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
