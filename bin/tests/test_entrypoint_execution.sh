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
# Feature 016 (T012/T013/T014) rides here too, because the run record is written
# on the very exit paths this file already owns:
#   T012  a PENDING record exists WHILE the agent is still running — the only
#         reason a SIGKILLed run is recoverable at all (SC-008).
#   T013  the exit path completes it, and CANNOT change the run's exit status
#         (FR-008, C11) — asserted in both directions, since a test that only
#         checked "0 stays 0" would pass for an entrypoint that always exits 0.
#   T014  SIGTERM yields outcome `stopped`, written BEFORE the entrypoint waits
#         on the agent — so it lands inside the runtime's stop grace period even
#         when the agent itself refuses to die (research R5).
#   T042  an interactive session is a DISTINCT KIND with its own vocabulary
#         (`ended` | `stopped`, never `finished`/`failed`), no task and no exit
#         code — and `finished` is refused at the WRITE, not merely unwritten by
#         today's branches. The session's repository capture (FR-013) is asserted
#         in bin/tests/test_entrypoint_repository.sh, where the git stubs are real
#         repositories.
#
# Mechanics: tmux is a dispatcher recording new-session/new-window/select-window
# and modelling has-session + list-windows; sshd/tail are recorder/immediate-exit
# stubs; git models config set/get of core.sshCommand + records `clone` (creating
# a .git so idempotency is testable); claude/codex/pi/opencode are recorder stubs that exit
# with a chosen code (headless exit-code propagation). AGENT_CONTAINER_* hooks
# redirect HOME, the inject dir, and the workspace into tmpdirs.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRY="${REPO_ROOT}/image/entrypoint.sh"

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
# Feature 016: the run-record volume mount point, redirected out of /var/lib.
# Without this hook every case in this file would try to write the operator's
# real /var/lib/agent-container/runs — and, failing, would emit the entrypoint's
# "cannot create" diagnostic into a log that other cases grep NEGATIVELY.
RUNSDIR="${SB}/runs"; mkdir -p "${RUNSDIR}"
SNAPDIR="${SB}/runsnapshot"; mkdir -p "${SNAPDIR}"

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

# tail: return immediately so PID-1 `tail -f /dev/null; wait` unblocks — unless
# the case asked (tailblock) for a session that STAYS UP. That is what an
# interactive container actually is, and it is the only shape in which its SIGTERM
# handler can be reached at all: with the immediate-exit stub the entrypoint has
# already fallen off the end of its `wait` before any signal could arrive.
# `exec` keeps the recorded pid valid so the case can reap the sleeper.
cat > "${STUB}/tail" <<'EOF'
#!/usr/bin/env bash
_st="${AGENT_CONTAINER_STUB_STATE}"
if [[ -f "${_st}/tailblock" ]]; then
    printf '%s' "$$" > "${_st}/tailpid"
    : > "${_st}/tailready"
    exec sleep 60
fi
exit 0
EOF
chmod +x "${STUB}/tail"

# pkill recorder. The interactive shutdown handler runs `pkill -TERM -x sshd`, and
# HERMETICITY (Constitution V) is the whole reason this is stubbed: unstubbed, the
# first test to exercise that handler would signal whatever real `sshd` the
# developer happens to own — a suite that reaches outside its sandbox is a suite
# whose result depends on the machine it ran on.
printf '#!/usr/bin/env bash\nexit 0\n' > "${STUB}/pkill"
chmod +x "${STUB}/pkill"

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
    kill-server)
        # Held open on request (tmuxhold) until the case releases it. This is the
        # UNBOUNDED step of the interactive shutdown handler — research R5's whole
        # point — so holding it here is how "the record was written BEFORE it" can
        # be asserted as an ORDER rather than guessed from elapsed milliseconds.
        _st="${AGENT_CONTAINER_STUB_STATE}"
        if [[ -f "${_st}/tmuxhold" ]]; then
            : > "${_st}/tmuxholding"
            for (( i = 0; i < 600; i++ )); do
                [[ -f "${_st}/tmuxrelease" ]] && break
                sleep 0.05
            done
        fi
        exit 0 ;;
    *) exit 0 ;;
esac
EOF
chmod +x "${STUB}/tmux"

# Agent recorder stubs. Exit code is read from AGENT_CONTAINER_STUB_STATE/agentrc
# (default 0) so the headless exit-code test can force a non-zero result.
#
# Two Feature 016 hooks, both inert unless their state file exists:
#   agentsnapshot  copy the runs dir AS IT IS WHILE THE AGENT RUNS. That is the
#                  only moment at which "the record was written at START" is
#                  observable without a container to SIGKILL.
#   agentsleep     become an agent that IGNORES SIGTERM and sleeps, recording its
#                  own pid so the test can reap it. The T014 assertion is that
#                  the record is durable while such an agent is still refusing to
#                  exit — which is exactly what the stop grace period demands.
for a in claude codex pi opencode; do
cat > "${STUB}/${a}" <<EOF
#!/usr/bin/env bash
printf '${a} %s\n' "\$*" >> "\${AGENT_CONTAINER_AGENT_CAPTURE}"
_st="\${AGENT_CONTAINER_STUB_STATE}"
if [[ -f "\${_st}/agentsnapshot" ]]; then
    cp -R "\${AGENT_CONTAINER_RUNS_DIR}/." "\$(cat "\${_st}/agentsnapshot")/" 2>/dev/null
fi
if [[ -f "\${_st}/agentsleep" ]]; then
    trap '' TERM
    printf '%s' "\$\$" > "\${_st}/agentpid"
    : > "\${_st}/agentready"
    sleep "\$(cat "\${_st}/agentsleep")"
fi
exit "\$(cat "\${_st}/agentrc" 2>/dev/null || echo 0)"
EOF
chmod +x "${STUB}/${a}"
done

reset() {
    rm -f "${STATE}/exists" "${STATE}/windows" "${STATE}/sshcommand" "${STATE}/agentrc"
    rm -f "${STATE}/agentsnapshot" "${STATE}/agentsleep" "${STATE}/agentready" "${STATE}/agentpid"
    rm -f "${STATE}/tailblock" "${STATE}/tailready" "${STATE}/tailpid"
    rm -f "${STATE}/tmuxhold" "${STATE}/tmuxholding" "${STATE}/tmuxrelease"
    # Fully recreate INJECTDIR/WORKSPACE so leftover DOTFILES (e.g. a .git the clone
    # stub creates) never leak between cases — `rm -rf DIR/*` misses dotfiles.
    # The runs dirs go the same way: a record left by the previous case would let
    # a case that writes NOTHING still find a plausible-looking record.
    rm -rf "${INJECTDIR:?}" "${WORKSPACE:?}" "${RUNSDIR:?}" "${SNAPDIR:?}"
    mkdir -p "${INJECTDIR}" "${WORKSPACE}" "${RUNSDIR}" "${SNAPDIR}"
    : > "${CAP}"; : > "${GITCAP}"; : > "${SSHDCAP}"; : > "${AGENTCAP}"; : > "${LOG}"
}

# The one record this run left, or empty. Records are `<run-id>.json`; a staged
# `.<run-id>.json.<pid>.tmp` is deliberately NOT matched, so a test can tell a
# finished write from an abandoned one.
record_path() { ls -1 "${1}"/*.json 2>/dev/null | head -1; }

# record_field <dir> <field> -> the field's value; 'null' for JSON null,
# '<<none>>' when there is no record at all.
#
# PARSED, not grepped. A regex over the record would report the field this suite
# expects while the file around it was malformed — and malformed is precisely the
# failure the entrypoint's JSON escaping exists to prevent, so a reader that
# cannot notice it would be a check that passes while its subject is broken.
record_field() {
    local f; f="$(record_path "$1")"
    if [[ -z "${f}" ]]; then printf '<<none>>'; return 0; fi
    python3 - "${f}" "$2" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    rec = json.load(fh)
v = rec.get(sys.argv[2], "<<missing>>")
print("null" if v is None else v, end="")
PY
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
        export AGENT_CONTAINER_RUNS_DIR="${RUNSDIR}"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS ANTHROPIC_API_KEY OPENAI_API_KEY
        unset AGENT_CONTAINER_MODE AGENT_CONTAINER_AGENT AGENT_CONTAINER_CLONE_URL
        for kv in "$@"; do export "${kv?}"; done
        bash "${ENTRY}" >/dev/null 2>"${LOG}"
    )
}

# Same, but backgrounded and signallable. `exec` is load-bearing: without it the
# subshell — not the entrypoint — would be $!, and a SIGTERM sent to it would
# never reach the trap under test.
ENTRY_PID=""
run_entry_bg() {
    (
        cd "${WORK}" || exit 99
        export GH_TOKEN=x GIT_USER_NAME='Test User' GIT_USER_EMAIL='t@example.com'
        export HOME="${HOMEDIR}" AGENT_CONTAINER_HOME="${HOMEDIR}"
        export AGENT_CONTAINER_CAPTURE="${CAP}" AGENT_CONTAINER_STUB_STATE="${STATE}"
        export AGENT_CONTAINER_GIT_CAPTURE="${GITCAP}" AGENT_CONTAINER_SSHD_CAPTURE="${SSHDCAP}"
        export AGENT_CONTAINER_AGENT_CAPTURE="${AGENTCAP}"
        export AGENT_CONTAINER_SSHD="${STUB}/sshd" AGENT_CONTAINER_INJECT_DIR="${INJECTDIR}"
        export AGENT_CONTAINER_WORKSPACE="${WORKSPACE}"
        export AGENT_CONTAINER_RUNS_DIR="${RUNSDIR}"
        export PATH="${STUB}:${PATH}"
        unset AGENT_CONTAINER_TMUX_WINDOWS ANTHROPIC_API_KEY OPENAI_API_KEY
        unset AGENT_CONTAINER_MODE AGENT_CONTAINER_AGENT AGENT_CONTAINER_CLONE_URL
        for kv in "$@"; do export "${kv?}"; done
        exec bash "${ENTRY}" >/dev/null 2>"${LOG}"
    ) &
    ENTRY_PID=$!
}

# Poll for a condition rather than sleeping a fixed amount: a fixed sleep either
# makes the suite slow or makes it flaky, and here the elapsed time is itself an
# assertion (T014's grace-period bound).
#
# Bounded by the WALL CLOCK, not by an iteration count. Counting iterations makes
# the real deadline depend on how long the predicate takes — and this predicate
# starts a python interpreter, so an iteration-bounded "give up after 10s" was
# measured overshooting to ~20s, which let a record written far outside the stop
# grace period still satisfy the assertion that it was written.
wait_for() {
    local deadline=$1 stop
    shift
    stop=$(( $(date +%s) + deadline ))
    while :; do
        "$@" && return 0
        [[ "$(date +%s)" -lt "${stop}" ]] || return 1
        sleep 0.05
    done
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

# --- Feature 010 US1: opencode is dispatched like the other three ------------
reset
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=opencode
if cap_has 'new-window -t main -n opencode'; then ok; else bad "010: agent window 'opencode' created"; fi
if cap_has 'select-window -t main:opencode'; then ok; else bad "010: attach lands on the opencode window"; fi

# Headless uses `opencode run <task>` (the documented non-interactive form) and
# propagates the agent's exit code (FR-005, verified against the real binary).
reset
printf 'run the tests' > "${INJECTDIR}/task"
printf '7' > "${STATE}/agentrc"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=opencode
check_eq "010: headless container exits with opencode's code" "7" "$?"
if agent_has 'opencode run run the tests'; then ok; else bad "010: headless opencode invoked as 'run <task>'"; fi

# The TUI positional is a PROJECT DIRECTORY, not a message — passing the task
# there would be read as a path, so interactive opencode must launch UNSEEDED.
reset
printf 'fix the bug' > "${INJECTDIR}/task"
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=opencode
if cap_has 'new-window -t main -n opencode opencode'; then ok; else bad "010: interactive opencode launches unseeded"; fi
if cap_has 'fix the bug'; then bad "010: task must NOT be passed to opencode's TUI (read as a project path)"; else ok; fi

# --- Feature 010 FR-012: a stale image names the remedy, not exit 127 --------
# Move the stub aside (an image built before opencode landed), then restore it.
#
# PATH is pinned to the stub dir + the system dirs ONLY. run_entry exports PATH
# before applying kv args, so this override wins. It is load-bearing for
# HERMETICITY (Constitution V): a developer machine may well have the real agent
# installed (homebrew/npm land in /opt/homebrew/bin or /usr/local/bin), and
# without the pin this case would pass in CI and fail locally — the worst kind of
# environment-dependent test.
reset
mv "${STUB}/opencode" "${STUB}/.opencode.hidden"
run_entry PATH="${STUB}:/usr/bin:/bin" AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=opencode
rc=$?
mv "${STUB}/.opencode.hidden" "${STUB}/opencode"
if [[ "${rc}" -ne 0 && "${rc}" -ne 127 ]]; then ok; else bad "010: missing agent must die cleanly (got ${rc})"; fi
if grep -q 'redeploy' "${LOG}"; then ok; else bad "010: stale-image message must name 'redeploy' as the remedy (log: $(tr '\n' '|' < "${LOG}" | tail -c 300))"; fi

# --- Feature 010: an UNKNOWN agent says so, rather than blaming the image -----
# Review catch: with the preflight ordered first, AGENT_CONTAINER_AGENT=gpt
# reported "not installed in this image — run redeploy", sending the operator to
# rebuild an image that was never the problem.
reset
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=gpt
rc=$?
if [[ "${rc}" -ne 0 ]]; then ok; else bad "010: unknown agent must fail"; fi
if grep -q "unknown agent" "${LOG}"; then ok; else bad "010: unknown agent must say 'unknown agent'"; fi
if grep -q 'redeploy' "${LOG}"; then bad "010: unknown agent must NOT blame the image"; else ok; fi

# --- Feature 016 T012: the record exists BEFORE the run ends -----------------
# Snapshotted from inside the agent, so what is inspected is the file as it was
# while the run was still going. This is the property `docker kill` depends on:
# SIGKILL runs no trap, so a record written only at exit would leave nothing at
# all, and quickstart S4 names "no record" as the wrong answer that looks right.
reset
printf 'tidy the "imports"\nand push\n' > "${INJECTDIR}/task"
printf '%s' "${SNAPDIR}" > "${STATE}/agentsnapshot"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
if [[ -n "$(record_path "${SNAPDIR}")" ]]; then ok; else bad "016 T012: a record exists WHILE the agent runs (SIGKILL survivability)"; fi
check_eq "016 T012: the in-flight record is PENDING (ended_at null)" "null" "$(record_field "${SNAPDIR}" ended_at)"
check_eq "016 T012: the in-flight record has no outcome yet" "null" "$(record_field "${SNAPDIR}" outcome)"
check_eq "016 T012: kind comes from the execution mode" "headless" "$(record_field "${SNAPDIR}" kind)"
check_eq "016 T012: agent is named in the record" "claude" "$(record_field "${SNAPDIR}" agent)"
# Byte-identical to the injected task, quotes and newlines included (S12). This
# is also the only assertion that would catch a broken JSON escaper: record_field
# parses, so an unescaped quote fails here rather than being read back as prose.
check_eq "016 T012: task recorded verbatim" 'tidy the "imports"
and push' "$(record_field "${SNAPDIR}" task)"
check_eq "016 T012: environment is left for ingestion to stamp" "null" "$(record_field "${SNAPDIR}" environment)"
check_eq "016 T012: host is left for ingestion to stamp" "null" "$(record_field "${SNAPDIR}" host)"

# The record is assembled in shell from text the operator wrote, and `--task @file`
# means that text can come from a file rather than a keyboard. Command
# substitution and backticks must reach the record as CHARACTERS.
reset
printf 'run $(id) and `whoami` ${HOME}' > "${INJECTDIR}/task"
printf '%s' "${SNAPDIR}" > "${STATE}/agentsnapshot"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "016: task shell metacharacters are DATA, never evaluated" 'run $(id) and `whoami` ${HOME}' "$(record_field "${SNAPDIR}" task)"

# --- Feature 016 T013: the exit path completes it ----------------------------
reset
printf 'noop\n' > "${INJECTDIR}/task"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=codex
check_eq "016 T013: a clean headless run is 'finished'" "finished" "$(record_field "${RUNSDIR}" outcome)"
check_eq "016 T013: the completed record carries the agent's exit code" "0" "$(record_field "${RUNSDIR}" exit_code)"
if [[ "$(record_field "${RUNSDIR}" ended_at)" == "null" ]]; then bad "016 T013: ended_at must be set on completion"; else ok; fi
# The staged file is gone: a `.tmp` left behind is a slow leak in a directory
# whose entire retention story is "delete files".
if compgen -G "${RUNSDIR}/.*.tmp" >/dev/null; then bad "016 T013: a staged .tmp must not survive the write"; else ok; fi

reset
printf 'boom\n' > "${INJECTDIR}/task"
printf '7\n' > "${STATE}/agentrc"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude
check_eq "016 T013: a failing headless run is 'failed'" "failed" "$(record_field "${RUNSDIR}" outcome)"
check_eq "016 T013: the failing run's exit code is recorded" "7" "$(record_field "${RUNSDIR}" exit_code)"

# --- Feature 016 T013 / C11: a record write NEVER alters the exit status -----
# The runs dir is made uncreatable by putting a FILE where its parent must be, so
# `mkdir -p` fails the way a read-only volume or a full disk would.
#
# Asserted in BOTH directions on purpose. "0 stays 0" alone would also pass for
# an entrypoint that always exits 0 — which would be a far worse bug than the one
# under test, and invisible to a one-sided check.
reset
printf 'noop\n' > "${INJECTDIR}/task"
: > "${SB}/blocked"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_RUNS_DIR="${SB}/blocked/runs"
check_eq "016 C11: an unwritable record leaves a SUCCESS a success" "0" "$?"
if grep -q 'run record:' "${LOG}"; then ok; else bad "016 C11: a failed record write must not be silent (FR-008)"; fi

reset
printf 'boom\n' > "${INJECTDIR}/task"
printf '7\n' > "${STATE}/agentrc"
run_entry AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=claude \
          AGENT_CONTAINER_RUNS_DIR="${SB}/blocked/runs"
check_eq "016 C11: an unwritable record leaves a FAILURE a failure" "7" "$?"
rm -f "${SB}/blocked"

# --- Feature 016 T014: SIGTERM -> `stopped`, inside the grace period ---------
# The agent here IGNORES SIGTERM and sleeps. That is the case R5 is about: the
# entrypoint has one stop grace period to get the record down, and it cannot
# spend it waiting for a process that will not exit. If the record were written
# after the wait, this assertion would time out — which is the point of shaping
# the stub this way rather than letting it die promptly.
reset
printf 'sleep for a while\n' > "${INJECTDIR}/task"
printf '20' > "${STATE}/agentsleep"
run_entry_bg AGENT_CONTAINER_MODE=headless AGENT_CONTAINER_AGENT=pi
if wait_for 10 test -f "${STATE}/agentready"; then ok; else bad "016 T014: the sleeping agent stub never started"; fi
started="$(date +%s)"
kill -TERM "${ENTRY_PID}" 2>/dev/null
record_is_stopped() { [[ "$(record_field "${RUNSDIR}" outcome)" == "stopped" ]]; }
# 9s, deliberately inside docker's default 10s stop_grace_period: a record that
# needs longer than the grace period is a record SIGKILL destroys, so "arrived
# eventually" is not the property — "arrived in time" is.
if wait_for 9 record_is_stopped; then ok; else bad "016 T014: SIGTERM must produce outcome 'stopped' within the stop grace period"; fi
elapsed=$(( $(date +%s) - started ))
if [[ "${elapsed}" -lt 10 ]]; then ok; else bad "016 T014: the record took ${elapsed}s — past the stop grace period"; fi
check_eq "016 T014: a stopped run has no invented exit code" "null" "$(record_field "${RUNSDIR}" exit_code)"
if [[ "$(record_field "${RUNSDIR}" ended_at)" == "null" ]]; then bad "016 T014: a stopped record must still carry ended_at"; else ok; fi
# Reap: the stub is ignoring TERM, so the entrypoint is still in its wait.
kill -9 "$(cat "${STATE}/agentpid" 2>/dev/null)" 2>/dev/null
wait "${ENTRY_PID}" 2>/dev/null
rc=$?
if [[ "${rc}" -ne 0 ]]; then ok; else bad "016 T014: a stopped run must not report success (got ${rc})"; fi

# --- Feature 016 T042: an interactive session is recorded, with ITS vocabulary --
# `finished` and `failed` are unrepresentable for a session (FR-003, C5): it has
# no completion semantics. The stubbed `tail` returns at once, so this exercises
# the ordinary end of an interactive entrypoint.
reset
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
check_eq "016 T042: an interactive session records kind 'interactive'" "interactive" "$(record_field "${RUNSDIR}" kind)"
# The POSITIVE assertion, and it is not redundant with the C5 one below: "not
# finished and not failed" is also true of `null`, of a typo, and of no record at
# all — so on its own it would pass for a build that had stopped naming endings.
# S8 asks for exactly this word.
check_eq "016 T042: a session that simply ends is 'ended'" "ended" "$(record_field "${RUNSDIR}" outcome)"
outcome="$(record_field "${RUNSDIR}" outcome)"
if [[ "${outcome}" == "finished" || "${outcome}" == "failed" ]]; then
    bad "016 C5: an interactive session must never be '${outcome}'"
else ok; fi
check_eq "016 T042: an interactive session carries no task (FR-002)" "null" "$(record_field "${RUNSDIR}" task)"
check_eq "016 T042: an interactive session has no exit code" "null" "$(record_field "${RUNSDIR}" exit_code)"

# --- Feature 016 T042: the session's OTHER legal ending ----------------------
# `stopped` is the second and last member of the interactive vocabulary, and it
# is the one an operator actually produces — `agent-container down` SIGTERMs a
# container an operator is attached to. Exercised through a session that STAYS UP
# (tailblock), because the immediate-exit `tail` stub used above has the
# entrypoint past its `wait` before a signal could ever arrive: without this case
# the interactive shutdown handler is code no test executes.
#
# `tmux kill-server` is HELD OPEN for the duration (tmuxhold). It is the one
# unbounded step in that handler, and holding it is what makes the assertion below
# an ordering proof: with the record written first it arrives while tmux is still
# blocked, and with the two swapped it cannot arrive at all until the case
# releases — so the difference is a failure, not a few milliseconds. Timing alone
# proved nothing here, MEASURED: an entrypoint whose handler wrote no record at
# all still passed, because the EXIT trap wrote one afterwards.
reset
: > "${STATE}/tailblock"
: > "${STATE}/tmuxhold"
run_entry_bg AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
if wait_for 10 test -f "${STATE}/tailready"; then ok; else bad "016 T042: the interactive entrypoint never reached its PID-1 wait"; fi
started="$(date +%s)"
kill -TERM "${ENTRY_PID}" 2>/dev/null
# 9s, inside docker's default 10s stop grace period: SIGKILL closes that window,
# so "arrived eventually" is not the property — "arrived in time" is.
if wait_for 9 record_is_stopped; then ok; else bad "016 T042: SIGTERM on a session must produce 'stopped' within the stop grace period, BEFORE the unbounded shutdown steps"; fi
elapsed=$(( $(date +%s) - started ))
if [[ "${elapsed}" -lt 10 ]]; then ok; else bad "016 T042: the session's record took ${elapsed}s — past the stop grace period"; fi
# The hold was actually engaged. Without this the case above would pass equally
# for a stub whose hook silently did nothing, which is the same shape of vacuity
# the mutation checks below exist to rule out.
if wait_for 5 test -f "${STATE}/tmuxholding"; then ok; else bad "016 T042: the tmux hold never engaged — the ordering above proved nothing"; fi
check_eq "016 T042: a stopped session is still kind 'interactive'" "interactive" "$(record_field "${RUNSDIR}" kind)"
check_eq "016 T042: a stopped session invents no exit code" "null" "$(record_field "${RUNSDIR}" exit_code)"
if [[ "$(record_field "${RUNSDIR}" ended_at)" == "null" ]]; then bad "016 T042: a stopped session must still carry ended_at"; else ok; fi
: > "${STATE}/tmuxrelease"
kill -9 "$(cat "${STATE}/tailpid" 2>/dev/null)" 2>/dev/null
wait "${ENTRY_PID}" 2>/dev/null
# C11 on the interactive side: this handler exited 0 before Feature 016 existed
# and must still exit 0. The record is bookkeeping; it may not become the thing
# that decides what an operator's `down` reports.
check_eq "016 C11: recording a session leaves the shutdown status alone" "0" "$?"

# --- Feature 016 T042 / C5: `finished` is REFUSED AT THE WRITE ---------------
# Not merely absent from today's branches. This is the only place a real
# interactive record is ever produced — ingestion stamps and stores one verbatim,
# so the tool's validator never sees it — which makes the entrypoint the last
# line at which SC-002 can be enforced rather than hoped for.
#
# Proven by MUTATION, in both directions, because a guard nobody has watched fire
# is a guard nobody knows is wired: the first mutant asserts the refusal, the
# second neuters the guard alone and asserts that the very same mutation then
# reaches the record. Without the second, this case would also pass for a sed
# that quietly matched nothing.
MUTANT="${SB}/entrypoint-refuses.sh"
sed 's/outcome="ended"/outcome="finished"/' "${ENTRY}" > "${MUTANT}"
if cmp -s "${ENTRY}" "${MUTANT}"; then bad "016 T042: the mutation did not apply — this case would pass vacuously"; else ok; fi
reset
_real_entry="${ENTRY}"
ENTRY="${MUTANT}"
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
ENTRY="${_real_entry}"
check_eq "016 C5: an illegal outcome is refused, leaving none rather than a false one" "null" "$(record_field "${RUNSDIR}" outcome)"
if grep -q 'REFUSED' "${LOG}"; then ok; else bad "016 C11: the refusal must be said out loud, not swallowed"; fi
# Still a record, and still one an operator can read: a guard that responded by
# dropping the record would trade a mislabelled run for a vanished one.
check_eq "016 C5: the refused record is still written" "interactive" "$(record_field "${RUNSDIR}" kind)"

MUTANT_UNGUARDED="${SB}/entrypoint-unguarded.sh"
sed -e 's/outcome="ended"/outcome="finished"/' \
    -e 's/^runs_outcome_is_legal() {$/runs_outcome_is_legal() { return 0;/' \
    "${ENTRY}" > "${MUTANT_UNGUARDED}"
reset
ENTRY="${MUTANT_UNGUARDED}"
run_entry AGENT_CONTAINER_MODE=interactive AGENT_CONTAINER_AGENT=claude
ENTRY="${_real_entry}"
check_eq "016 C5: with the guard neutered the same mutation DOES reach the record" "finished" "$(record_field "${RUNSDIR}" outcome)"

# --- Feature 016: no agent, no record, and it SAYS so ------------------------
# The pre-004 bare-shell layout launches nothing, and `agent` is closed to the
# four supported names — so there is no truthful record to write. Silence here
# would leave an operator inferring the absence.
reset
run_entry AGENT_CONTAINER_MODE=interactive
if [[ -z "$(record_path "${RUNSDIR}")" ]]; then ok; else bad "016: a bare-shell session must not invent a record"; fi
if grep -q 'no run record' "${LOG}"; then ok; else bad "016: the absence of a record must be stated, not inferred"; fi

# --- summary -----------------------------------------------------------------
note ""
note "test_entrypoint_execution.sh: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
