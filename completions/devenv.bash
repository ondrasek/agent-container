# bash completion for `devenv` (bin/devenv).
#
# Install (interactive):   source /path/to/completions/devenv.bash
# Install (system-wide):   copy to a bash-completion dir (see README "Shell completions").
#
# Completion keys off the command NAME, so `devenv` must be on PATH
# (symlink bin/devenv into ~/.local/bin). Works with or without the
# bash-completion package loaded (graceful fallback below).
#
# Container names are sourced directly in-shell — no docker/podman/python is
# ever invoked on TAB. The candidate set is the de-duplicated union of:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/devenv/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and never executed/sourced.

__devenv_names() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/devenv"
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/devenv"
    local hosts="${config_dir}/hosts.conf"
    local f base line key
    {
        if [[ -d "${state_dir}" ]]; then
            for f in "${state_dir}"/*.port; do
                [[ -e "${f}" ]] || continue
                base="${f##*/}"
                printf '%s\n' "${base%.port}"
            done
        fi
        if [[ -f "${hosts}" ]]; then
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
        fi
    } | LC_ALL=C sort -u
}

_devenv_filedir_d() {
    if declare -F _filedir >/dev/null 2>&1; then
        _filedir -d
    else
        local IFS=$'\n'
        COMPREPLY=( $(compgen -d -- "${cur}") )
    fi
}

_devenv() {
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

    local subcommands="build up down list attach logs help completions"

    # The subcommand is the first non-option word after `devenv`.
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

    case "${sub}" in
        up)
            if [[ "${prev}" == "--mount" ]]; then
                _devenv_filedir_d
                return 0
            fi
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--mount" -- "${cur}") )
                return 0
            fi
            COMPREPLY=( $(compgen -W "$(__devenv_names)" -- "${cur}") )
            ;;
        down)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "--purge" -- "${cur}") )
                return 0
            fi
            COMPREPLY=( $(compgen -W "$(__devenv_names)" -- "${cur}") )
            ;;
        attach|logs)
            COMPREPLY=( $(compgen -W "$(__devenv_names)" -- "${cur}") )
            ;;
        completions)
            COMPREPLY=( $(compgen -W "bash zsh" -- "${cur}") )
            ;;
        build|list|help)
            : # build takes a free-form tag; list/help take nothing.
            ;;
    esac
}

complete -F _devenv devenv
