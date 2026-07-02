# bash completion for `agent-env` (bin/agent-env).
#
# Install (interactive):   source /path/to/completions/agent-env.bash
# Install (system-wide):   copy to a bash-completion dir (see README "Shell completions").
#
# Completion keys off the command NAME, so `agent-env` must be on PATH
# (symlink bin/agent-env into ~/.local/bin). Works with or without the
# bash-completion package loaded (graceful fallback below).
#
# Container names are sourced directly in-shell — agent-env/uv is NEVER spun
# up on TAB. Candidate names come from:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/agent-env/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and NEVER executed/sourced. Candidates are matched against the
# current word manually (never via `compgen -W`, which re-expands words and
# would execute a `$(...)`/backtick embedded in a hostile name).

# State-only names (local containers): safe source for down/logs/purge.
__agent_env_names_local() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-env"
    local f base
    [[ -d "${state_dir}" ]] || return 0
    for f in "${state_dir}"/*.port; do
        [[ -e "${f}" ]] || continue
        base="${f##*/}"
        printf '%s\n' "${base%.port}"
    done
}

# hosts.conf-derived names (remote targets): only meaningful for attach.
__agent_env_names_hosts() {
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/agent-env"
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
__agent_env_names() {
    { __agent_env_names_local; __agent_env_names_hosts; } | LC_ALL=C sort -u
}

# Append names emitted by $1 that prefix-match $cur to COMPREPLY, WITHOUT the
# word re-expansion `compgen -W` performs (which would run command
# substitutions embedded in a hostile name). $cur is set by the caller.
__agent_env_add_names() {
    local n
    while IFS= read -r n; do
        [[ -n "${n}" && "${n}" == "${cur}"* ]] && COMPREPLY+=("${n}")
    done < <("$1")
}

_agent_env_filedir() {
    local kind="${1:-}"  # 'd' => directories only, else files
    if declare -F _filedir >/dev/null 2>&1; then
        _filedir ${kind:+"-${kind}"}
    else
        local IFS=$'\n'
        COMPREPLY=( $(compgen ${kind:+-${kind}} -- "${cur}") )
    fi
}

_agent_env() {
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
    local subcommands="build up down purge list attach logs menu completions --self-test --help"

    # The subcommand is the first non-option word after `agent-env`.
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
        up)
            if [[ "${prev}" == "--mount" ]]; then
                _agent_env_filedir d       # --mount takes a directory
                return 0
            fi
            if [[ "${prev}" == "--env-file" ]]; then
                _agent_env_filedir          # --env-file takes a file path
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--mount --env-file" -- "${cur}") )
                return 0
            fi
            __agent_env_add_names __agent_env_names       # arbitrary name; union is fine
            ;;
        down)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--purge -y --yes" -- "${cur}") )
                return 0
            fi
            __agent_env_add_names __agent_env_names_local # local runtime only
            ;;
        purge)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-y --yes" -- "${cur}") )
                return 0
            fi
            __agent_env_add_names __agent_env_names_local # local runtime only
            ;;
        list)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--json" -- "${cur}") )
            fi
            ;;
        attach)
            # --user/--host take a value we don't complete; suppress name fallback.
            if [[ "${prev}" == "--user" || "${prev}" == "--host" ]]; then
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--local --remote --user --host" -- "${cur}") )
                return 0
            fi
            __agent_env_add_names __agent_env_names       # local + remote hosts.conf
            ;;
        logs)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--no-follow" -- "${cur}") )
                return 0
            fi
            __agent_env_add_names __agent_env_names_local # local runtime only
            ;;
        completions)
            COMPREPLY=( $(compgen -W "bash zsh" -- "${cur}") )
            ;;
        build|menu)
            : # build takes a free-form tag; menu takes nothing.
            ;;
    esac
}

complete -F _agent_env agent-env
