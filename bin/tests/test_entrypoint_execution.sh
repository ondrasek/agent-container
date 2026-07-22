#!/usr/bin/env bash
# Feature 004 entrypoint behaviors, exercised against STUBBED tmux/sshd/git/agent
# binaries — no container, nothing privileged (the entrypoint is fully rootless).
#
# Run:  bin/tests/test_entrypoint_execution.sh
#
# Covers:
#   US1 (T009)  interactive mode launches the primary agent in a dedicated tmux
#               window, seeded with the injected task; NO agent is launched when
#               AGENT_CONTAINER_AGENT is unset (pre-004 bare-shell default).
#   US3 (T015)  headless mode runs the agent's non-interactive form as PID 1's
#               workload and the container EXITS WITH THE AGENT'S CODE; sshd/tmux
#               are NOT started.
#   US4 (T020)  clone-on-start: HTTPS clones via git; an SSH URL with NO push key
#               dies fast (FR-014); a populated /workspace is not re-cloned.
#
# Mechanics: tmux is a dispatcher recording new-session/new-window/select-window
# and modelling has-session + list-windows; sshd/tail are recorder/immediate-exit
# stubs; git models config set/get of core.sshCommand + records `clone` (creating
# a .git so idempotency is testable); claude/codex/pi are recorder stubs that exit
# with a chosen code (headless exit-code propagation). AGENT_CONTAINER_* hooks
# redirect HOME, the inject dir, and the workspace into tmpdirs.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRY="${REPO_ROOT}/entrypoint.sh"

pass=0
fail=0
note() { printf '%s\n' "$*" >&2; }
check_eq() {
    if [[ "$2" == "$3" ]]; then pass=$((pass + 1)); else
        fail=$((fail + 1)); note "FAIL: $1"; note "  expected: [$2]"; note "  actual:   [$3]"
    fi
}
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); note "FAIL: $1"; }

SB="$(mktemp -d)"
trap 'rm -rf "${SB}"' EXIT
STUB="${SB}/stub"; mkdir -p "${STUB}"
CAP="${SB}/capture"
GITCAP="${SB}/gitcapture"
SSHDCAP="${SB}/sshdcapture"
AGENTCAP="${SB}/agentcapture"
LOG="${SB}/log"
STATE="${SB}/stubstate"; mkdir -p "${STATE}"
HOMEDIR="${SB}/home"; mkdir -p "${HOMEDIR}"
WORK="${SB}/work"; mkdir -p "${WORK}"
INJECTDIR="${SB}/inject"; mkdir -p "${INJECTDIR}"
WORKSPACE="${SB}/workspace"; mkdir -p "${WORKSPACE}"

cap_has()   { grep -qF "$1" "${CAP}"; }
git_has()   { grep -qF "$1" "${GITCAP}"; }
agent_has() { grep -qF "$1" "${AGENTCAP}"; }
sshd_ran()  { [[ -s "${SSHDCAP}" ]]; }
cap_count() { grep -c "$1" "${CAP}" 2>/dev/null || true; }

# sshd recorder.
cat > "${STUB}/sshd" <<'EOF'
#!/usr/bin/env bash
printf 'sshd %s\n' "$*" >> "${AGENT_CONTAINER_SSHD_CAPTURE}"
exit 0
EOF
chmod +x "${STUB}/sshd"

# tail: return immediately so PID-1 `tail -f /dev/null; wait` unblocks.
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/tail"
chmod +x "${STUB}/tail"

# git: model config set/get of core.sshCommand + record clone (create a .git so a
# re-run's idempotency guard sees a working copy).
cat > "${STUB}/git" <<'EOF'
#!/usr/bin/env bash
printf 'git %s\n' "$*" >> "${AGENT_CONTAINER_GIT_CAPTURE}"
sc_state="${AGENT_CONTAINER_STUB_STATE}/sshcommand"
if [[ "$1" == "config" ]]; then
    if [[ "$*" == *"--get core.sshCommand"* ]]; then
        [[ -f "${sc_state}" ]] && { cat "${sc_state}"; exit 0; } || exit 1
    fi
    if [[ "$*" == *"core.sshCommand"* ]]; then
        # last arg is the value
        for a in "$@"; do :; done; printf '%s' "${a}" > "${sc_state}"; exit 0
    fi
    exit 0
fi
if [[ "$1" == "clone" ]]; then
    dest="${@: -1}"; mkdir -p "${dest}/.git"; exit 0
fi
exit 0
EOF
chmod +x "${STUB}/git"

# tmux dispatcher: records argv; models has-session + list-windows via state.
cat > "${STUB}/tmux" <<'EOF'
#!/usr/bin/env bash
sub="$1"; shift
wl="${AGENT_CONTAINER_STUB_STATE}/windows"
case "${sub}" in
    has-session) [[ -f "${AGENT_CONTAINER_STUB_STATE}/exists" ]] && exit 0 || exit 1 ;;
    list-windows) [[ -f "${wl}" ]] && cat "${wl}"; exit 0 ;;
    new-session)
        : > "${AGENT_CONTAINER_STUB_STATE}/exists"
        printf 'new-session %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"
        name=""; for ((i=1;i<=$#;i++)); do [[ "${!i}" == "-n" ]] && { j=$((i+1)); name="${!j}"; }; done
        [[ -n "${name}" ]] && printf '%s\n' "${name}" >> "${wl}"
        for a in "$@"; do [[ "${a}" == "-P" ]] && { printf '@0\n'; break; }; done
        exit 0 ;;
    new-window)
        printf 'new-window %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"
        name=""; for ((i=1;i<=$#;i++)); do [[ "${!i}" == "-n" ]] && { j=$((i+1)); name="${!j}"; }; done
        [[ -n "${name}" ]] && printf '%s\n' "${name}" >> "${wl}"
        exit 0 ;;
    select-window) printf 'select-window %s\n' "$*" >> "${AGENT_CONTAINER_CAPTURE}"; exit 0 ;;
    *) exit 0 ;;
esac
EOF
chmod +x "${STUB}/tmux"

# Agent recorder stubs. Exit code is read from AGENT_CONTAINER_STUB_STATE/agentrc
# (default 0) so the headless exit-code test can force a non-zero result.
for a in claude codex pi; do
cat > "${STUB}/${a}" <<EOF
#!/usr/bin/env bash
printf '${a} %s\n' "\$*" >> "\${AGENT_CONTAINER_AGENT_CAPTURE}"
exit "\$(cat "\${AGENT_CONTAINER_STUB_STATE}/agentrc" 2>/dev/null || echo 0)"
EOF
chmod +x "${STUB}/${a}"
done

reset() {
    rm -f "${STATE}/exists" "${STATE}/windows" "${STATE}/sshcommand" "${STATE}/agentrc"
    # Fully recreate INJECTDIR/WORKSPACE so leftover DOTFILES (e.g. a .git the clone
    # stub creates) never leak between cases — `rm -rf DIR/*` misses dotfiles.
    rm -rf "${INJECTDIR:?}" "${WORKSPACE:?}"; mkdir -p "${INJECTDIR}" "${WORKSPACE}"
    : > "${CAP}"; : > "${GITCAP}"; : > "${SSHDCAP}"; : > "${AGENTCAP}"; : > "${LOG}"
}

# run_entry: run the entrypoint with the given AGENT_CONTAINER_* execution env.
# Extra `KEY=VALUE` args are exported for the run. Returns the entrypoint exit code.
run_entry() {
    (
        cd "${WORK}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
        export AGENT_CONTAINER_CAPTURE="${CAP}" AGENT_CONTAINER_STUB_STATE="${STATE}"
        export AGENT_CONTAINER_GIT_CAPTURE="${GITCAP}" AGENT_CONTAINER_SSHD_CAPTURE="${SSHDCAP}"
        export AGENT_CONTAINER_AGENT_CAPTURE="${AGENTCAP}"
        export AGENT_CONTAINER_SSHD="${STUB}/sshd" AGENT_CONTAINER_INJECT_DIR="${INJECTDIR}"
        export AGENT_CONTAINER_WORKSPACE="${WORKSPACE}"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS ANTHROPIC_API_KEY OPENAI_API_KEY
        unset AGENT_CONTAINER_MODE AGENT_CONTAINER_AGENT AGENT_CONTAINER_CLONE_URL
        for kv in "$@"; do export "${kv?}"; done
        bash "${ENTRY}" >/dev/null 2>"${LOG}"
    )
}

# --- US1: interactive agent launch, seeded with the task ---------------------
reset
printf 'fix the failing test\n' > "${INJECTDIR}/task"
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
if cap_has 'new-window -t main -n claude'; then ok; else bad "US1: agent window 'claude' created"; fi
if cap_has "cat ${INJECTDIR}/task"; then ok; else bad "US1: agent window seeded with the injected task"; fi
if cap_has 'select-window -t main:claude'; then ok; else bad "US1: attach lands on the agent window"; fi
if sshd_ran; then ok; else bad "US1: sshd started (interactive keeps the session)"; fi

# --- US1: no agent configured -> bare shells, no agent window (backward compat)
reset
run_entry AGENT_CONTAINER_MODE=interactive
check_eq "US1: no agent window when AGENT_CONTAINER_AGENT unset" "0" "$(cap_count 'new-window -t main -n claude')"
if sshd_ran; then ok; else bad "US1: sshd still started with no agent"; fi

# --- US1: interactive without a task launches the bare agent -----------------
reset
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=codex
if cap_has 'new-window -t main -n codex'; then ok; else bad "US1: codex window created"; fi
if cap_has 'cat '; then bad "US1: no task -> window must not cat a task file"; else ok; fi

# --- US3: headless runs the agent as PID 1 and exits with its code -----------
reset
printf 'run the tests\n' > "${INJECTDIR}/task"
printf '7\n' > "${STATE}/agentrc"   # agent (task) fails with code 7
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
rc=$?
check_eq "US3: container exits with the agent's exit code (FR-002/SC-004)" "7" "${rc}"
if agent_has 'claude -p run the tests'; then ok; else bad "US3: headless claude invoked with -p <task>"; fi
if sshd_ran; then bad "US3: sshd must NOT run in headless mode"; else ok; fi
check_eq "US3: no tmux session in headless mode" "0" "$(cap_count 'new-session')"

# --- US3: headless success exits 0 -------------------------------------------
reset
printf 'noop\n' > "${INJECTDIR}/task"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=codex
check_eq "US3: headless success exit code" "0" "$?"
if agent_has 'codex exec noop'; then ok; else bad "US3: headless codex invoked with exec <task>"; fi

# --- US4: clone-on-start over HTTPS ------------------------------------------
reset
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_CLONE_URL=https://github.com/you/repo.git
if git_has 'clone https://github.com/you/repo.git'; then ok; else bad "US4: HTTPS clone-on-start invoked"; fi

# --- US4: SSH URL without a push key dies fast (FR-014) ----------------------
reset
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_CLONE_URL=git@github.com:you/repo.git
rc=$?
if [[ "${rc}" -ne 0 ]]; then ok; else bad "US4: SSH clone with no push key must die (got exit 0)"; fi
if git_has 'clone git@'; then bad "US4: must NOT clone an SSH URL without a key"; else ok; fi

# --- US4: SSH URL WITH an injected push key clones ---------------------------
reset
printf 'PRIVATE-KEY\n' > "${INJECTDIR}/push_ed25519_key"
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_CLONE_URL=git@github.com:you/repo.git
if git_has 'clone git@github.com:you/repo.git'; then ok; else bad "US4: SSH clone with push key invoked"; fi

# --- US4: idempotent — a populated /workspace is not re-cloned ---------------
reset
mkdir -p "${WORKSPACE}/.git"   # already a working copy
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_CLONE_URL=https://github.com/you/repo.git
if git_has 'clone '; then bad "US4: must skip clone when /workspace already has .git"; else ok; fi

# --- summary -----------------------------------------------------------------
note ""
note "test_entrypoint_execution.sh: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
