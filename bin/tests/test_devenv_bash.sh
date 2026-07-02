#!/usr/bin/env bash
# Executes bin/devenv (bash) against a STUBBED container runtime to assert the
# argv it constructs — the cross-script parity contract with bin/devenv-wiz —
# plus --mount resolution, --purge volume handling, and symlink path resolution.
# No real docker/podman is needed.
#
# Run:  bin/tests/test_devenv_bash.sh
#
# The expected 'up' argv below MUST stay identical to bin/devenv-wiz's
# launch_container output asserted in bin/tests/test_command_construction.py.
# If the two drift, one of these tests fails — which is the whole point (before
# this harness, bin/devenv's argv had zero coverage and could drift silently).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVENV="${REPO_ROOT}/bin/devenv"
IMAGE="localhost/remote-persistent-devenv:latest"

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

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); note "FAIL: $1"; }

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"
CAP="${SB}/capture"
WORK="${SB}/work"; mkdir -p "${WORK}"
printf 'GH_TOKEN=x\n' > "${WORK}/.env"

# Stub named 'docker' so detect_runtime (which only accepts docker|podman)
# resolves it. It never touches a real container: 'ps' returns nothing (so the
# container reads as not-running/not-existing), 'run' and 'volume rm' append
# their argv to the capture file, everything else is a no-op.
cat > "${STUB}/docker" <<'EOF'
#!/usr/bin/env bash
case "$1" in
    ps)     exit 0 ;;
    run)    printf '%s\n' "$@" >> "${DEVENV_CAPTURE}"; exit 0 ;;
    volume) printf 'VOLRM %s\n' "$3" >> "${DEVENV_CAPTURE}"; exit 0 ;;
    *)      exit 0 ;;
esac
EOF
chmod +x "${STUB}/docker"

run_devenv() {  # run_devenv <args...>; resets + fills ${CAP}; returns devenv's rc
    : > "${CAP}"
    ( cd "${WORK}" \
        && DEVENV_RUNTIME=docker DEVENV_CAPTURE="${CAP}" \
           XDG_STATE_HOME="${SB}/state" PATH="${STUB}:${PATH}" \
           "${DEVENV}" "$@" >/dev/null 2>&1 )
}

# --- 1. 'up' argv: the 6-volume / flag / image parity contract --------------
run_devenv up acme
expected_up="run
-d
--name
devenv-acme
--env-file
${WORK}/.env
-p
2206:22
-v
devenv-acme-workspace:/workspace
-v
devenv-acme-claude:/home/dev/.claude
-v
devenv-acme-codex:/home/dev/.codex
-v
devenv-acme-pi:/home/dev/.pi
-v
devenv-acme-shellenv:/home/dev/.devenv
-v
devenv-acme-tmux:/home/dev/.config/tmux
--restart
unless-stopped
${IMAGE}"
check_eq "up acme argv == canonical (parity with devenv-wiz)" "${expected_up}" "$(cat "${CAP}")"

# --- 2. optional --mount appends a resolved read-write bind ------------------
md="${SB}/proj"; mkdir -p "${md}"
absmd="$(cd "${md}" && pwd -P)"
run_devenv up acme --mount "${md}"
if grep -qxF "${absmd}:/workspace/proj" "${CAP}"; then ok; else bad "--mount default target /workspace/<basename>"; fi
# no --mount => no extra -v beyond the 6 standard volumes
run_devenv up acme
nv="$(grep -cxF -- '-v' "${CAP}")"
check_eq "no --mount => exactly 6 -v flags" "6" "${nv}"

# --- 3. --mount rejects a non-existent host dir -----------------------------
if run_devenv up acme --mount "${SB}/does-not-exist"; then bad "--mount missing dir should exit nonzero"; else ok; fi
# --mount with no argument errors
if run_devenv up acme --mount; then bad "--mount with no arg should exit nonzero"; else ok; fi
# unexpected extra positional errors
if run_devenv up acme extra; then bad "extra positional should exit nonzero"; else ok; fi

# --- 4. --purge removes all 6 volumes; plain down removes none --------------
run_devenv down acme --purge
check_eq "down --purge removes 6 volumes" "6" "$(grep -c '^VOLRM ' "${CAP}")"
run_devenv down acme
check_eq "down (no --purge) removes 0 volumes" "0" "$(grep -c '^VOLRM ' "${CAP}" || true)"

# --- 5. completions subcommand (bash tool) ----------------------------------
if diff <("${DEVENV}" completions bash) "${REPO_ROOT}/completions/devenv.bash" >/dev/null 2>&1; then
    ok
else
    bad "completions bash prints the checked-in script verbatim"
fi
if "${DEVENV}" completions bogus >/dev/null 2>&1; then bad "completions bogus should exit nonzero"; else ok; fi
if "${DEVENV}" completions >/dev/null 2>&1; then bad "completions (missing arg) should exit nonzero"; else ok; fi

# --- 6. symlink path resolution: devenv on PATH still finds the repo ---------
ln -s "${DEVENV}" "${SB}/devenv-link"
if PATH="${SB}:${PATH}" "${SB}/devenv-link" completions zsh >/dev/null 2>&1; then ok; else bad "symlinked devenv resolves REPO_ROOT for completions"; fi

note ""
note "devenv bash tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
