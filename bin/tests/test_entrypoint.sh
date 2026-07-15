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
reset_ssh() { rm -rf "${HOMEDIR}/.ssh"; rm -rf "${INJECTDIR:?}"/*; TEST_ENV_AUTHKEYS=""; TEST_ENV_HKB64=""; TEST_PUSH_RUNTIME=""; TEST_APIKEY_RUNTIME=""; }
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
    export PATH="${STUB}:${PATH}"
    unset AGENT_CONTAINER_TMUX_WINDOWS
    [[ -n "${TEST_ENV_AUTHKEYS}" ]] && export SSH_AUTHORIZED_KEYS="${TEST_ENV_AUTHKEYS}" || unset SSH_AUTHORIZED_KEYS
    [[ -n "${TEST_ENV_HKB64}" ]] && export SSH_HOST_ED25519_KEY_B64="${TEST_ENV_HKB64}" || unset SSH_HOST_ED25519_KEY_B64
    [[ -n "${TEST_PUSH_RUNTIME}" ]] && export AGENT_CONTAINER_PUSH_RUNTIME="${TEST_PUSH_RUNTIME}" || unset AGENT_CONTAINER_PUSH_RUNTIME
    [[ -n "${TEST_APIKEY_RUNTIME}" ]] && export AGENT_CONTAINER_APIKEY_RUNTIME="${TEST_APIKEY_RUNTIME}" || unset AGENT_CONTAINER_APIKEY_RUNTIME
    # A leaked provider key env must never steer the US2 file-injection tests.
    unset ANTHROPIC_API_KEY OPENAI_API_KEY
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

# A known ed25519 keypair for the injection cases.
KNOWN="${SB}/known_hostkey"
ssh-keygen -q -t ed25519 -f "${KNOWN}" -N '' <<<y >/dev/null 2>&1
KNOWN_FP="$(fp "${KNOWN}.pub")"

# 7c. env(B64) install: the given private key becomes the host identity.
reset_session; reset_ssh
TEST_ENV_HKB64="$(base64 < "${KNOWN}" | tr -d '\n')"
run_entrypoint __unset__
check_eq "ssh: SSH_HOST_ED25519_KEY_B64 installs the given key" "${KNOWN_FP}" "$(fp "${HK}.pub")"
if log_has 'from SSH_HOST_ED25519_KEY_B64'; then ok; else bad "ssh: env-B64 install log fires"; fi

# 7d. bind-mount takes precedence over env(B64).
reset_session; reset_ssh
cp "${KNOWN}" "${INJECTDIR}/ssh_host_ed25519_key"
OTHER="${SB}/other_hostkey"; ssh-keygen -q -t ed25519 -f "${OTHER}" -N '' <<<y >/dev/null 2>&1
TEST_ENV_HKB64="$(base64 < "${OTHER}" | tr -d '\n')"   # must be IGNORED: bind-mount wins
run_entrypoint __unset__
check_eq "ssh: bind-mounted host key wins over env" "${KNOWN_FP}" "$(fp "${HK}.pub")"
if log_has 'installing bind-mounted SSH host key'; then ok; else bad "ssh: bind-mount install log fires"; fi

# 7e. authorized_keys: deduped union of the persisted file + the env source.
reset_session; reset_ssh
PUB1="ssh-ed25519 AAAAKEY1 laptop"; PUB2="ssh-ed25519 AAAAKEY2 desktop"
mkdir -p "${HOMEDIR}/.ssh"; printf '%s\n' "${PUB1}" > "${AK}"      # pre-existing persisted key
TEST_ENV_AUTHKEYS="$(printf '%s\n%s\n%s' "${PUB1}" "${PUB1}" "${PUB2}")"  # dup PUB1 + new PUB2
run_entrypoint __unset__
check_eq "ssh: authorized_keys deduped union has 2 keys" "2" "$(grep -c . "${AK}")"
if grep -qxF "${PUB1}" "${AK}" && grep -qxF "${PUB2}" "${AK}"; then ok; else bad "ssh: both unique keys present"; fi

# --- 8. Outbound SSH push key (Feature 003 US1) ------------------------------
# The push key is injected via INJECT_DIR, delivered EPHEMERALLY: copied 0600 to
# an ephemeral runtime dir (never the ~/.ssh volume, FR-012), git's core.sshCommand
# points at it with IdentitiesOnly, and the inbound host-key path is untouched
# (SC-008).
reset_session; reset_ssh
PUSHRT="${SB}/pushrt"; rm -rf "${PUSHRT}"; TEST_PUSH_RUNTIME="${PUSHRT}"
PKSRC="${SB}/agent_push_key"; ssh-keygen -q -t ed25519 -f "${PKSRC}" -N '' <<<y >/dev/null 2>&1
cp "${PKSRC}" "${INJECTDIR}/push_ed25519_key"
printf 'github.com ssh-ed25519 AAAAKH\n' > "${INJECTDIR}/known_hosts"
run_entrypoint __unset__
# core.sshCommand configured with the ephemeral key + IdentitiesOnly (no prompt)
if git_has 'core.sshCommand'; then ok; else bad "push: core.sshCommand configured"; fi
if git_has "IdentitiesOnly=yes"; then ok; else bad "push: IdentitiesOnly set"; fi
if git_has "${PUSHRT}/push_key"; then ok; else bad "push: sshCommand points at the ephemeral key"; fi
# the ephemeral key exists 0600 in the runtime dir, byte-identical to the source
check_eq "push: ephemeral key mode 0600" "600" "$(stat -c '%a' "${PUSHRT}/push_key" 2>/dev/null || stat -f '%Lp' "${PUSHRT}/push_key")"
if cmp -s "${PKSRC}" "${PUSHRT}/push_key"; then ok; else bad "push: ephemeral key matches source"; fi
# FR-012: the push key is NOT written onto the persisted ~/.ssh volume
if [[ ! -e "${HOMEDIR}/.ssh/push_ed25519_key" && ! -e "${HOMEDIR}/.ssh/push_key" ]]; then ok; else bad "push: key must NOT land on the ~/.ssh volume"; fi
# SC-008: the inbound host key still lives on its own path, untouched/unconflated
if [[ -f "${HK}" ]]; then ok; else bad "push: inbound host key path untouched"; fi
if ! cmp -s "${PUSHRT}/push_key" "${HK}"; then ok; else bad "push: push key and host key are distinct"; fi

# 8b. no push key injected -> no core.sshCommand (HTTPS path is unaffected)
reset_session; reset_ssh; PUSHRT2="${SB}/pushrt2"; rm -rf "${PUSHRT2}"; TEST_PUSH_RUNTIME="${PUSHRT2}"
run_entrypoint __unset__
if git_has 'core.sshCommand'; then bad "push: no key -> core.sshCommand must NOT be set"; else ok; fi

# --- 9. Model/API credentials (Feature 003 US2) ------------------------------
# Provider keys are injected as FILES under ${INJECT_DIR}/apikeys/<provider>,
# delivered EPHEMERALLY (H1/FR-012): Claude gets an apiKeyHelper that CATS the
# injected key (the key value never lands on the ~/.claude volume); Codex/pi get
# their homes REDIRECTED to an ephemeral dir so nothing they write hits the
# -codex/-pi volume. Absent injected keys -> no wiring at all.
CLAUDE_SETTINGS="${HOMEDIR}/.claude/settings.json"
CLAUDE_HELPER="${HOMEDIR}/.claude/apikey-helper.sh"

reset_session; reset_ssh
APIRT="${SB}/apirt"; rm -rf "${APIRT}"; TEST_APIKEY_RUNTIME="${APIRT}"
rm -rf "${HOMEDIR}/.claude" "${HOMEDIR}/.codex" "${HOMEDIR}/.pi"
mkdir -p "${INJECTDIR}/apikeys"
printf 'sk-ant-SECRETVALUE\n' > "${INJECTDIR}/apikeys/anthropic"
printf 'sk-oai-SECRETVALUE\n'  > "${INJECTDIR}/apikeys/openai"
run_entrypoint __unset__

# Claude: settings.json carries an apiKeyHelper pointing at a helper script that
# cats the EPHEMERAL injected key — never the key value itself.
if [[ -f "${CLAUDE_SETTINGS}" ]] && grep -qF 'apiKeyHelper' "${CLAUDE_SETTINGS}"; then ok; else bad "apikey: Claude settings.json gets apiKeyHelper"; fi
if [[ -x "${CLAUDE_HELPER}" ]] && grep -qF "${INJECTDIR}/apikeys/anthropic" "${CLAUDE_HELPER}"; then ok; else bad "apikey: helper cats the injected anthropic path"; fi
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
