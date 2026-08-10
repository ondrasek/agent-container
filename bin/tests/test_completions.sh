#!/usr/bin/env bash
# Shell-based tests for the bash completion script (completions/agent-container.bash).
#
# Run:  bin/tests/test_completions.sh        (needs only bash)
#
# Sources the completion in a sandboxed HOME/XDG with fixture *.port and
# hosts.conf files, drives the completion functions with synthetic
# COMP_WORDS/COMP_CWORD, and asserts the expected candidate sets. No docker/
# podman/uv is involved. Exits non-zero on the first failure.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail=0
pass=0
# Probes that could not be EXERCISED, kept apart from ones that FAILED: a pty
# that never reached a prompt tells you nothing about the completion (T157).
skip=0

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
    export XDG_DATA_HOME="${SANDBOX}/data"
    mkdir -p "${XDG_STATE_HOME}/agent-container" "${XDG_CONFIG_HOME}/agent-container"
    printf '2206\n' > "${XDG_STATE_HOME}/agent-container/acme.port"
    printf '2220\n' > "${XDG_STATE_HOME}/agent-container/blog.port"
    # Feature 016 durable run store. 'demolished' deliberately has NO state file:
    # it is the environment that was torn down and whose records outlived it, and
    # it is the assertion that proves `runs list` completes from the record store
    # rather than from the state files (where it would be invisible).
    mkdir -p "${XDG_DATA_HOME}/agent-container/runs/local/acme" \
             "${XDG_DATA_HOME}/agent-container/runs/local/demolished"
    : > "${XDG_DATA_HOME}/agent-container/runs/local/acme/20260809T101010Z-ab12.json"
    cat > "${XDG_CONFIG_HOME}/agent-container/hosts.conf" <<'EOF'
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

# The single CLI has the full surface: subcommands, per-subcommand flags
# (including --env-file / --mount / --json / --no-follow / attach targets), and
# container-name completion sourced directly from state + hosts.conf.
test_tool() {
    local tool="agent-container" func="_agent_container" names_func="__agent_container_names"
    local script="${REPO_ROOT}/completions/agent-container.bash"
    note "--- ${tool} (${script}) ---"
    # shellcheck disable=SC1090
    source "${script}"

    # --- Feature 010 FR-013: --agent offers exactly the four supported agents.
    # Asserted by INVOKING the completion, not by reading its source — the
    # declaration is separately checked against AGENTS in test_pure_logic.py.
    run_comp "${func}" "${tool}" up box --agent ""
    for a in claude codex pi opencode; do
        assert_has "${tool}: --agent offers ${a}" "${a}" "${COMPREPLY[@]}"
    done
    assert_lacks "${tool}: --agent offers nothing extra" "gpt" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" up box --agent "op"
    assert_has "${tool}: --agent prefix-filters to opencode" "opencode" "${COMPREPLY[@]}"
    assert_lacks "${tool}: --agent prefix 'op' excludes claude" "claude" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" redeploy box --agent ""
    assert_has "${tool}: redeploy --agent offers opencode too" "opencode" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" up box --mode ""
    assert_has "${tool}: --mode offers headless" "headless" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" up box --workspace ""
    assert_has "${tool}: --workspace offers ephemeral" "ephemeral" "${COMPREPLY[@]}"
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

    # 4) 'up --<TAB>' completes flags (--mount / --env-file), not names
    run_comp "${func}" "${tool}" "up" "--"
    assert_has  "${tool}:up-flag" "--mount"    "${COMPREPLY[@]}"
    assert_has  "${tool}:up-flag" "--env-file" "${COMPREPLY[@]}"
    assert_lacks "${tool}:up-flag" "acme"      "${COMPREPLY[@]}"

    # 5) 'attach <TAB>' completes container names (local + remote union)
    run_comp "${func}" "${tool}" "attach" ""
    assert_has "${tool}:attach-name" "blog" "${COMPREPLY[@]}"
    assert_has "${tool}:attach-name" "vps"  "${COMPREPLY[@]}"

    # 6) 'completions <TAB>' offers bash/zsh
    run_comp "${func}" "${tool}" "completions" ""
    assert_has "${tool}:completions" "bash" "${COMPREPLY[@]}"
    assert_has "${tool}:completions" "zsh"  "${COMPREPLY[@]}"

    # 7) bare subcommand set includes completions + down
    run_comp "${func}" "${tool}" ""
    assert_has "${tool}:subcmd" "completions" "${COMPREPLY[@]}"
    assert_has "${tool}:subcmd" "down"        "${COMPREPLY[@]}"

    # 8) down/logs complete LOCAL names only (state), not remote hosts.conf names
    run_comp "${func}" "${tool}" "down" ""
    assert_has  "${tool}:down-local" "acme" "${COMPREPLY[@]}"
    assert_lacks "${tool}:down-local" "vps" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "logs" ""
    assert_has  "${tool}:logs-local" "blog"   "${COMPREPLY[@]}"
    assert_lacks "${tool}:logs-local" "my-box" "${COMPREPLY[@]}"

    # 9) per-subcommand flag surfaces
    run_comp "${func}" "${tool}" "down" "--"
    assert_has "${tool}:down-flag" "--purge" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "purge" "--"
    assert_has "${tool}:purge-flag" "--yes" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "list" "--"
    assert_has "${tool}:list-flag" "--json" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "logs" "--"
    assert_has "${tool}:logs-flag" "--no-follow" "${COMPREPLY[@]}"
    # --egress is the ONLY way to reach the boundary's log, where a refused
    # destination is recorded (T130). Undiscoverable, an operator debugging a
    # refusal tails the agent container and finds an empty stream instead.
    assert_has "${tool}:logs-egress" "--egress" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "attach" "--"
    assert_has "${tool}:attach-flag" "--remote" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "build" "--"
    assert_has "${tool}:build-flag" "--context" "${COMPREPLY[@]}"
    # SSH-injection flags on up + the keys subcommand.
    run_comp "${func}" "${tool}" "up" "--"
    assert_has "${tool}:up-hostkey"  "--host-key"       "${COMPREPLY[@]}"
    assert_has "${tool}:up-authkey"  "--authorized-key" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" ""
    assert_has "${tool}:subcmd-keys" "keys" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "keys" "--"
    assert_has "${tool}:keys-flag"   "--host-key"       "${COMPREPLY[@]}"
    assert_has "${tool}:keys-flag"   "--authorized-key" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "keys" ""
    assert_has "${tool}:keys-name"   "acme" "${COMPREPLY[@]}"     # local running names

    # 10) Feature 016: the `runs` group.
    run_comp "${func}" "${tool}" ""
    assert_has "${tool}:subcmd-runs" "runs" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "runs" ""
    assert_has "${tool}:runs-sub" "list" "${COMPREPLY[@]}"
    assert_has "${tool}:runs-sub" "show" "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "runs" "list" ""
    # THE point of a separate source: 'demolished' has records and no state file.
    # Completing from state would offer nothing for the environments this feature
    # exists to answer for — a completion that looks like it works and is blind to
    # every torn-down environment.
    assert_has  "${tool}:runs-env" "demolished" "${COMPREPLY[@]}"
    assert_has  "${tool}:runs-env" "acme"       "${COMPREPLY[@]}"
    assert_lacks "${tool}:runs-env" "blog"      "${COMPREPLY[@]}"   # deployed, never ran
    run_comp "${func}" "${tool}" "runs" "show" ""
    assert_has  "${tool}:runs-id" "20260809T101010Z-ab12" "${COMPREPLY[@]}"
    assert_lacks "${tool}:runs-id" "acme"                 "${COMPREPLY[@]}"
    run_comp "${func}" "${tool}" "runs" "list" "--"
    assert_has "${tool}:runs-flag" "--json" "${COMPREPLY[@]}"
    assert_has "${tool}:runs-flag" "--host" "${COMPREPLY[@]}"
    assert_has "${tool}:runs-flag" "--changed" "${COMPREPLY[@]}"
    # --changed is `runs list`-only. Offered on `show` it would complete a flag
    # that errors, which is worse than not completing it at all.
    run_comp "${func}" "${tool}" "runs" "show" "--"
    assert_lacks "${tool}:runs-show-flag" "--changed" "${COMPREPLY[@]}"
    # A --changed VALUE is a path INSIDE the recorded repository, which may not
    # exist here at all; falling through to the record completer would offer run
    # ids where a path goes.
    run_comp "${func}" "${tool}" "runs" "list" "--changed" ""
    assert_lacks "${tool}:runs-changed" "demolished" "${COMPREPLY[@]}"
    # A --host VALUE must not fall through to the record completer: offering run
    # ids where a host name goes reads as a working completion and is nonsense.
    run_comp "${func}" "${tool}" "runs" "list" "--host" ""
    assert_lacks "${tool}:runs-host" "demolished" "${COMPREPLY[@]}"
}

# COMPL-1 regression: a hostile hosts.conf key or state-file name carrying a
# $(...) payload must NEVER execute when the bash completion runs. Uses a fresh
# sandbox with relative-path payloads and runs the completer from inside it.
test_security_no_exec() {
    local tool="agent-container" func="_agent_container"
    local script="${REPO_ROOT}/completions/agent-container.bash"
    local sbx; sbx="$(mktemp -d)"
    mkdir -p "${sbx}/state/agent-container" "${sbx}/config/agent-container"
    : > "${sbx}/state/agent-container/\$(touch PWNED-state).port"
    printf '$(touch PWNED-hosts)_HOST=x\n' > "${sbx}/config/agent-container/hosts.conf"
    # Feature 016 added a THIRD name source (the durable run store), and a name
    # source that never runs the injection probe is a source nobody checked.
    mkdir -p "${sbx}/data/agent-container/runs/local/\$(touch PWNED-runs)"
    : > "${sbx}/data/agent-container/runs/local/\$(touch PWNED-runs)/\$(touch PWNED-id).json"
    (
        cd "${sbx}" || exit 0
        export XDG_STATE_HOME="${sbx}/state" XDG_CONFIG_HOME="${sbx}/config"
        export XDG_DATA_HOME="${sbx}/data"
        # shellcheck disable=SC1090
        source "${script}"
        cur=""; COMP_WORDS=("${tool}" attach ""); COMP_CWORD=2; COMPREPLY=()
        "${func}" 2>/dev/null || true
        cur=""; COMP_WORDS=("${tool}" runs list ""); COMP_CWORD=3; COMPREPLY=()
        "${func}" 2>/dev/null || true
        cur=""; COMP_WORDS=("${tool}" runs show ""); COMP_CWORD=3; COMPREPLY=()
        "${func}" 2>/dev/null || true
    )
    if [[ -e "${sbx}/PWNED-runs" || -e "${sbx}/PWNED-id" ]]; then
        fail=$((fail + 1)); note "FAIL: ${tool}: completion EXECUTED code from a hostile run record name"
    else
        pass=$((pass + 1))
    fi
    if [[ -e "${sbx}/PWNED-state" || -e "${sbx}/PWNED-hosts" ]]; then
        fail=$((fail + 1)); note "FAIL: ${tool}: completion EXECUTED code from a hostile name"
    else
        pass=$((pass + 1))
    fi
    rm -rf "${sbx}"
}

# F4: exercise the zsh name gatherers (guarded — skipped if zsh is absent).
test_zsh_names() {
    command -v zsh >/dev/null 2>&1 || { note "zsh not found; skipping zsh name tests"; return; }
    local n out script="${REPO_ROOT}/completions/agent-container.zsh"
    out="$(zsh -c "source '${script}'; local -aU names; __agent_container_gather_local; __agent_container_gather_hosts; print -l -- \$names" 2>/dev/null)"
    for n in acme blog my-box vps; do
        if printf '%s\n' "${out}" | grep -qxF "${n}"; then pass=$((pass + 1)); else fail=$((fail + 1)); note "FAIL: zsh union missing '${n}'"; fi
    done
    out="$(zsh -c "source '${script}'; local -aU names; __agent_container_gather_local; print -l -- \$names" 2>/dev/null)"
    if printf '%s\n' "${out}" | grep -qxF "acme"; then pass=$((pass + 1)); else fail=$((fail + 1)); note "FAIL: zsh local missing 'acme'"; fi
    if printf '%s\n' "${out}" | grep -qxF "vps"; then fail=$((fail + 1)); note "FAIL: zsh local should exclude remote 'vps'"; else pass=$((pass + 1)); fi
}

# oh-my-zsh plugin: simulate omz's load order (compinit, then source the plugin)
# and assert it wires PATH, registers the completion, and defines aliases.
test_omz_plugin() {
    command -v zsh >/dev/null 2>&1 || { note "zsh not found; skipping omz plugin test"; return; }
    local plugin="${REPO_ROOT}/completions/oh-my-zsh/agent-container/agent-container.plugin.zsh"
    if [[ ! -f "${plugin}" ]]; then fail=$((fail + 1)); note "FAIL: omz plugin file missing"; return; fi
    local out label empty_bin filled_bin
    empty_bin="$(mktemp -d)"                        # XDG bin WITHOUT the tool
    filled_bin="$(mktemp -d)"; : > "${filled_bin}/agent-container"  # XDG bin WITH the tool

    # Case 1: tool absent from XDG bin -> plugin falls back to repo/bin, and
    # wires the completion + aliases.
    out="$(XDG_BIN_HOME="${empty_bin}" zsh -c "
        autoload -Uz compinit && compinit -u
        source '${plugin}'
        print -r -- \"PATHHIT=\$([[ \":\$PATH:\" == *\":\${AGENT_CONTAINER_REPO}/bin:\"* ]] && echo yes || echo no)\"
        print -r -- \"COMPFUNC=\${functions[_agent-container]:+defined}\"
        print -r -- \"COMPDEF=\${_comps[agent-container]:-none}\"
        alias ae >/dev/null 2>&1 && print -r -- 'ALIAS=ok'
    " 2>/dev/null)"
    for label in "PATHHIT=yes" "COMPFUNC=defined" "COMPDEF=_agent-container" "ALIAS=ok"; do
        if printf '%s\n' "${out}" | grep -qxF "${label}"; then
            pass=$((pass + 1))
        else
            fail=$((fail + 1)); note "FAIL: omz(no-xdg) missing '${label}' (got: ${out//$'\n'/ | })"
        fi
    done

    # Case 2: tool present in XDG_BIN_HOME -> plugin prefers it over repo/bin.
    out="$(XDG_BIN_HOME="${filled_bin}" zsh -c "
        source '${plugin}'
        print -r -- \"XDGHIT=\$([[ \":\$PATH:\" == *\":${filled_bin}:\"* ]] && echo yes || echo no)\"
    " 2>/dev/null)"
    if printf '%s\n' "${out}" | grep -qxF "XDGHIT=yes"; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1)); note "FAIL: omz did not prefer XDG_BIN_HOME (got: ${out})"
    fi

    rm -rf "${empty_bin}" "${filled_bin}"
}

setup_sandbox
trap teardown_sandbox EXIT

test_tool

note "--- security: no code execution from hostile names ---"
test_security_no_exec

# --- F5: EXECUTE the zsh completion through a pty (Feature 010) --------------
# Grepping the script is not enough. A review found `--agent` completing nothing
# in zsh while the list was correctly declared AND referenced, so both the
# structural test and the reviewer's read of the diff passed. Two separate
# defects hid behind that: the list was a file-level global (empty under the
# #compdef autoload path), and the spec used "${=var}", whose split flag breaks
# ONE _arguments spec into four malformed words. Only running it catches either.
if command -v zsh >/dev/null 2>&1; then
    note "--- zsh completion, executed via pty ---"
    zsh_complete() {  # <line-to-complete> -> the completed buffer
        zsh -f -c '
            zmodload zsh/zpty 2>/dev/null || exit 0
            zpty z zsh -f
            zpty -w z "fpath=('"${REPO_ROOT}"'/completions \$fpath); autoload -Uz compinit; compinit -u"
            zpty -w z "source '"${REPO_ROOT}"'/completions/agent-container.zsh"
            zpty -w z "zstyle \":completion:*\" completer _complete; PROMPT=\"RDY>\""
            # WAIT FOR THE PROMPT, do not guess at it. This was `sleep 0.5`, which is
            # a bet that compinit finishes in half a second. Under load it does not,
            # the TAB is then delivered to a shell with no completion system loaded,
            # and the probe returns EMPTY — a hard CI gate going red while
            # completions/ is untouched (T157: observed twice immediately after the
            # container tier, green on five other runs).
            ready=""
            for i in {1..80}; do
                if zpty -r -t z chunk 2>/dev/null; then ready+="$chunk"; fi
                [[ "$ready" == *"RDY>"* ]] && break
                sleep 0.1
            done
            [[ "$ready" == *"RDY>"* ]] || { print -r -- "__HARNESS_NOT_READY__"; exit 0; }
            zpty -w -n z "'"$1"'"$'"'"'\t'"'"'
            out=""
            for i in {1..40}; do
                if zpty -r -t z chunk 2>/dev/null; then out+="$chunk"; else sleep 0.15; fi
            done
            print -r -- "$out" | tr -d "\r" | sed "s/\x1b\[[0-9;?]*[a-zA-Z]//g" | tail -1
        ' 2>/dev/null
    }
    for probe in "up:op:opencode" "up:cod:codex" "redeploy:op:opencode"; do
        verb="${probe%%:*}"; rest="${probe#*:}"; pre="${rest%%:*}"; want="${rest##*:}"
        got="$(zsh_complete "agent-container ${verb} box --agent ${pre}")"
        if [[ "${got}" == *"--agent ${want}"* ]]; then
            pass=$((pass + 1))
        elif [[ "${got}" == *"__HARNESS_NOT_READY__"* || -z "${got}" ]]; then
            # NAME THE HARNESS, NOT THE COMPLETIONS. An empty buffer means the pty
            # never reached a prompt; it says nothing about whether the completion
            # is correct, and reporting it as a completion failure sends whoever
            # reads CI into completions/ to debug a file that is working.
            skip=$((skip + 1))
            note "SKIP: zsh '${verb} --agent ${pre}<TAB>' — pty never became ready; \
completion NOT exercised (harness limitation, not a completion defect)"
        else
            fail=$((fail + 1))
            note "FAIL: zsh '${verb} --agent ${pre}<TAB>' should complete to '${want}', got: ${got}"
        fi
    done
    # Feature 016: the `runs` arm, EXECUTED. Grepping the zsh file would prove only
    # that the words are present — which is exactly what it proved for `--agent`
    # while that completion returned nothing. The second probe also exercises the
    # durable-store gatherer: 'demolished' has records and no state file, so a
    # completion reading state instead would return the prefix unchanged.
    for probe in "agent-container runs sh|runs show" \
                 "agent-container runs list demol|runs list demolished"; do
        pline="${probe%%|*}"; want="${probe#*|}"
        got="$(zsh_complete "${pline}")"
        if [[ "${got}" == *"${want}"* ]]; then
            pass=$((pass + 1))
        elif [[ "${got}" == *"__HARNESS_NOT_READY__"* || -z "${got}" ]]; then
            skip=$((skip + 1))
            note "SKIP: zsh '${pline}<TAB>' — pty never became ready; completion NOT \
exercised (harness limitation, not a completion defect)"
        else
            fail=$((fail + 1))
            note "FAIL: zsh '${pline}<TAB>' should complete to '${want}', got: ${got}"
        fi
    done
else
    note "--- zsh completion pty test SKIPPED (no zsh) ---"
fi

note "--- zsh name gatherers ---"
test_zsh_names

note "--- oh-my-zsh plugin ---"
test_omz_plugin

note ""
if [ "${skip}" -gt 0 ]; then
    note "completion tests: ${pass} passed, ${fail} failed, ${skip} not exercised (pty unavailable under load)"
else
    note "completion tests: ${pass} passed, ${fail} failed"
fi
[[ "${fail}" -eq 0 ]]
