#!/usr/bin/env bash
# Shell-based tests for the bash completion scripts (completions/*.bash).
#
# Run:  bin/tests/test_completions.sh        (needs only bash)
#
# Sources each completion in a sandboxed HOME/XDG with fixture *.port and
# hosts.conf files, drives the completion functions with synthetic
# COMP_WORDS/COMP_CWORD, and asserts the expected candidate sets. No docker/
# podman/uv is involved. Exits non-zero on the first failure.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail=0
pass=0

note() { printf '%s\n' "$*" >&2; }

# assert_has <label> <needle> -- COMPREPLY...
assert_has() {
    local label="$1" needle="$2"; shift 2
    local w found=0
    for w in "$@"; do [[ "${w}" == "${needle}" ]] && found=1 && break; done
    if [[ "${found}" -eq 1 ]]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        note "FAIL: ${label}: expected candidate '${needle}' in: [$*]"
    fi
}

# assert_lacks <label> <needle> -- COMPREPLY...
assert_lacks() {
    local label="$1" needle="$2"; shift 2
    local w
    for w in "$@"; do
        if [[ "${w}" == "${needle}" ]]; then
            fail=$((fail + 1))
            note "FAIL: ${label}: '${needle}' should NOT be offered, got: [$*]"
            return
        fi
    done
    pass=$((pass + 1))
}

# Build a throwaway XDG sandbox with two running-state files and a hosts.conf
# that yields names 'vps' and 'my-box'. Union with state => acme blog my-box vps.
setup_sandbox() {
    SANDBOX="$(mktemp -d)"
    export XDG_STATE_HOME="${SANDBOX}/state"
    export XDG_CONFIG_HOME="${SANDBOX}/config"
    mkdir -p "${XDG_STATE_HOME}/devenv" "${XDG_CONFIG_HOME}/devenv"
    printf '2206\n' > "${XDG_STATE_HOME}/devenv/acme.port"
    printf '2220\n' > "${XDG_STATE_HOME}/devenv/blog.port"
    cat > "${XDG_CONFIG_HOME}/devenv/hosts.conf" <<'EOF'
# sample hosts
VPS_HOST=vps.example.com
VPS_PORT=2222
export MY_BOX_HOST=box.example.com   # trailing comment
MY_BOX_PORT=2200
EOF
}
teardown_sandbox() { rm -rf "${SANDBOX}"; }

# run_comp <completion-func> <word0> <word1> ... ; result in COMPREPLY.
run_comp() {
    local func="$1"; shift
    COMP_WORDS=("$@")
    COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))
    COMP_LINE="${*}"
    COMP_POINT=${#COMP_LINE}
    COMPREPLY=()
    "${func}" 2>/dev/null || true
}

test_tool() {
    local tool="$1" func="$2" names_func="$3" script="${REPO_ROOT}/completions/$1.bash"
    note "--- ${tool} (${script}) ---"
    # shellcheck disable=SC1090
    source "${script}"

    # 1) name gathering: state ∪ hosts, deduped/sorted
    local got; got="$("${names_func}")"
    for n in acme blog my-box vps; do
        assert_has "${tool}:names" "${n}" ${got}
    done

    # 2) bare subcommand position offers the subcommands
    run_comp "${func}" "${tool}" ""
    assert_has "${tool}:subcmd" "up" "${COMPREPLY[@]}"
    assert_has "${tool}:subcmd" "attach" "${COMPREPLY[@]}"

    # 3) 'up <TAB>' completes container names
    run_comp "${func}" "${tool}" "up" ""
    assert_has "${tool}:up-name" "acme" "${COMPREPLY[@]}"
    assert_has "${tool}:up-name" "my-box" "${COMPREPLY[@]}"

    # 4) 'up --<TAB>' completes flags (--mount), not names
    run_comp "${func}" "${tool}" "up" "--"
    assert_has  "${tool}:up-flag" "--mount" "${COMPREPLY[@]}"
    assert_lacks "${tool}:up-flag" "acme"   "${COMPREPLY[@]}"

    # 5) 'attach <TAB>' completes container names
    run_comp "${func}" "${tool}" "attach" ""
    assert_has "${tool}:attach-name" "blog" "${COMPREPLY[@]}"
    assert_has "${tool}:attach-name" "vps"  "${COMPREPLY[@]}"
}

setup_sandbox
trap teardown_sandbox EXIT

test_tool devenv     _devenv     __devenv_names
test_tool devenv-wiz _devenv_wiz __devenv_wiz_names

note ""
note "completion tests: ${pass} passed, ${fail} failed"
[[ "${fail}" -eq 0 ]]
