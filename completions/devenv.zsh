#compdef devenv
# zsh completion for `devenv` (bin/devenv).
#
# Install (autoload):  copy/symlink this file as `_devenv` into a dir on $fpath
#                      (e.g. ~/.zfunc), then `autoload -U compinit && compinit`.
# Install (source):    source /path/to/completions/devenv.zsh from ~/.zshrc
#                      AFTER `compinit` has run.
#
# Completion keys off the command NAME, so `devenv` must be on PATH
# (symlink bin/devenv into ~/.local/bin).
#
# Container names are gathered directly in-shell — no docker/podman/python is
# invoked on TAB. Candidate names come from:
#   * basenames of ${XDG_STATE_HOME:-$HOME/.local/state}/devenv/*.port (minus .port)
#   * hosts.conf keys ending in _HOST, lowercased with '_' -> '-'
# Missing dirs/files are tolerated silently. hosts.conf is parsed with shell
# builtins only and never executed/sourced. Names go through `compadd -a`
# (array add), so an embedded `$(...)` in a hostile name is never expanded.

# Gather state-file names into the caller's `names` array.
__devenv_gather_local() {
    local state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/devenv" f
    for f in "$state_dir"/*.port(N); do
        names+=("${f:t:r}")
    done
}

# Gather hosts.conf-derived names into the caller's `names` array.
__devenv_gather_hosts() {
    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/devenv"
    local hosts="${config_dir}/hosts.conf" line key
    [[ -f "$hosts" ]] || return
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"
        [[ -z "$line" || "$line" == '#'* ]] && continue
        line="${line#export }"
        line="${line#"${line%%[![:space:]]*}"}"
        key="${line%%=*}"
        key="${key%"${key##*[![:space:]]}"}"
        [[ "$key" == *_HOST ]] || continue
        key="${key%_HOST}"
        key="${key//_/-}"
        names+=("${(L)key}")
    done < "$hosts"
}

# State-only names (local containers): safe source for down/logs.
__devenv_names_local() {
    local -aU names
    __devenv_gather_local
    compadd -a names
}

# Union (local + remote): used by up/attach.
__devenv_names() {
    local -aU names
    __devenv_gather_local
    __devenv_gather_hosts
    compadd -a names
}

_devenv() {
    local context state state_descr line
    typeset -A opt_args
    local -a cmds
    cmds=(
        'build:Build the image at the repo root'
        'up:Start a container (detached)'
        'down:Stop and remove a container'
        'list:List running devenv containers'
        'attach:Attach via ssh + tmux'
        'logs:Tail container logs'
        'completions:Print a checked-in completion script'
        'help:Show usage'
    )

    _arguments -C \
        '1:command:->command' \
        '*::arg:->args' && return 0

    case $state in
        command)
            _describe -t commands 'devenv command' cmds
            ;;
        args)
            case $line[1] in
                up)
                    _arguments \
                        '*--mount[Bind-mount a host dir read-write]:directory:_files -/' \
                        '*:container:__devenv_names'
                    ;;
                down)
                    _arguments \
                        '--purge[Also delete all per-container volumes]' \
                        '*:container:__devenv_names_local'
                    ;;
                logs)
                    _arguments '*:container:__devenv_names_local'
                    ;;
                attach)
                    _arguments '*:container:__devenv_names'
                    ;;
                completions)
                    _arguments '1:shell:(bash zsh)'
                    ;;
            esac
            ;;
    esac
}

# Dual-mode: works whether autoloaded from $fpath as `_devenv` or sourced.
if [[ "$funcstack[1]" == "_devenv" ]]; then
    _devenv "$@"
else
    (( $+functions[compdef] )) && compdef _devenv devenv
fi
