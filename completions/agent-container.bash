# bash completion for `agent-container` (bin/agent-container).
#
# Install (interactive):   source /path/to/completions/agent-container.bash
# Install (system-wide):   copy to a bash-completion dir (see README "Shell completions").
#
# Completion keys off the command NAME, so `agent-container` must be on PATH
# (symlink bin/agent-container into ~/.local/bin). Works with or without the
# bash-completion package loaded (graceful fallback below).
#
# Container names are sourced directly in-shell — agent-container/uv is NEVER spun
# up on TAB. Candidate names come from:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/agent-container/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and NEVER executed/sourced. Candidates are matched against the
# current word manually (never via `compgen -W`, which re-expands words and
# would execute a `$(...)`/backtick embedded in a hostile name).

# State-only names (local containers): safe source for down/logs/purge.
__agent_container_names_local() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-container"
    local f base
    [[ -d "${state_dir}" ]] || return 0
    # State is namespaced per host (<state>/<host>/<name>.port); also read any
    # legacy flat files (<state>/<name>.port) that predate the migration. Dedup
    # so the same name on two hosts lists once.
    for f in "${state_dir}"/*.port "${state_dir}"/*/*.port; do
        [[ -e "${f}" ]] || continue
        base="${f##*/}"
        printf '%s\n' "${base%.port}"
    done | sort -u
}

# hosts.conf-derived names (remote targets): only meaningful for attach.
__agent_container_names_hosts() {
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/agent-container"
    local hosts="${config_dir}/hosts.conf"
    local line key
    [[ -f "${hosts}" ]] || return 0
    # KEY=VALUE parse, builtins only; the file is NEVER sourced.
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"          # ltrim
        [[ -z "${line}" || "${line:0:1}" == "#" ]] && continue
        line="${line#export }"
        line="${line#"${line%%[![:space:]]*}"}"          # ltrim again
        key="${line%%=*}"
        key="${key%"${key##*[![:space:]]}"}"             # rtrim
        case "${key}" in
            *_HOST) ;;
            *) continue ;;
        esac
        key="${key%_HOST}"
        key="${key//_/-}"                                 # inverse of name_to_key
        printf '%s\n' "${key}" | tr '[:upper:]' '[:lower:]'
    done < "${hosts}"
}

# Union (local + remote), de-duplicated: used by up/attach.
__agent_container_names() {
    { __agent_container_names_local; __agent_container_names_hosts; } | LC_ALL=C sort -u
}

# Append names emitted by $1 that prefix-match $cur to COMPREPLY, WITHOUT the
# word re-expansion `compgen -W` performs (which would run command
# substitutions embedded in a hostile name). $cur is set by the caller.
__agent_container_add_names() {
    local n
    while IFS= read -r n; do
        [[ -n "${n}" && "${n}" == "${cur}"* ]] && COMPREPLY+=("${n}")
    done < <("$1")
}

_agent_container_filedir() {
    local kind="${1:-}"  # 'd' => directories only, else files
    if declare -F _filedir >/dev/null 2>&1; then
        _filedir ${kind:+"-${kind}"}
    else
        local IFS=$'\n'
        COMPREPLY=( $(compgen ${kind:+-${kind}} -- "${cur}") )
    fi
}

# Feature 010 FR-013 / FR-002: the supported-agent list. Kept as ONE assignment
# so the hermetic agreement test can parse it and fail if it drifts from AGENTS
# in bin/agent-container (the canonical source).
_agent_container_agents="claude codex pi opencode"

_agent_container() {
    local cur prev words cword
    if declare -F _init_completion >/dev/null 2>&1; then
        _init_completion || return
    else
        COMPREPLY=()
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]:-}"
        words=("${COMP_WORDS[@]}")
        cword="${COMP_CWORD}"
    fi

    # Top-level subcommands plus the two standalone options.
    local subcommands="build host up redeploy stop start keys down purge wipe list attach logs plan apply status destroy menu completions --self-test --help"

    # The subcommand is the first non-option word after `agent-container`.
    local sub="" i
    for (( i = 1; i < cword; i++ )); do
        case "${words[i]}" in
            -*) ;;
            *) sub="${words[i]}"; break ;;
        esac
    done

    if [[ -z "${sub}" ]]; then
        COMPREPLY=( $(compgen -W "${subcommands}" -- "${cur}") )
        return 0
    fi

    COMPREPLY=()
    case "${sub}" in
        up|redeploy)
            if [[ "${prev}" == "--agent" ]]; then
                COMPREPLY=( $(compgen -W "${_agent_container_agents}" -- "${cur}") )
                return 0
            fi
            if [[ "${prev}" == "--mode" ]]; then
                COMPREPLY=( $(compgen -W "interactive headless" -- "${cur}") )
                return 0
            fi
            if [[ "${prev}" == "--workspace" ]]; then
                COMPREPLY=( $(compgen -W "persistent bind ephemeral" -- "${cur}") )
                return 0
            fi
            if [[ "${prev}" == "--mount" ]]; then
                _agent_container_filedir d       # --mount takes a directory
                return 0
            fi
            if [[ "${prev}" == "--env-file" || "${prev}" == "--host-key" || "${prev}" == "--authorized-key" ]]; then
                _agent_container_filedir          # these take a file path
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--host --mount --env-file --host-key --authorized-key --agent --mode --workspace" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names       # arbitrary name; union is fine
            ;;
        host)
            # `host add|ls` — sub-subcommand then flags.
            if [[ "${prev}" == "host" ]]; then
                COMPREPLY=( $(compgen -W "add ls" -- "${cur}") )
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--driver --docker-context --connection --address --default --json" -- "${cur}") )
            fi
            ;;
        keys)
            if [[ "${prev}" == "--host-key" || "${prev}" == "--authorized-key" ]]; then
                _agent_container_filedir          # both take a file path
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--host-key --authorized-key" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names_local # running container; local only
            ;;
        down)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--host --purge -y --yes" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names_local # local runtime only
            ;;
        purge)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-y --yes" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names_local # local runtime only
            ;;
        list)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--json" -- "${cur}") )
            fi
            ;;
        attach)
            # --user/--host/--window take a value we don't complete; suppress name fallback.
            if [[ "${prev}" == "--user" || "${prev}" == "--host" || "${prev}" == "--window" || "${prev}" == "-w" ]]; then
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--local --remote --user --host --window -w" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names       # local + remote hosts.conf
            ;;
        logs)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--no-follow" -- "${cur}") )
                return 0
            fi
            __agent_container_add_names __agent_container_names_local # local runtime only
            ;;
        completions)
            COMPREPLY=( $(compgen -W "bash zsh" -- "${cur}") )
            ;;
        build)
            # build [TAG] [--context DIR]. --context takes a directory (repo checkout).
            if [[ "${prev}" == "--context" ]]; then
                COMPREPLY=( $(compgen -d -- "${cur}") )
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--context" -- "${cur}") )
                return 0
            fi
            : # free-form tag otherwise
            ;;
        menu)
            : # menu takes nothing.
            ;;
    esac
}

complete -F _agent_container agent-container
